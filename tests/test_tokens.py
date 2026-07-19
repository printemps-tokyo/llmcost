"""Token-amount parsing tests."""

import unittest

from llmcost.core import TokenAmountError, parse_token_amount


class ParseTokenAmountTest(unittest.TestCase):
    def test_plain_integers(self) -> None:
        self.assertEqual(parse_token_amount("0"), 0)
        self.assertEqual(parse_token_amount("42"), 42)
        self.assertEqual(parse_token_amount("500000"), 500_000)

    def test_k_suffix(self) -> None:
        self.assertEqual(parse_token_amount("500k"), 500_000)
        self.assertEqual(parse_token_amount("1K"), 1_000)
        self.assertEqual(parse_token_amount("1.5k"), 1_500)

    def test_m_suffix(self) -> None:
        self.assertEqual(parse_token_amount("2m"), 2_000_000)
        self.assertEqual(parse_token_amount("2M"), 2_000_000)
        self.assertEqual(parse_token_amount("1.5m"), 1_500_000)
        self.assertEqual(parse_token_amount("0.25m"), 250_000)

    def test_separators_and_whitespace(self) -> None:
        self.assertEqual(parse_token_amount(" 500k "), 500_000)
        self.assertEqual(parse_token_amount("1,000,000"), 1_000_000)
        self.assertEqual(parse_token_amount("1_000"), 1_000)

    def test_rejects_garbage(self) -> None:
        for bad in ["", "  ", "abc", "1.2.3", "k", "m", "12x", "1e6", "5 tokens", "$5"]:
            with self.assertRaises(TokenAmountError, msg=bad):
                parse_token_amount(bad)

    def test_rejects_negative(self) -> None:
        with self.assertRaises(TokenAmountError):
            parse_token_amount("-5")
        with self.assertRaises(TokenAmountError):
            parse_token_amount("-1k")

    def test_rejects_fractional_token_counts(self) -> None:
        with self.assertRaises(TokenAmountError):
            parse_token_amount("1.5")
        with self.assertRaises(TokenAmountError):
            parse_token_amount("1.2345k")

    def test_rejects_non_string(self) -> None:
        with self.assertRaises(TokenAmountError):
            parse_token_amount(500)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
