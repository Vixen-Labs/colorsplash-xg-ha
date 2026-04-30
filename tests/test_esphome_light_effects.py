"""Cross-verify the ESPHome light platform's effect tables.

The custom light platform exposes all 12 selectable hardware
states as effects, split into two lists for documentation:

- ``SOLID_EFFECTS`` — 5 entries, (name, byte) for the solid colors.
- ``SHOW_EFFECTS`` — 7 entries, (name, byte) for the show animations.

Together they must equal the 12 canonical effects in
``tools/cli.py`` — no more, no fewer. Lock (0x0D), Return (0x0E),
and Standby (0x00) are deliberately excluded; they map to button
entities or on/off semantics.

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

# Matches (name, byte) entries like:   ("Nova", 0x07),
_ENTRY_RE = re.compile(
    r'\(\s*"([^"]+)"\s*,\s*(0x[0-9a-fA-F]+)\s*\)',
)

EXPECTED_SOLIDS: list[tuple[str, int]] = [
    ("Arctic White",       0x0B),
    ("Brazilian Red",      0x0A),
    ("New Zealand Green",  0x09),
    ("Parisian Blue",      0x08),
    ("Miami Pink",         0x0C),
]

EXPECTED_SHOWS: list[tuple[str, int]] = [
    ("Nova",               0x07),
    ("Super Nova",         0x02),
    ("Northern Lights",    0x03),
    ("Tidal Wave",         0x04),
    ("Patriot Dream",      0x05),
    ("Desert Skies",       0x06),
    ("Peruvian Paradise",  0x01),
]

# Bytes that must NOT appear as effects — they map to other UI
# surfaces.
EXCLUDED_BYTES: dict[int, str] = {
    0x00: "Standby (on/off semantics)",
    0x0D: "Lock (exposed as button entity)",
    0x0E: "Return (exposed as button entity)",
}


def _section(text: str, var_name: str) -> str:
    """Extract the text of ``VAR_NAME [: ...] = [ ... ]`` from a module.

    Matches both the bare ``NAME = [`` and annotated
    ``NAME: list[...] = [`` forms, returning the bracketed block.
    """
    m = re.search(
        rf'{var_name}\s*(?::\s*[^=]*)?=\s*\[',
        text,
    )
    if not m:
        return ""
    i = m.end()
    depth = 1
    while i < len(text) and depth > 0:
        if text[i] == '[':
            depth += 1
        elif text[i] == ']':
            depth -= 1
        i += 1
    return text[m.end() - 1:i]


def _parse_entries(text: str, var_name: str) -> list[tuple[str, int]]:
    block = _section(text, var_name)
    return [(name, int(b, 16)) for name, b in _ENTRY_RE.findall(block)]


class LightPlatformTests(unittest.TestCase):
    """Shape and content of the light platform's effect tables."""

    def setUp(self):
        if LIGHT_INIT_PATH.is_file():
            self.text = LIGHT_INIT_PATH.read_text(encoding="utf-8")
            self.solids = _parse_entries(self.text, "SOLID_EFFECTS")
            self.shows = _parse_entries(self.text, "SHOW_EFFECTS")
        else:
            self.text = None
            self.solids = None
            self.shows = None

    def _require(self):
        if self.text is None:
            self.fail(
                f"{LIGHT_INIT_PATH.relative_to(REPO_ROOT)} does not exist — "
                "run the rest of issue #11's work to create it"
            )

    def test_file_exists(self):
        self.assertTrue(
            LIGHT_INIT_PATH.is_file(),
            f"missing {LIGHT_INIT_PATH.relative_to(REPO_ROOT)}",
        )

    def test_solid_effects_match_expected(self):
        self._require()
        self.assertEqual(
            sorted(self.solids, key=lambda e: e[1]),
            sorted(EXPECTED_SOLIDS, key=lambda e: e[1]),
            "SOLID_EFFECTS does not match the canonical 5",
        )

    def test_show_effects_match_expected(self):
        self._require()
        self.assertEqual(
            sorted(self.shows, key=lambda e: e[1]),
            sorted(EXPECTED_SHOWS, key=lambda e: e[1]),
            "SHOW_EFFECTS does not match the canonical 7",
        )

    def test_tables_combined_cover_cli_effects(self):
        """SOLID_EFFECTS + SHOW_EFFECTS together must equal cli.py
        minus Lock/Return/Standby."""
        self._require()
        combined = {b for _, b in self.solids} | {b for _, b in self.shows}
        expected = set(EFFECT_TABLE.values()) - set(EXCLUDED_BYTES.keys())
        self.assertEqual(
            combined, expected,
            "solids + shows must cover every cli.py effect except "
            "Standby/Lock/Return",
        )

    def test_bytes_agree_with_cli_table(self):
        self._require()
        for name, byte in self.solids:
            with self.subTest(solid=name):
                self.assertEqual(EFFECT_TABLE[name.lower()], byte)
        for name, byte in self.shows:
            with self.subTest(show=name):
                self.assertEqual(EFFECT_TABLE[name.lower()], byte)

    def test_excluded_bytes_never_appear(self):
        self._require()
        all_bytes = {b for _, b in self.solids} | {b for _, b in self.shows}
        for byte, reason in EXCLUDED_BYTES.items():
            with self.subTest(byte=f"0x{byte:02x}"):
                self.assertNotIn(
                    byte, all_bytes,
                    f"0x{byte:02x} appeared in light tables — {reason}",
                )


class _ParserUnitTests(unittest.TestCase):
    """Spot-check the regex parser."""

    def test_parses_named_section(self):
        src = '''
        SOLID_EFFECTS = [
            ("Alpha", 0x01),
            ("Beta",  0x02),
        ]
        '''
        self.assertEqual(
            _parse_entries(src, "SOLID_EFFECTS"),
            [("Alpha", 0x01), ("Beta", 0x02)],
        )


if __name__ == "__main__":
    unittest.main()
