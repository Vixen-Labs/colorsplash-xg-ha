"""Cross-verify the ESPHome component's effect byte table.

The ESPHome custom component in
``firmware/esphome/components/colorsplash_xg/effect_codec.h`` must
speak the exact same byte codes as the Python reference client
in ``tools/cli.py``. If the two drift apart — e.g. someone adds a
new effect to one and forgets the other — the pool light will stop
responding the way HA expects.

This test parses the C++ header's table and asserts it matches
``tools.cli.EFFECT_TABLE`` byte-for-byte. It also asserts every
byte 0x00..0x0e is accounted for (the complete opcode space from
``docs/PROTOCOL.md`` v1.4 §Effect opcode table).

Run:
    python3 -m unittest discover -s tests
"""

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "tools"))
from cli import EFFECT_TABLE  # noqa: E402

HEADER_PATH = (
    REPO_ROOT
    / "firmware"
    / "esphome"
    / "components"
    / "colorsplash_xg"
    / "effect_codec.h"
)

# Match rows like:   {"parisian blue", 0x08},
# Loose enough to tolerate varying whitespace; strict enough to
# reject comments and non-entry lines.
_ENTRY_RE = re.compile(
    r'\{\s*"([^"]+)"\s*,\s*(0x[0-9a-fA-F]+)\s*\}',
)


def _parse_header_table(header_text: str) -> dict[str, int]:
    """Extract {name: byte} pairs from the C++ header source."""
    pairs: dict[str, int] = {}
    for name, hex_byte in _ENTRY_RE.findall(header_text):
        value = int(hex_byte, 16)
        if name in pairs:
            raise AssertionError(
                f"duplicate effect name {name!r} in {HEADER_PATH.name}"
            )
        pairs[name] = value
    return pairs


class EffectCodecHeaderTests(unittest.TestCase):
    """Shape and content of effect_codec.h's byte table."""

    def setUp(self):
        # Loaded per-test so test_header_exists can fail cleanly when
        # the file is missing without masking the other tests.
        if HEADER_PATH.is_file():
            self.header_text = HEADER_PATH.read_text(encoding="utf-8")
            self.table = _parse_header_table(self.header_text)
        else:
            self.header_text = None
            self.table = None

    def _require_header(self):
        if self.table is None:
            self.fail(
                f"{HEADER_PATH.relative_to(REPO_ROOT)} does not exist — "
                "run the rest of issue #10's work to create it"
            )

    def test_header_exists(self):
        self.assertTrue(
            HEADER_PATH.is_file(),
            f"missing {HEADER_PATH.relative_to(REPO_ROOT)} — "
            "this test is the failing-first guard for that file",
        )

    def test_header_matches_python_reference(self):
        self._require_header()
        """The C++ table must carry the same name→byte mapping as tools/cli.py."""
        for name, expected_byte in EFFECT_TABLE.items():
            with self.subTest(effect=name):
                self.assertIn(
                    name, self.table,
                    f"effect {name!r} missing from effect_codec.h",
                )
                self.assertEqual(
                    self.table[name], expected_byte,
                    f"effect {name!r}: expected 0x{expected_byte:02x}, "
                    f"got 0x{self.table[name]:02x}",
                )

    def test_header_has_no_extra_effects(self):
        """effect_codec.h must not carry effects unknown to cli.py."""
        self._require_header()
        extras = set(self.table) - set(EFFECT_TABLE)
        self.assertFalse(
            extras,
            f"effect_codec.h has effects unknown to tools/cli.py: {sorted(extras)}",
        )

    def test_full_0x00_to_0x0e_coverage(self):
        """Every byte 0x00..0x0e must map to exactly one effect."""
        self._require_header()
        bytes_seen = sorted(self.table.values())
        self.assertEqual(
            bytes_seen,
            list(range(0x00, 0x0F)),
            "effect_codec.h must cover the full 0x00..0x0e opcode space",
        )


class _ParseHeaderUnitTests(unittest.TestCase):
    """Spot-check the regex parser itself."""

    def test_parses_a_minimal_table(self):
        src = """
        constexpr EffectEntry kEffectTable[] = {
            {"alpha", 0x00},
            {"beta",  0x01},
            // a comment that should not parse
            {"gamma", 0x0F},
        };
        """
        self.assertEqual(
            _parse_header_table(src),
            {"alpha": 0x00, "beta": 0x01, "gamma": 0x0F},
        )

    def test_rejects_duplicates(self):
        src = '{"alpha", 0x00}, {"alpha", 0x01}'
        with self.assertRaises(AssertionError):
            _parse_header_table(src)


if __name__ == "__main__":
    unittest.main()
