"""Cross-verify the ESPHome light platform's show + solid tables.

The custom light platform splits the 12 canonical non-control
effects into two lists:

- ``SOLID_COLORS`` — 5 entries, each carrying (name, byte, RGB).
  Surfaced as color-picker targets (HA's color picker snaps to
  the nearest of these 5 solids).
- ``SHOW_EFFECTS`` — 7 entries, each carrying (name, byte).
  Surfaced as light effects in HA's effect dropdown.

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

# Matches SHOW_EFFECTS entries like:   ("Nova", 0x07),
_SHOW_RE = re.compile(
    r'\(\s*"([^"]+)"\s*,\s*(0x[0-9a-fA-F]+)\s*\)',
)

# Matches SOLID_COLORS entries like:
#   ("Parisian Blue",  0x08, (0x00, 0x00, 0xFF)),
_SOLID_RE = re.compile(
    r'\(\s*"([^"]+)"\s*,\s*(0x[0-9a-fA-F]+)\s*,\s*'
    r'\(\s*0x([0-9a-fA-F]+)\s*,\s*0x([0-9a-fA-F]+)\s*,\s*0x([0-9a-fA-F]+)\s*\)'
    r'\s*\)',
)

EXPECTED_SOLIDS: list[tuple[str, int]] = [
    ("Parisian Blue",      0x08),
    ("Brazilian Red",      0x0A),
    ("Arctic White",       0x0B),
    ("Miami Pink",         0x0C),
    ("New Zealand Green",  0x09),
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

# Bytes that must NOT appear as effects OR as solid color presets —
# they map to other UI surfaces.
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


def _parse_shows(text: str) -> list[tuple[str, int]]:
    block = _section(text, "SHOW_EFFECTS")
    return [(name, int(b, 16)) for name, b in _SHOW_RE.findall(block)]


def _parse_solids(text: str) -> list[tuple[str, int, tuple[int, int, int]]]:
    block = _section(text, "SOLID_COLORS")
    out: list[tuple[str, int, tuple[int, int, int]]] = []
    for name, byte, r, g, b in _SOLID_RE.findall(block):
        out.append((name, int(byte, 16),
                    (int(r, 16), int(g, 16), int(b, 16))))
    return out


class LightPlatformTests(unittest.TestCase):
    """Shape and content of the light platform's two tables."""

    def setUp(self):
        if LIGHT_INIT_PATH.is_file():
            self.text = LIGHT_INIT_PATH.read_text(encoding="utf-8")
            self.solids = _parse_solids(self.text)
            self.shows = _parse_shows(self.text)
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

    def test_solid_colors_match_expected(self):
        self._require()
        got = [(n, b) for n, b, _ in self.solids]
        self.assertEqual(
            sorted(got, key=lambda e: e[1]),
            sorted(EXPECTED_SOLIDS, key=lambda e: e[1]),
            "SOLID_COLORS does not match the canonical 5",
        )

    def test_show_effects_match_expected(self):
        self._require()
        self.assertEqual(
            sorted(self.shows, key=lambda e: e[1]),
            sorted(EXPECTED_SHOWS, key=lambda e: e[1]),
            "SHOW_EFFECTS does not match the canonical 7",
        )

    def test_tables_combined_cover_cli_effects(self):
        """SOLID_COLORS + SHOW_EFFECTS together must equal cli.py
        minus Lock/Return/Standby."""
        self._require()
        combined = {b for _, b, _ in self.solids} | {b for _, b in self.shows}
        expected = set(EFFECT_TABLE.values()) - set(EXCLUDED_BYTES.keys())
        self.assertEqual(
            combined, expected,
            "solids + shows must cover every cli.py effect except "
            "Standby/Lock/Return",
        )

    def test_bytes_agree_with_cli_table(self):
        self._require()
        for name, byte, _rgb in self.solids:
            with self.subTest(solid=name):
                self.assertEqual(EFFECT_TABLE[name.lower()], byte)
        for name, byte in self.shows:
            with self.subTest(show=name):
                self.assertEqual(EFFECT_TABLE[name.lower()], byte)

    def test_excluded_bytes_never_appear(self):
        self._require()
        all_bytes = {b for _, b, _ in self.solids} | {b for _, b in self.shows}
        for byte, reason in EXCLUDED_BYTES.items():
            with self.subTest(byte=f"0x{byte:02x}"):
                self.assertNotIn(
                    byte, all_bytes,
                    f"0x{byte:02x} appeared in light tables — {reason}",
                )

    def test_solids_are_pure_primaries(self):
        """User spec: solids are pure saturated colors, no mixed
        intermediates. Each channel must be 0x00 or 0xFF."""
        self._require()
        for name, _, (r, g, b) in self.solids:
            with self.subTest(solid=name):
                for ch, label in ((r, "R"), (g, "G"), (b, "B")):
                    self.assertIn(
                        ch, (0x00, 0xFF),
                        f"{name}: {label} channel is 0x{ch:02x}, "
                        "must be 0x00 or 0xFF per user-confirmed fixture "
                        "behavior (pure primaries only)",
                    )


class _ParserUnitTests(unittest.TestCase):
    """Spot-check the regex parsers."""

    def test_parses_shows_section(self):
        src = '''
        SHOW_EFFECTS = [
            ("Alpha", 0x01),
            ("Beta",  0x02),
        ]
        '''
        self.assertEqual(
            _parse_shows(src),
            [("Alpha", 0x01), ("Beta", 0x02)],
        )

    def test_parses_solids_section(self):
        src = '''
        SOLID_COLORS = [
            ("Red",   0x0A, (0xFF, 0x00, 0x00)),
            ("White", 0x0B, (0xFF, 0xFF, 0xFF)),
        ]
        '''
        self.assertEqual(
            _parse_solids(src),
            [
                ("Red",   0x0A, (0xFF, 0x00, 0x00)),
                ("White", 0x0B, (0xFF, 0xFF, 0xFF)),
            ],
        )


if __name__ == "__main__":
    unittest.main()
