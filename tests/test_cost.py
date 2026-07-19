"""Cost-math tests against hand-computed values (Decimal exactness)."""

import unittest
from decimal import Decimal

from llmcost.core import LLMCostError, ModelPricing, estimate_cost, sort_estimates


def entry(**overrides: object) -> ModelPricing:
    defaults: dict = {
        "provider": "test",
        "model": "test-model",
        "input": Decimal("2"),
        "output": Decimal("10"),
        "cached_input": Decimal("0.20"),
        "batch_input": Decimal("1"),
        "batch_output": Decimal("5"),
    }
    defaults.update(overrides)
    return ModelPricing(**defaults)


class EstimateCostTest(unittest.TestCase):
    def test_basic_cost(self) -> None:
        # 500k in at $2/MTok = $1.00, 120k out at $10/MTok = $1.20
        est = estimate_cost(entry(), 500_000, 120_000)
        self.assertEqual(est.input_cost, Decimal("1"))
        self.assertEqual(est.output_cost, Decimal("1.2"))
        self.assertEqual(est.cached_cost, Decimal("0"))
        self.assertEqual(est.total, Decimal("2.2"))
        self.assertFalse(est.batch_applied)

    def test_decimal_exactness_tiny_amounts(self) -> None:
        # 3 tokens at $0.14/MTok is exactly $0.00000042 - no float noise.
        pricing = entry(input=Decimal("0.14"), output=Decimal("0.28"), cached_input=None)
        est = estimate_cost(pricing, 3, 0)
        self.assertEqual(est.input_cost, Decimal("0.00000042"))
        self.assertEqual(est.total, Decimal("0.00000042"))

    def test_cached_input_path(self) -> None:
        # 1m in, 400k cached: 600k at $2 = $1.20, 400k at $0.20 = $0.08
        est = estimate_cost(entry(), 1_000_000, 0, cached_tokens=400_000)
        self.assertEqual(est.input_cost, Decimal("1.2"))
        self.assertEqual(est.cached_cost, Decimal("0.08"))
        self.assertEqual(est.total, Decimal("1.28"))

    def test_cached_without_cached_rate_bills_full_input(self) -> None:
        pricing = entry(cached_input=None)
        est = estimate_cost(pricing, 1_000_000, 0, cached_tokens=400_000)
        self.assertEqual(est.input_cost, Decimal("1.2"))
        self.assertEqual(est.cached_cost, Decimal("0.8"))
        self.assertEqual(est.total, Decimal("2"))

    def test_batch_path(self) -> None:
        # 2m in at $1 = $2, 500k out at $5 = $2.50
        est = estimate_cost(entry(), 2_000_000, 500_000, batch=True)
        self.assertTrue(est.batch_applied)
        self.assertEqual(est.input_cost, Decimal("2"))
        self.assertEqual(est.output_cost, Decimal("2.5"))
        self.assertEqual(est.total, Decimal("4.5"))

    def test_batch_falls_back_when_unavailable(self) -> None:
        pricing = entry(batch_input=None, batch_output=None)
        est = estimate_cost(pricing, 2_000_000, 500_000, batch=True)
        self.assertFalse(est.batch_applied)
        self.assertEqual(est.total, Decimal("9"))  # 2m*$2 + 500k*$10

    def test_batch_bills_all_input_at_batch_rate(self) -> None:
        # In batch mode cached tokens are not split out.
        est = estimate_cost(entry(), 1_000_000, 0, cached_tokens=500_000, batch=True)
        self.assertEqual(est.input_cost, Decimal("1"))
        self.assertEqual(est.cached_cost, Decimal("0"))

    def test_multiplier_scales_all_components(self) -> None:
        est = estimate_cost(entry(), 1_000, 1_000, multiplier=3000)
        # per request: in 0.002, out 0.01 -> x3000: 6 + 30
        self.assertEqual(est.input_cost, Decimal("6.000"))
        self.assertEqual(est.output_cost, Decimal("30.000"))
        self.assertEqual(est.total, Decimal("36.000"))

    def test_zero_tokens(self) -> None:
        est = estimate_cost(entry(), 0, 0)
        self.assertEqual(est.total, Decimal("0"))

    def test_rejects_cached_exceeding_input(self) -> None:
        with self.assertRaises(LLMCostError):
            estimate_cost(entry(), 100, 0, cached_tokens=101)

    def test_rejects_negative_tokens(self) -> None:
        with self.assertRaises(LLMCostError):
            estimate_cost(entry(), -1, 0)
        with self.assertRaises(LLMCostError):
            estimate_cost(entry(), 0, -1)
        with self.assertRaises(LLMCostError):
            estimate_cost(entry(), 0, 0, cached_tokens=-1)

    def test_rejects_bad_multiplier(self) -> None:
        with self.assertRaises(LLMCostError):
            estimate_cost(entry(), 1, 1, multiplier=0)


class SortEstimatesTest(unittest.TestCase):
    def test_sort_by_cost_then_name(self) -> None:
        cheap = estimate_cost(entry(model="bbb", input=Decimal("1"), output=Decimal("1")), 1_000_000, 0)
        pricey = estimate_cost(entry(model="aaa", input=Decimal("9"), output=Decimal("9")), 1_000_000, 0)
        same_price = estimate_cost(entry(model="ccc", input=Decimal("1"), output=Decimal("1")), 1_000_000, 0)
        ordered = sort_estimates([pricey, same_price, cheap], "cost")
        self.assertEqual([e.pricing.model for e in ordered], ["bbb", "ccc", "aaa"])

    def test_sort_by_name(self) -> None:
        a = estimate_cost(entry(model="zeta"), 1, 1)
        b = estimate_cost(entry(model="alpha"), 1, 1)
        ordered = sort_estimates([a, b], "name")
        self.assertEqual([e.pricing.model for e in ordered], ["alpha", "zeta"])

    def test_unknown_sort_key(self) -> None:
        with self.assertRaises(LLMCostError):
            sort_estimates([], "price")


if __name__ == "__main__":
    unittest.main()
