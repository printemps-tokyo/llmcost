"""Pricing table schema validation and embedded-data sanity tests."""

import unittest
from datetime import date
from decimal import Decimal

from llmcost.core import PricingError, load_pricing, validate_pricing


def minimal_data(**overrides: object) -> dict:
    data: dict = {
        "as_of": "2026-07-19",
        "currency": "USD",
        "sources": {"test": "https://example.com/pricing"},
        "models": [
            {"provider": "test", "model": "test-model", "input": "1", "output": "2"}
        ],
    }
    data.update(overrides)
    return data


class ValidatePricingTest(unittest.TestCase):
    def test_minimal_valid_table(self) -> None:
        table = validate_pricing(minimal_data())
        self.assertEqual(table.as_of, date(2026, 7, 19))
        self.assertEqual(table.models[0].input, Decimal("1"))
        self.assertIsNone(table.models[0].cached_input)

    def test_rejects_non_object(self) -> None:
        with self.assertRaises(PricingError):
            validate_pricing([])

    def test_rejects_missing_as_of(self) -> None:
        data = minimal_data()
        del data["as_of"]
        with self.assertRaises(PricingError):
            validate_pricing(data)

    def test_rejects_unparseable_as_of(self) -> None:
        with self.assertRaises(PricingError):
            validate_pricing(minimal_data(as_of="July 19, 2026"))

    def test_rejects_empty_models(self) -> None:
        with self.assertRaises(PricingError):
            validate_pricing(minimal_data(models=[]))

    def test_rejects_missing_required_fields(self) -> None:
        for missing in ["provider", "model", "input", "output"]:
            model = {"provider": "p", "model": "m", "input": "1", "output": "2"}
            del model[missing]
            with self.assertRaises(PricingError, msg=missing):
                validate_pricing(minimal_data(models=[model]))

    def test_rejects_non_positive_prices(self) -> None:
        for bad in ["0", "-1"]:
            model = {"provider": "p", "model": "m", "input": bad, "output": "2"}
            with self.assertRaises(PricingError, msg=bad):
                validate_pricing(minimal_data(models=[model]))

    def test_rejects_non_numeric_price(self) -> None:
        model = {"provider": "p", "model": "m", "input": "free", "output": "2"}
        with self.assertRaises(PricingError):
            validate_pricing(minimal_data(models=[model]))

    def test_rejects_float_prices(self) -> None:
        # JSON floats are rejected so prices always round-trip via Decimal.
        model = {"provider": "p", "model": "m", "input": 0.1, "output": "2"}
        with self.assertRaises(PricingError):
            validate_pricing(minimal_data(models=[model]))

    def test_rejects_negative_optional_price(self) -> None:
        model = {
            "provider": "p",
            "model": "m",
            "input": "1",
            "output": "2",
            "cached_input": "-0.1",
        }
        with self.assertRaises(PricingError):
            validate_pricing(minimal_data(models=[model]))

    def test_rejects_duplicate_models(self) -> None:
        model = {"provider": "p", "model": "m", "input": "1", "output": "2"}
        with self.assertRaises(PricingError):
            validate_pricing(minimal_data(models=[model, dict(model)]))


class EmbeddedPricingTest(unittest.TestCase):
    def test_embedded_table_loads_and_validates(self) -> None:
        table = load_pricing()
        self.assertGreaterEqual(len(table.models), 10)
        self.assertIsInstance(table.as_of, date)
        self.assertEqual(table.currency, "USD")

    def test_every_entry_has_required_fields_and_positive_prices(self) -> None:
        table = load_pricing()
        for model in table.models:
            self.assertTrue(model.provider)
            self.assertTrue(model.model)
            self.assertGreater(model.input, 0)
            self.assertGreater(model.output, 0)
            for optional in (model.cached_input, model.batch_input, model.batch_output):
                if optional is not None:
                    self.assertGreater(optional, 0)

    def test_covers_big_three_providers(self) -> None:
        providers = {m.provider for m in load_pricing().models}
        self.assertLessEqual({"anthropic", "openai", "google"}, providers)

    def test_every_provider_has_a_source_url(self) -> None:
        table = load_pricing()
        for provider in {m.provider for m in table.models}:
            self.assertIn(provider, table.sources)
            self.assertTrue(table.sources[provider].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
