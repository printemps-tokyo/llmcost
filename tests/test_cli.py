"""CLI tests: output shapes, flags, and an end-to-end subprocess run."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from llmcost.cli import format_money, main

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def run_cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


class FormatMoneyTest(unittest.TestCase):
    def test_small_amounts_get_four_decimals(self) -> None:
        self.assertEqual(format_money(Decimal("2.2")), "$2.2000")
        self.assertEqual(format_money(Decimal("0.00000042")), "$0.0000")
        self.assertEqual(format_money(Decimal("99.99999")), "$100.0000")

    def test_large_amounts_get_two_decimals(self) -> None:
        self.assertEqual(format_money(Decimal("100")), "$100.00")
        self.assertEqual(format_money(Decimal("12345.678")), "$12345.68")


class EstimateCliTest(unittest.TestCase):
    def test_json_shape(self) -> None:
        code, out, _ = run_cli("--in", "1m", "--out", "1m", "--model", "claude-opus-4-8", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["period"], "request")
        self.assertEqual(payload["input_tokens"], 1_000_000)
        self.assertEqual(len(payload["results"]), 1)
        result = payload["results"][0]
        self.assertEqual(result["model"], "claude-opus-4-8")
        self.assertEqual(result["provider"], "anthropic")
        self.assertEqual(Decimal(result["input_cost"]), Decimal("5"))
        self.assertEqual(Decimal(result["output_cost"]), Decimal("25"))
        self.assertEqual(Decimal(result["total"]), Decimal("30"))
        self.assertFalse(result["batch_applied"])

    def test_csv_shape(self) -> None:
        code, out, _ = run_cli("--in", "500k", "--out", "120k", "--csv", "--top", "2")
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertEqual(
            lines[0],
            "model,provider,input_cost,cached_cost,output_cost,total,batch_applied",
        )
        self.assertEqual(len(lines), 3)  # header + 2 rows
        self.assertEqual(len(lines[1].split(",")), 7)

    def test_default_sort_is_ascending_total(self) -> None:
        code, out, _ = run_cli("--in", "500k", "--out", "120k", "--json")
        self.assertEqual(code, 0)
        totals = [Decimal(r["total"]) for r in json.loads(out)["results"]]
        self.assertEqual(totals, sorted(totals))

    def test_sort_by_name(self) -> None:
        code, out, _ = run_cli("--in", "1k", "--out", "1k", "--sort", "name", "--json")
        self.assertEqual(code, 0)
        names = [r["model"] for r in json.loads(out)["results"]]
        self.assertEqual(names, sorted(names))

    def test_top_limits_rows(self) -> None:
        code, out, _ = run_cli("--in", "1k", "--out", "1k", "--json", "--top", "3")
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)["results"]), 3)

    def test_provider_filter(self) -> None:
        code, out, _ = run_cli("--in", "1k", "--out", "1k", "--provider", "anthropic", "--json")
        self.assertEqual(code, 0)
        providers = {r["provider"] for r in json.loads(out)["results"]}
        self.assertEqual(providers, {"anthropic"})

    def test_unknown_provider_errors(self) -> None:
        code, _, err = run_cli("--in", "1k", "--out", "1k", "--provider", "nvidia")
        self.assertEqual(code, 1)
        self.assertIn("nvidia", err)

    def test_ambiguous_model_lists_candidates(self) -> None:
        code, _, err = run_cli("--in", "1k", "--out", "1k", "--model", "gpt-5.6")
        self.assertEqual(code, 1)
        self.assertIn("ambiguous", err)
        self.assertIn("gpt-5.6-sol", err)
        self.assertIn("gpt-5.6-terra", err)

    def test_unknown_model_errors(self) -> None:
        code, _, err = run_cli("--in", "1k", "--out", "1k", "--model", "no-such-model")
        self.assertEqual(code, 1)
        self.assertIn("no model matches", err)

    def test_per_day_month_projection(self) -> None:
        # 1k input tokens per request, 100 requests/day, projected to 30 days
        code, out, _ = run_cli(
            "--in", "1k", "--model", "claude-haiku-4-5",
            "--per", "day", "--requests", "100", "--month", "--json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["period"], "month")
        self.assertEqual(payload["multiplier"], 3000)
        # 1000 tokens at $1/MTok = $0.001, x3000 = $3
        self.assertEqual(Decimal(payload["results"][0]["total"]), Decimal("3"))

    def test_month_requires_day_or_month_period(self) -> None:
        code, _, err = run_cli("--in", "1k", "--month")
        self.assertEqual(code, 2)
        self.assertIn("--per day", err)

    def test_requires_some_tokens(self) -> None:
        code, _, err = run_cli()
        self.assertEqual(code, 2)
        self.assertIn("nothing to estimate", err)

    def test_rejects_json_and_csv_together(self) -> None:
        code, _, _ = run_cli("--in", "1k", "--json", "--csv")
        self.assertEqual(code, 2)

    def test_invalid_token_amount_is_usage_error(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            run_cli("--in", "abc")
        self.assertEqual(ctx.exception.code, 2)

    def test_cached_exceeding_input_errors(self) -> None:
        code, _, err = run_cli("--in", "1k", "--cached", "2k", "--model", "claude-haiku-4-5")
        self.assertEqual(code, 1)
        self.assertIn("cached_tokens", err)

    def test_batch_flag_marks_rows(self) -> None:
        code, out, _ = run_cli(
            "--in", "1m", "--out", "1m", "--model", "claude-haiku-4-5", "--batch", "--json"
        )
        self.assertEqual(code, 0)
        result = json.loads(out)["results"][0]
        self.assertTrue(result["batch_applied"])
        # batch: $0.50 + $2.50 per MTok
        self.assertEqual(Decimal(result["total"]), Decimal("3"))

    def test_table_output_and_disclaimer(self) -> None:
        code, out, err = run_cli("--in", "500k", "--out", "120k")
        self.assertEqual(code, 0)
        self.assertIn("MODEL", out)
        self.assertIn("TOTAL", out)
        self.assertIn("snapshot", err)

    def test_pricing_override_file(self) -> None:
        data = {
            "as_of": "2026-01-01",
            "sources": {"custom": "https://example.com"},
            "models": [
                {"provider": "custom", "model": "my-model", "input": "1", "output": "1"}
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(data, handle)
            path = handle.name
        try:
            code, out, _ = run_cli("--pricing", path, "--in", "1m", "--out", "1m", "--json")
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["as_of"], "2026-01-01")
            self.assertEqual(payload["results"][0]["model"], "my-model")
            self.assertEqual(Decimal(payload["results"][0]["total"]), Decimal("2"))
        finally:
            os.unlink(path)

    def test_missing_pricing_file_errors(self) -> None:
        code, _, err = run_cli("--pricing", "/no/such/file.json", "--in", "1k")
        self.assertEqual(code, 1)
        self.assertIn("file", err.lower())


class ModelsCliTest(unittest.TestCase):
    def test_models_lists_embedded_table_with_as_of(self) -> None:
        code, out, _ = run_cli("models")
        self.assertEqual(code, 0)
        self.assertIn("as of", out)
        self.assertIn("claude-opus-4-8", out)
        self.assertIn("gemini-3.5-flash", out)

    def test_models_json(self) -> None:
        code, out, _ = run_cli("models", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertIn("as_of", payload)
        self.assertIn("sources", payload)
        self.assertGreaterEqual(len(payload["models"]), 10)

    def test_models_provider_filter(self) -> None:
        code, out, _ = run_cli("models", "--provider", "deepseek", "--json")
        self.assertEqual(code, 0)
        providers = {m["provider"] for m in json.loads(out)["models"]}
        self.assertEqual(providers, {"deepseek"})


class EndToEndSubprocessTest(unittest.TestCase):
    def test_python_dash_m_llmcost(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        proc = subprocess.run(
            [
                sys.executable, "-m", "llmcost",
                "--in", "500k", "--out", "120k",
                "--model", "claude-sonnet-5", "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        result = payload["results"][0]
        self.assertEqual(result["model"], "claude-sonnet-5")
        # 500k at $2 + 120k at $10 = $1.00 + $1.20
        self.assertEqual(Decimal(result["total"]), Decimal("2.2"))

    def test_python_dash_m_help(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        proc = subprocess.run(
            [sys.executable, "-m", "llmcost", "--help"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("llmcost", proc.stdout)


if __name__ == "__main__":
    unittest.main()
