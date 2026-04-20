"""Cross-verify the ESPHome light platform's preset effect list.

The custom light platform registers one HA effect per named effect
the fixture supports. That list must equal the 12 canonical
non-control effects in ``tools/cli.py`` (5 solid colors + 7 shows),
and must NOT include Lock (``0x0d``), Return (``0x0e``), or Standby
(``0x00``) — those are either on/off semantics or separate button
entities.

If this test fails, HA will surface the wrong effect set. If it
silently drifts, the pool light will misbehave on rename/reorder.

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

LIGHT_INIT_PATH = (
    REPO_ROOT
    / "firmware"
    / "esphome"
    / "components"
    / "colorsplash_xg"
    / "light"
    / "__init__.py"
)

# Matches rows like:   ("Parisian Blue", 0x08),
# Lenient on whitespace; ignores lines that don't fit the literal
# tuple shape (comments, other statements).
_ENTRY_RE = re.compile(
    r'\(\s*"([^"]+)"\s*,\s*(0x[0-9a-fA-F]+)\s*\)',
)

# Canonical HA-facing effect names. Drawn from docs/PROTOCOL.md
# §Effect opcode table and verified against tools/cli.py. These
# must appear in the light platform's preset list, capitalized as
# shown (title case — that's what HA displays).
EXPECTED_PRESETS: list[tuple[str, int]] = [
    # Solids
    ("Parisian Blue",      0x08),
    ("Brazilian Red",      0x0A),
    ("Arctic White",       0x0B),
    ("Miami Pink",         0x0C),
    ("New Zealand Green",  0x09),
    # Shows
    ("Nova",               0x07),
    ("Super Nova",         0x02),
    ("Northern Lights",    0x03),
    ("Tidal Wave",         0x04),
    ("Patriot Dream",      0x05),
    ("Desert Skies",       0x06),
    ("Peruvian Paradise",  0x01),
]

# Bytes that must NOT appear as effects in the light entity — they
# map to other UI surfaces.
EXCLUDED_BYTES: dict[int, str] = {
    0x00: "Standby (on/off semantics, not effect)",
    0x0D: "Lock (exposed as button entity)",
    0x0E: "Return (exposed as button entity)",
}


def _parse_presets(text: str) -> list[tuple[str, int]]:
    """Extract (name, byte) tuples from the platform's __init__.py."""
    entries: list[tuple[str, int]] = []
    for name, hex_byte in _ENTRY_RE.findall(text):
        entries.append((name, int(hex_byte, 16)))
    return entries


class LightPresetTests(unittest.TestCase):
    """Shape and content of the light platform's preset effect list."""

    def setUp(self):
        if LIGHT_INIT_PATH.is_file():
            self.text = LIGHT_INIT_PATH.read_text(encoding="utf-8")
            self.presets = _parse_presets(self.text)
        else:
            self.text = None
            self.presets = None

    def _require(self):
        if self.presets is None:
            self.fail(
                f"{LIGHT_INIT_PATH.relative_to(REPO_ROOT)} does not exist — "
                "run the rest of issue #11's work to create it"
            )

    def test_file_exists(self):
        self.assertTrue(
            LIGHT_INIT_PATH.is_file(),
            f"missing {LIGHT_INIT_PATH.relative_to(REPO_ROOT)}",
        )

    def test_preset_list_matches_canonical(self):
        self._require()
        self.assertEqual(
            sorted(self.presets, key=lambda e: e[1]),
            sorted(EXPECTED_PRESETS, key=lambda e: e[1]),
            "light platform's preset list does not match the canonical 12",
        )

    def test_preset_bytes_match_cli_table(self):
        """Every preset's byte must agree with tools/cli.py's EFFECT_TABLE."""
        self._require()
        for name, byte in self.presets:
            canonical = name.strip().lower()
            with self.subTest(effect=name):
                self.assertIn(
                    canonical, EFFECT_TABLE,
                    f"light exposes {name!r} but cli.py has no such effect",
                )
                self.assertEqual(
                    EFFECT_TABLE[canonical], byte,
                    f"{name}: expected 0x{EFFECT_TABLE[canonical]:02x}, "
                    f"got 0x{byte:02x}",
                )

    def test_lock_return_standby_not_in_effects(self):
        """Lock/Return live as buttons; Standby is on/off. Not effects."""
        self._require()
        preset_bytes = {byte for _, byte in self.presets}
        for byte, reason in EXCLUDED_BYTES.items():
            with self.subTest(byte=f"0x{byte:02x}"):
                self.assertNotIn(
                    byte, preset_bytes,
                    f"0x{byte:02x} must not appear as an effect — {reason}",
                )

    def test_exactly_twelve_presets(self):
        self._require()
        self.assertEqual(
            len(self.presets), 12,
            f"expected 12 preset effects, found {len(self.presets)}",
        )


class _ParserUnitTests(unittest.TestCase):
    """Spot-check the regex parser."""

    def test_parses_simple_list(self):
        src = '''
        PRESET_EFFECTS = [
            ("Alpha", 0x01),
            ("Beta",  0x02),
        ]
        '''
        self.assertEqual(
            _parse_presets(src),
            [("Alpha", 0x01), ("Beta", 0x02)],
        )


if __name__ == "__main__":
    unittest.main()
