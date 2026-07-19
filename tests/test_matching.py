"""Model matching tests: exact beats prefix, unique prefix/substring, ambiguity."""

import unittest
from decimal import Decimal

from llmcost.core import (
    AmbiguousModelError,
    ModelPricing,
    UnknownModelError,
    filter_by_provider,
    resolve_model,
    resolve_models,
)


def entry(model: str, provider: str = "test") -> ModelPricing:
    return ModelPricing(provider=provider, model=model, input=Decimal(1), output=Decimal(2))


MODELS = (
    entry("gpt-5", "openai"),
    entry("gpt-5-mini", "openai"),
    entry("gpt-5-nano", "openai"),
    entry("claude-haiku-4-5", "anthropic"),
    entry("claude-sonnet-5", "anthropic"),
    entry("gemini-3.5-flash", "google"),
)


class ResolveModelTest(unittest.TestCase):
    def test_exact_match_beats_prefix_expansion(self) -> None:
        # "gpt-5" is both an exact name and a prefix of gpt-5-mini/nano;
        # the exact match must win instead of raising ambiguity.
        self.assertEqual(resolve_model("gpt-5", MODELS).model, "gpt-5")

    def test_exact_match_is_case_insensitive(self) -> None:
        self.assertEqual(resolve_model("GPT-5", MODELS).model, "gpt-5")

    def test_unique_prefix_resolves(self) -> None:
        self.assertEqual(resolve_model("gpt-5-m", MODELS).model, "gpt-5-mini")
        self.assertEqual(resolve_model("claude-h", MODELS).model, "claude-haiku-4-5")

    def test_ambiguous_prefix_lists_candidates(self) -> None:
        with self.assertRaises(AmbiguousModelError) as ctx:
            resolve_model("gpt-5-", MODELS)
        self.assertEqual(ctx.exception.candidates, ["gpt-5-mini", "gpt-5-nano"])

    def test_unique_substring_resolves(self) -> None:
        self.assertEqual(resolve_model("haiku", MODELS).model, "claude-haiku-4-5")
        self.assertEqual(resolve_model("flash", MODELS).model, "gemini-3.5-flash")

    def test_ambiguous_substring_lists_candidates(self) -> None:
        with self.assertRaises(AmbiguousModelError) as ctx:
            resolve_model("claude", MODELS)
        self.assertEqual(
            ctx.exception.candidates, ["claude-haiku-4-5", "claude-sonnet-5"]
        )

    def test_unknown_model_raises(self) -> None:
        with self.assertRaises(UnknownModelError):
            resolve_model("mistral-large", MODELS)

    def test_empty_query_raises(self) -> None:
        with self.assertRaises(UnknownModelError):
            resolve_model("   ", MODELS)

    def test_resolve_models_deduplicates_preserving_order(self) -> None:
        resolved = resolve_models(["haiku", "gpt-5", "claude-h"], MODELS)
        self.assertEqual([m.model for m in resolved], ["claude-haiku-4-5", "gpt-5"])


class ProviderFilterTest(unittest.TestCase):
    def test_filter_is_case_insensitive_exact(self) -> None:
        openai_only = filter_by_provider(MODELS, "OpenAI")
        self.assertEqual({m.provider for m in openai_only}, {"openai"})
        self.assertEqual(len(openai_only), 3)

    def test_filter_unknown_provider_empty(self) -> None:
        self.assertEqual(filter_by_provider(MODELS, "nvidia"), ())


if __name__ == "__main__":
    unittest.main()
