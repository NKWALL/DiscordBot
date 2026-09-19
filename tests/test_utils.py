import math
import unittest

from discord_bot.utils import chunk_lines, chunk_text, haversine_km, safe_calculate


class UtilsTests(unittest.TestCase):
    def test_chunk_text_respects_limit(self):
        self.assertEqual(chunk_text("abcdefgh", 3), ["abc", "def", "gh"])

    def test_chunk_lines_preserves_all_lines(self):
        chunks = chunk_lines(["abc", "def", "ghi"], 8)
        self.assertEqual(chunks, ["abc\ndef", "ghi"])

    def test_haversine_returns_zero_for_same_point(self):
        self.assertEqual(haversine_km(22.6, 120.3, 22.6, 120.3), 0)

    def test_safe_calculate_supports_expected_operations(self):
        self.assertEqual(safe_calculate("2^3 + sqrt(9)"), 11)
        self.assertTrue(math.isclose(safe_calculate("sin(0)"), 0))

    def test_safe_calculate_rejects_unsafe_expression(self):
        for expression in ["__import__('os')", "open('x')", "[1, 2]"]:
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                safe_calculate(expression)


if __name__ == "__main__":
    unittest.main()
