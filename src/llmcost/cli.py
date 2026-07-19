"""Command-line interface for llmcost.

Stdlib only: argparse for parsing, decimal for money, json/csv for machine
output. All cost math lives in :mod:`llmcost.core`.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from decimal import ROUND_HALF_UP, Decimal

from . import __version__
from .core import (
    CostEstimate,
    LLMCostError,
    PricingTable,
    estimate_cost,
    filter_by_provider,
    load_pricing,
    parse_token_amount,
    resolve_models,
    sort_estimates,
)

DAYS_PER_MONTH = 30

_SMALL = Decimal("0.0001")
_LARGE = Decimal("0.01")


def format_money(value: Decimal) -> str:
    """Format a USD amount: 4 decimals under $100, 2 decimals from $100 up."""
    quantum = _LARGE if value >= 100 else _SMALL
    return f"${value.quantize(quantum, rounding=ROUND_HALF_UP)}"


def _token_amount(text: str) -> int:
    try:
        return parse_token_amount(text)
    except LLMCostError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1: {text!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llmcost",
        description=(
            "Estimate and compare LLM API costs across providers, fully offline. "
            "Prices are an embedded snapshot and can change at any time; the "
            "providers' own pricing pages are authoritative."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--pricing",
        metavar="FILE",
        help="JSON file that replaces the embedded pricing table (same schema)",
    )
    parser.add_argument(
        "--in",
        "--input-tokens",
        dest="input_tokens",
        type=_token_amount,
        default=0,
        metavar="N",
        help="input (prompt) tokens per request, e.g. 500000, 500k, 2m, 1.5m",
    )
    parser.add_argument(
        "--out",
        "--output-tokens",
        dest="output_tokens",
        type=_token_amount,
        default=0,
        metavar="N",
        help="output (completion) tokens per request",
    )
    parser.add_argument(
        "--cached",
        dest="cached_tokens",
        type=_token_amount,
        default=0,
        metavar="N",
        help="portion of input tokens served from the provider cache",
    )
    parser.add_argument(
        "--model",
        "-m",
        action="append",
        default=None,
        metavar="NAME",
        help=(
            "model to include (repeatable). Exact, unique-prefix, or unique-"
            "substring match; ambiguous queries list the candidates. Default: all models"
        ),
    )
    parser.add_argument(
        "--provider",
        metavar="NAME",
        help="only include models from this provider (anthropic, openai, google, ...)",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="apply batch API pricing where the model has it",
    )
    parser.add_argument(
        "--per",
        choices=("request", "day", "month"),
        default="request",
        help="period the token amounts describe (default: request)",
    )
    parser.add_argument(
        "--requests",
        type=_positive_int,
        default=1,
        metavar="N",
        help="number of requests per period to scale by (default: 1)",
    )
    parser.add_argument(
        "--month",
        action="store_true",
        help="project a --per day workload to a 30-day month (or label a --per month one)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument("--csv", action="store_true", help="emit CSV instead of a table")
    parser.add_argument(
        "--sort",
        choices=("cost", "name"),
        default="cost",
        help="sort by total cost (ascending) or model name (default: cost)",
    )
    parser.add_argument(
        "--top",
        type=_positive_int,
        default=None,
        metavar="N",
        help="only show the first N rows after sorting",
    )

    subparsers = parser.add_subparsers(dest="command")
    models_parser = subparsers.add_parser(
        "models",
        help="list the models in the pricing table with their snapshot date",
    )
    models_parser.add_argument("--pricing", metavar="FILE", help="pricing table override")
    models_parser.add_argument("--provider", metavar="NAME", help="filter by provider")
    models_parser.add_argument("--json", action="store_true", help="emit JSON")
    return parser


def _render_table(rows: list[list[str]], header: list[str]) -> str:
    widths = [len(cell) for cell in header]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = []
    for row in [header, *rows]:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(lines)


def _period_label(per: str, month: bool) -> str:
    return "month" if month else per


def _disclaimer(table: PricingTable) -> str:
    return (
        f"Prices are a snapshot as of {table.as_of.isoformat()} and can change at "
        "any time; authoritative prices live with each provider."
    )


def run_models(args: argparse.Namespace) -> int:
    table = load_pricing(args.pricing)
    models = table.models
    if args.provider:
        models = filter_by_provider(models, args.provider)
        if not models:
            print(f"llmcost: no models for provider {args.provider!r}", file=sys.stderr)
            return 1
    if args.json:
        payload = {
            "as_of": table.as_of.isoformat(),
            "currency": table.currency,
            "sources": table.sources,
            "models": [
                {
                    "provider": m.provider,
                    "model": m.model,
                    "input": str(m.input),
                    "output": str(m.output),
                    "cached_input": None if m.cached_input is None else str(m.cached_input),
                    "batch_input": None if m.batch_input is None else str(m.batch_input),
                    "batch_output": None if m.batch_output is None else str(m.batch_output),
                    "notes": m.notes,
                }
                for m in models
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0
    header = ["MODEL", "PROVIDER", "INPUT", "OUTPUT", "CACHED-IN", "BATCH-IN", "BATCH-OUT"]
    rows = [
        [
            m.model,
            m.provider,
            str(m.input),
            str(m.output),
            "-" if m.cached_input is None else str(m.cached_input),
            "-" if m.batch_input is None else str(m.batch_input),
            "-" if m.batch_output is None else str(m.batch_output),
        ]
        for m in models
    ]
    print(f"Pricing snapshot as of {table.as_of.isoformat()} (USD per 1M tokens)")
    print(_render_table(rows, header))
    print(file=sys.stderr)
    print(_disclaimer(table), file=sys.stderr)
    return 0


def run_estimate(args: argparse.Namespace) -> int:
    if args.json and args.csv:
        print("llmcost: choose one of --json or --csv", file=sys.stderr)
        return 2
    if args.input_tokens == 0 and args.output_tokens == 0:
        print(
            "llmcost: nothing to estimate; pass --in and/or --out "
            "(see llmcost --help)",
            file=sys.stderr,
        )
        return 2
    if args.month and args.per == "request":
        print("llmcost: --month needs --per day or --per month", file=sys.stderr)
        return 2

    table = load_pricing(args.pricing)
    models = table.models
    if args.provider:
        models = filter_by_provider(models, args.provider)
        if not models:
            print(f"llmcost: no models for provider {args.provider!r}", file=sys.stderr)
            return 1
    if args.model:
        models = resolve_models(args.model, models)

    multiplier = args.requests
    if args.month and args.per == "day":
        multiplier *= DAYS_PER_MONTH

    estimates = [
        estimate_cost(
            m,
            args.input_tokens,
            args.output_tokens,
            args.cached_tokens,
            batch=args.batch,
            multiplier=multiplier,
        )
        for m in models
    ]
    estimates = sort_estimates(estimates, args.sort)
    if args.top is not None:
        estimates = estimates[: args.top]

    period = _period_label(args.per, args.month)
    if args.json:
        print(_to_json(args, table, estimates, period, multiplier))
    elif args.csv:
        sys.stdout.write(_to_csv(estimates))
    else:
        print(_to_table(args, table, estimates, period))
        print(file=sys.stderr)
        print(_disclaimer(table), file=sys.stderr)
    return 0


def _to_table(
    args: argparse.Namespace,
    table: PricingTable,
    estimates: list[CostEstimate],
    period: str,
) -> str:
    show_cached = args.cached_tokens > 0
    header = ["MODEL", "PROVIDER", "INPUT", "OUTPUT", "TOTAL"]
    if show_cached:
        header.insert(3, "CACHED")
    rows = []
    for est in estimates:
        row = [
            est.pricing.model + (" (batch)" if est.batch_applied else ""),
            est.pricing.provider,
            format_money(est.input_cost),
            format_money(est.output_cost),
            format_money(est.total),
        ]
        if show_cached:
            row.insert(3, format_money(est.cached_cost))
        rows.append(row)
    workload = (
        f"{args.input_tokens:,} in / {args.output_tokens:,} out tokens"
        + (f" ({args.cached_tokens:,} cached)" if show_cached else "")
        + (f" x {args.requests:,} requests" if args.requests > 1 else "")
    )
    title = f"Cost per {period} for {workload} (USD, prices as of {table.as_of.isoformat()})"
    return title + "\n" + _render_table(rows, header)


def _to_json(
    args: argparse.Namespace,
    table: PricingTable,
    estimates: list[CostEstimate],
    period: str,
    multiplier: int,
) -> str:
    payload = {
        "as_of": table.as_of.isoformat(),
        "currency": table.currency,
        "period": period,
        "input_tokens": args.input_tokens,
        "output_tokens": args.output_tokens,
        "cached_tokens": args.cached_tokens,
        "requests": args.requests,
        "multiplier": multiplier,
        "batch": args.batch,
        "results": [
            {
                "model": est.pricing.model,
                "provider": est.pricing.provider,
                "input_cost": str(est.input_cost),
                "cached_cost": str(est.cached_cost),
                "output_cost": str(est.output_cost),
                "total": str(est.total),
                "batch_applied": est.batch_applied,
                "notes": est.pricing.notes,
            }
            for est in estimates
        ],
    }
    return json.dumps(payload, indent=2)


def _to_csv(estimates: list[CostEstimate]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        ["model", "provider", "input_cost", "cached_cost", "output_cost", "total", "batch_applied"]
    )
    for est in estimates:
        writer.writerow(
            [
                est.pricing.model,
                est.pricing.provider,
                str(est.input_cost),
                str(est.cached_cost),
                str(est.output_cost),
                str(est.total),
                "true" if est.batch_applied else "false",
            ]
        )
    return buffer.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "models":
            return run_models(args)
        return run_estimate(args)
    except LLMCostError as exc:
        print(f"llmcost: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"llmcost: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
