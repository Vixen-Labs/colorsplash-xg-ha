"""Unit tests for cli.py pure-logic helpers.

Covers the name-to-byte and hex-byte parsers that don't need any BLE
hardware. The BLE flow itself is exercised manually against a real
controller and documented in the PR, not unit-tested here.

Run:
    python3 -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from cli import parse_effect, parse_raw, EFFECT_TABLE  # noqa: E402


class ParseEffectTests(unittest.TestCase):
    """`parse_effect` maps human names to command bytes."""

    def test_all_canonical_names(self):
        # Every canonical name from PROTOCOL.md v1.3 must parse.
        expected = {
            "Parisian Blue": 0x08,
            "Brazilian Red": 0x0A,
            "Arctic White": 0x0B,
            "Miami Pink": 0x0C,
            "New Zealand Green": 0x09,
            "Nova": 0x07,
            "Super Nova": 0x02,
            "Northern Lights": 0x03,
            "Tidal Wave": 0x04,
            "Patriot Dream": 0x05,
            "Desert Skies": 0x06,
            "Peruvian Paradise": 0x01,
            "Lock": 0x0D,
            "Return": 0x0E,
            "Standby": 0x00,
        }
        for name, byte in expected.items():
            with self.subTest(name=name):
                self.assertEqual(parse_effect(name), byte)

    def test_common_short_aliases(self):
        self.assertEqual(parse_effect("blue"), 0x08)
        self.assertEqual(parse_effect("red"), 0x0A)
        self.assertEqual(parse_effect("white"), 0x0B)
        self.assertEqual(parse_effect("pink"), 0x0C)
        self.assertEqual(parse_effect("green"), 0x09)
        self.assertEqual(parse_effect("nova"), 0x07)
        self.assertEqual(parse_effect("supernova"), 0x02)
        self.assertEqual(parse_effect("northern"), 0x03)
        self.assertEqual(parse_effect("tidal"), 0x04)
        self.assertEqual(parse_effect("patriot"), 0x05)
        self.assertEqual(parse_effect("desert"), 0x06)
        self.assertEqual(parse_effect("peruvian"), 0x01)
        self.assertEqual(parse_effect("lock"), 0x0D)
        self.assertEqual(parse_effect("return"), 0x0E)
        self.assertEqual(parse_effect("standby"), 0x00)
        self.assertEqual(parse_effect("off"), 0x00)  # alias for standby

    def test_case_insensitive(self):
        self.assertEqual(parse_effect("BLUE"), 0x08)
        self.assertEqual(parse_effect("Blue"), 0x08)
        self.assertEqual(parse_effect("pArIsIaN bLuE"), 0x08)

    def test_hyphen_and_space_interchangeable(self):
        self.assertEqual(parse_effect("parisian-blue"), 0x08)
        self.assertEqual(parse_effect("parisian blue"), 0x08)
        self.assertEqual(parse_effect("super-nova"), 0x02)
        self.assertEqual(parse_effect("super nova"), 0x02)
        self.assertEqual(parse_effect("northern-lights"), 0x03)

    def test_rejects_unknown(self):
        with self.assertRaises(ValueError):
            parse_effect("magenta")
        with self.assertRaises(ValueError):
            parse_effect("")
        with self.assertRaises(ValueError):
            parse_effect("supernova mega")

    def test_effect_table_exposes_all_15_bytes(self):
        # Safety: if we ever drop or duplicate a byte in the table,
        # this fails. Every byte 0x00..0x0e should have a canonical
        # name.
        seen_bytes = set(EFFECT_TABLE.values())
        for b in range(0x00, 0x0F):
            self.assertIn(b, seen_bytes, f"byte 0x{b:02x} missing")


class ParseRawTests(unittest.TestCase):
    """`parse_raw` accepts hex-byte strings."""

    def test_two_hex_digits(self):
        self.assertEqual(parse_raw("08"), 0x08)
        self.assertEqual(parse_raw("0e"), 0x0E)
        self.assertEqual(parse_raw("FF"), 0xFF)

    def test_0x_prefix(self):
        self.assertEqual(parse_raw("0x08"), 0x08)
        self.assertEqual(parse_raw("0X0e"), 0x0E)
        self.assertEqual(parse_raw("0xff"), 0xFF)

    def test_single_digit(self):
        # Lenient: accept "8" as 0x08.
        self.assertEqual(parse_raw("8"), 0x08)
        self.assertEqual(parse_raw("0x8"), 0x08)

    def test_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            parse_raw("100")  # 0x100 = 256
        with self.assertRaises(ValueError):
            parse_raw("0x100")

    def test_rejects_non_hex(self):
        with self.assertRaises(ValueError):
            parse_raw("gg")
        with self.assertRaises(ValueError):
            parse_raw("0xgg")
        with self.assertRaises(ValueError):
            parse_raw("")
        with self.assertRaises(ValueError):
            parse_raw("  ")

    def test_rejects_negative(self):
        with self.assertRaises(ValueError):
            parse_raw("-1")


if __name__ == "__main__":
    unittest.main()
