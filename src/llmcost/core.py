"""Pure cost math, pricing data handling, and model matching for llmcost.

Everything here is side-effect free (no printing, no argv) so it can be
tested directly. Money math uses decimal.Decimal throughout; prices in the
pricing table are stored as JSON strings and parsed with Decimal to avoid
float rounding surprises.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from importlib import resources
from typing import Any

MTOK = Decimal(1_000_000)

_TOKEN_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)?)(?P<suffix>[km]?)$")
_SUFFIX_SCALE = {"": Decimal(1), "k": Decimal(1_000), "m": Decimal(1_000_000)}


class LLMCostError(Exception):
    """Base class for all llmcost errors."""


class TokenAmountError(LLMCostError):
    """Raised when a token amount string cannot be parsed."""


class PricingError(LLMCostError):
    """Raised when a pricing table fails schema validation."""


class UnknownModelError(LLMCostError):
    """Raised when a model query matches nothing."""

    def __init__(self, query: str, available: list[str]) -> None:
        self.query = query
        self.available = available
        super().__init__(
            f"no model matches {query!r}; known models: {', '.join(available)}"
        )


class AmbiguousModelError(LLMCostError):
    """Raised when a model query matches more than one model."""

    def __init__(self, query: str, candidates: list[str]) -> None:
        self.query = query
        self.candidates = candidates
        super().__init__(
            f"{query!r} is ambiguous; candidates: {', '.join(candidates)}"
        )


@dataclass(frozen=True)
class ModelPricing:
    """Pricing for one model. All prices are USD per 1M tokens."""

    provider: str
    model: str
    input: Decimal
    output: Decimal
    cached_input: Decimal | None = None
    batch_input: Decimal | None = None
    batch_output: Decimal | None = None
    notes: str | None = None


@dataclass(frozen=True)
class PricingTable:
    """A validated pricing snapshot."""

    as_of: date
    currency: str
    sources: dict[str, str]
    models: tuple[ModelPricing, ...]


@dataclass(frozen=True)
class CostEstimate:
    """Cost of one workload on one model, already scaled by the multiplier."""

    pricing: ModelPricing
    input_cost: Decimal
    cached_cost: Decimal
    output_cost: Decimal
    total: Decimal
    batch_applied: bool


def parse_token_amount(text: str) -> int:
    """Parse a token amount such as ``500000``, ``500k``, ``2m``, ``1.5m``.

    Suffixes: ``k`` = 1,000 and ``m`` = 1,000,000 (case-insensitive).
    Commas and underscores are allowed as digit separators. Negative values,
    other suffixes, and amounts that do not resolve to a whole number of
    tokens are rejected.
    """
    if not isinstance(text, str):
        raise TokenAmountError(f"token amount must be a string, got {type(text).__name__}")
    normalized = text.strip().lower().replace(",", "").replace("_", "")
    match = _TOKEN_RE.match(normalized)
    if match is None:
        raise TokenAmountError(f"invalid token amount: {text!r}")
    value = Decimal(match.group("num")) * _SUFFIX_SCALE[match.group("suffix")]
    if value != value.to_integral_value():
        raise TokenAmountError(
            f"token amount does not resolve to a whole number of tokens: {text!r}"
        )
    return int(value)


def _parse_price(entry_name: str, field: str, raw: Any, *, required: bool) -> Decimal | None:
    if raw is None:
        if required:
            raise PricingError(f"model {entry_name!r}: missing required field {field!r}")
        return None
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise PricingError(
            f"model {entry_name!r}: field {field!r} must be a string or integer "
            f"(floats are rejected to keep Decimal exactness), got {type(raw).__name__}"
        )
    try:
        value = Decimal(str(raw))
    except InvalidOperation:
        raise PricingError(f"model {entry_name!r}: field {field!r} is not a number: {raw!r}") from None
    if value <= 0:
        raise PricingError(f"model {entry_name!r}: field {field!r} must be positive, got {raw!r}")
    return value


def validate_pricing(data: Any) -> PricingTable:
    """Validate raw pricing data and return a :class:`PricingTable`.

    Rules: top level must be an object with ``as_of`` (ISO date string),
    ``models`` (non-empty list). Every model entry needs non-empty
    ``provider`` and ``model`` strings plus positive ``input`` and ``output``
    prices; ``cached_input``, ``batch_input``, ``batch_output`` are optional
    but must be positive when present. Duplicate (provider, model) pairs are
    rejected.
    """
    if not isinstance(data, dict):
        raise PricingError("pricing data must be a JSON object")
    raw_as_of = data.get("as_of")
    if not isinstance(raw_as_of, str):
        raise PricingError("pricing data must have an 'as_of' date string")
    try:
        as_of = date.fromisoformat(raw_as_of)
    except ValueError:
        raise PricingError(f"'as_of' is not an ISO date: {raw_as_of!r}") from None

    currency = data.get("currency", "USD")
    if not isinstance(currency, str) or not currency:
        raise PricingError("'currency' must be a non-empty string")

    sources = data.get("sources", {})
    if not isinstance(sources, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in sources.items()
    ):
        raise PricingError("'sources' must be an object mapping provider to URL")

    raw_models = data.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise PricingError("pricing data must have a non-empty 'models' list")

    models: list[ModelPricing] = []
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(raw_models):
        if not isinstance(entry, dict):
            raise PricingError(f"models[{index}] must be an object")
        provider = entry.get("provider")
        model = entry.get("model")
        if not isinstance(provider, str) or not provider:
            raise PricingError(f"models[{index}]: 'provider' must be a non-empty string")
        if not isinstance(model, str) or not model:
            raise PricingError(f"models[{index}]: 'model' must be a non-empty string")
        key = (provider.lower(), model.lower())
        if key in seen:
            raise PricingError(f"duplicate model entry: {provider}/{model}")
        seen.add(key)
        notes = entry.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise PricingError(f"model {model!r}: 'notes' must be a string")
        models.append(
            ModelPricing(
                provider=provider,
                model=model,
                input=_parse_price(model, "input", entry.get("input"), required=True),  # type: ignore[arg-type]
                output=_parse_price(model, "output", entry.get("output"), required=True),  # type: ignore[arg-type]
                cached_input=_parse_price(model, "cached_input", entry.get("cached_input"), required=False),
                batch_input=_parse_price(model, "batch_input", entry.get("batch_input"), required=False),
                batch_output=_parse_price(model, "batch_output", entry.get("batch_output"), required=False),
                notes=notes,
            )
        )
    return PricingTable(as_of=as_of, currency=currency, sources=dict(sources), models=tuple(models))


def load_pricing(path: str | None = None) -> PricingTable:
    """Load and validate the embedded pricing table, or a JSON file override."""
    if path is None:
        raw_text = resources.files("llmcost").joinpath("pricing.json").read_text(encoding="utf-8")
    else:
        with open(path, encoding="utf-8") as handle:
            raw_text = handle.read()
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise PricingError(f"pricing file is not valid JSON: {exc}") from None
    return validate_pricing(data)


def filter_by_provider(models: tuple[ModelPricing, ...], provider: str) -> tuple[ModelPricing, ...]:
    """Case-insensitive exact provider filter."""
    wanted = provider.lower()
    return tuple(m for m in models if m.provider.lower() == wanted)


def resolve_model(query: str, models: tuple[ModelPricing, ...]) -> ModelPricing:
    """Resolve a query to exactly one model.

    Resolution order (all case-insensitive): exact name, then unique prefix,
    then unique substring. Multiple equally good matches raise
    :class:`AmbiguousModelError` listing the candidates; no match raises
    :class:`UnknownModelError`.
    """
    q = query.strip().lower()
    if not q:
        raise UnknownModelError(query, [m.model for m in models])
    exact = [m for m in models if m.model.lower() == q]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise AmbiguousModelError(query, [f"{m.provider}/{m.model}" for m in exact])
    for predicate in (
        lambda name: name.startswith(q),
        lambda name: q in name,
    ):
        matches = [m for m in models if predicate(m.model.lower())]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise AmbiguousModelError(query, sorted(m.model for m in matches))
    raise UnknownModelError(query, [m.model for m in models])


def resolve_models(queries: list[str], models: tuple[ModelPricing, ...]) -> tuple[ModelPricing, ...]:
    """Resolve each query, de-duplicating while preserving order."""
    resolved: list[ModelPricing] = []
    seen: set[tuple[str, str]] = set()
    for query in queries:
        entry = resolve_model(query, models)
        key = (entry.provider, entry.model)
        if key not in seen:
            seen.add(key)
            resolved.append(entry)
    return tuple(resolved)


def estimate_cost(
    pricing: ModelPricing,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    *,
    batch: bool = False,
    multiplier: int = 1,
) -> CostEstimate:
    """Compute the cost of a workload on one model.

    ``cached_tokens`` is the portion of ``input_tokens`` served from the
    provider's prompt/context cache; it is billed at the cached-input rate
    when the model has one (otherwise at the full input rate). With
    ``batch=True`` batch prices are applied where the model has them
    (``batch_applied`` reports whether they were); in batch mode all input
    tokens are billed at the batch input rate because providers do not
    publish a combined batch+cached rate. ``multiplier`` scales the result
    (requests per period, days per month, and so on).
    """
    for name, value in (
        ("input_tokens", input_tokens),
        ("output_tokens", output_tokens),
        ("cached_tokens", cached_tokens),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise LLMCostError(f"{name} must be a non-negative integer, got {value!r}")
    if cached_tokens > input_tokens:
        raise LLMCostError(
            f"cached_tokens ({cached_tokens}) cannot exceed input_tokens ({input_tokens})"
        )
    if not isinstance(multiplier, int) or isinstance(multiplier, bool) or multiplier < 1:
        raise LLMCostError(f"multiplier must be a positive integer, got {multiplier!r}")

    scale = Decimal(multiplier)
    batch_applied = batch and pricing.batch_input is not None and pricing.batch_output is not None
    if batch_applied:
        assert pricing.batch_input is not None and pricing.batch_output is not None
        input_cost = pricing.batch_input * input_tokens / MTOK * scale
        cached_cost = Decimal(0)
        output_cost = pricing.batch_output * output_tokens / MTOK * scale
    else:
        cached_rate = pricing.cached_input if pricing.cached_input is not None else pricing.input
        input_cost = pricing.input * (input_tokens - cached_tokens) / MTOK * scale
        cached_cost = cached_rate * cached_tokens / MTOK * scale
        output_cost = pricing.output * output_tokens / MTOK * scale
    total = input_cost + cached_cost + output_cost
    return CostEstimate(
        pricing=pricing,
        input_cost=input_cost,
        cached_cost=cached_cost,
        output_cost=output_cost,
        total=total,
        batch_applied=batch_applied,
    )


def sort_estimates(estimates: list[CostEstimate], key: str = "cost") -> list[CostEstimate]:
    """Sort estimates by ``cost`` (ascending total) or ``name`` (model name)."""
    if key == "cost":
        return sorted(estimates, key=lambda e: (e.total, e.pricing.model))
    if key == "name":
        return sorted(estimates, key=lambda e: e.pricing.model)
    raise LLMCostError(f"unknown sort key: {key!r}")
