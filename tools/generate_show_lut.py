#!/usr/bin/env python3
"""Generate a compact C++ header from a calibration JSON
(`tools/show_colors_video.json`) for embedding into the bridge
firmware.

Color-space note: the JSON stores camera-observed RGB values
(what the iPhone Final Cut Camera captured of the fixture). For
the picker to be useful from a Lovelace color wheel, the LUT
entries need to be in canonical sRGB-ish space — when the user
asks for #ff0000 they expect the *Brazilian Red* filter, not
whatever muddy red the camera saw. We anchor the 5 documented
solids to their canonical RGB names and fit a 3×3 color-
correction matrix (least-squares against all 5 anchors) that
maps observed → canonical. The matrix is applied to every show
sample; the solid entries are written with their exact canonical
values so a #ff0000 tap from the card lands as an exact match.

The header exposes:

    namespace esphome { namespace colorsplash_xg {
      struct LutSample {
        uint8_t  start_byte;
        uint16_t wait_ms;
        uint8_t  r, g, b;
      };
      extern const LutSample SHOW_LUT[];
      extern const size_t    SHOW_LUT_LEN;
      struct SolidEntry {
        uint8_t  start_byte;
        uint8_t  r, g, b;
      };
      extern const SolidEntry SOLID_LUT[];
      extern const size_t     SOLID_LUT_LEN;
      extern const uint8_t   AMBIENT_R, AMBIENT_G, AMBIENT_B;
    } }

The picker C++ code does a Euclidean RGB distance search across
both arrays.

Decimation: by default we take one sample every 100 ms, which for
7 shows × 90 s = 6300 samples raw → 630 samples decimated → ~5 KB.
Adjust --interval-ms for a different size/precision tradeoff.

Usage:
    python tools/generate_show_lut.py \\
        --in tools/show_colors_video.json \\
        --out firmware/esphome/components/colorsplash_xg/show_color_lut.h
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


SOLID_BYTES = {
    "Parisian Blue": 0x08,
    "Brazilian Red": 0x0a,
    "Arctic White": 0x0b,
    "Miami Pink": 0x0c,
    "New Zealand Green": 0x09,
}

# Canonical RGB values matching what each filter advertises to
# the user (and what the JS card uses for its solid swatches).
# These are the fixed targets the CCM stretches to.
SOLID_CANONICAL = {
    "Parisian Blue":     (0,   0,   255),
    "Brazilian Red":     (255, 0,   0),
    "Arctic White":      (255, 255, 255),
    "Miami Pink":        (255, 0,   255),
    "New Zealand Green": (0,   255, 0),
}

SHOW_BYTES = {
    "Nova": 0x07,
    "Super Nova": 0x02,
    "Northern Lights": 0x03,
    "Tidal Wave": 0x04,
    "Patriot Dream": 0x05,
    "Desert Skies": 0x06,
    "Peruvian Paradise": 0x01,
}

# Per-show loop period (ms) detected via autocorrelation on the
# linearized sRGB capture. The LUT only retains samples within
# the first loop (post-skip) so a wheel-pick lands a Lock byte at
# the earliest occurrence of the matched color rather than waiting
# through redundant cycles.
#
# Tidal Wave / Patriot Dream / Desert Skies have clean minima in
# the autocorrelation (mean Euclidean RGB distance < 15 at the
# detected period). Nova / Super Nova jump too fast for frame-
# level autocorrelation to lock (sub-second color steps + smooth
# transitions); Northern Lights / Peruvian Paradise capture
# windows didn't include a full cycle. Those shows use the
# DEFAULT_LOOP_MS fallback — generous enough to expose most
# colors, not so long that the user waits forever.
SHOW_LOOP_MS = {
    "Tidal Wave":     32000,
    "Patriot Dream":  12200,
    "Desert Skies":   32000,
}
DEFAULT_LOOP_MS = 30000


def compute_ccm(observed_solids: dict[str, tuple[int, int, int]]
                ) -> tuple[np.ndarray, dict[str, tuple[int, int, int]]]:
    """Solve a 3×3 color-correction matrix M such that
    M @ observed_anchor ≈ canonical_anchor, in least-squares sense
    across all 5 documented solids. Returns (M, residuals).

    Residuals are how the matrix predicts each anchor; useful for
    sanity-checking that the camera response is close enough to
    linear that one matrix can fit all 5. Big residuals on white
    or magenta would suggest the camera has non-linear response
    (HDR / gamma) and a per-channel pre-stage might be needed.
    """
    obs_cols, canon_cols = [], []
    for name, canon in SOLID_CANONICAL.items():
        if name not in observed_solids:
            continue
        obs_cols.append(np.array(observed_solids[name], dtype=float))
        canon_cols.append(np.array(canon, dtype=float))
    if len(obs_cols) < 3:
        raise ValueError(
            "Need observed RGBs for at least 3 anchor solids; got "
            f"{len(obs_cols)}.")
    obs = np.column_stack(obs_cols)        # 3 × N
    canon = np.column_stack(canon_cols)    # 3 × N
    # Least-squares: M = canon @ pinv(obs)
    M = canon @ np.linalg.pinv(obs)
    residuals = {}
    for name in observed_solids:
        if name not in SOLID_CANONICAL:
            continue
        pred = M @ np.array(observed_solids[name], dtype=float)
        residuals[name] = tuple(int(round(x)) for x in pred)
    return M, residuals


def apply_ccm(M: np.ndarray, rgb: tuple[int, int, int]
              ) -> tuple[int, int, int]:
    out = M @ np.array(rgb, dtype=float)
    out = np.clip(out, 0, 255).round().astype(int)
    return (int(out[0]), int(out[1]), int(out[2]))


def decimate(samples: list[dict], interval_ms: int,
             skip_ms: int) -> list[dict]:
    """Return one sample per `interval_ms` window, starting at
    `skip_ms`. Picks the sample whose t_ms is closest to each grid
    point so the kept colors track real fixture state."""
    if not samples:
        return []
    samples_sorted = sorted(samples, key=lambda s: s["t_ms"])
    max_t = samples_sorted[-1]["t_ms"]
    grid = list(range(skip_ms, max_t + 1, interval_ms))
    out = []
    cursor = 0
    for g in grid:
        # advance cursor while next sample is still closer to g
        while (cursor + 1 < len(samples_sorted)
               and abs(samples_sorted[cursor + 1]["t_ms"] - g)
               <= abs(samples_sorted[cursor]["t_ms"] - g)):
            cursor += 1
        out.append(samples_sorted[cursor])
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--in", dest="inp",
                   default="tools/show_colors_video.json", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--interval-ms", type=int, default=100,
                   help="decimation interval (default 100 — one "
                        "sample every 100 ms per show)")
    p.add_argument("--skip-ms", type=int, default=2500,
                   help="exclude samples earlier than this (default "
                        "2500 — covers BLE+dispatch latency)")
    args = p.parse_args()

    data = json.loads(args.inp.read_text())

    # ---- Calibrate: build observed→canonical CCM from solids ----
    observed_solids = {}
    for name, rgb in data.get("solids", {}).items():
        if name in SOLID_CANONICAL:
            observed_solids[name] = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    M, residuals = compute_ccm(observed_solids)
    # Print the calibration so the user can sanity-check before
    # the firmware flash.
    print(">>> CCM (least-squares fit, observed → canonical):")
    for row in M:
        print(f"      [{row[0]:7.4f}  {row[1]:7.4f}  {row[2]:7.4f}]")
    print(">>> Anchor residuals after CCM:")
    for name, canon in SOLID_CANONICAL.items():
        if name not in residuals:
            continue
        pred = residuals[name]
        err = max(abs(pred[i] - canon[i]) for i in range(3))
        print(f"      {name:22s}: pred={pred}  target={canon}  "
              f"max_err={err}")

    # ---- Show samples (decimated, clipped to first loop, then
    # CCM-stretched) ----
    show_entries: list[tuple[int, int, int, int, int]] = []
    show_summary: list[tuple[str, int, int]] = []  # (name, kept, loop_ms)
    for show_name, samples in data.get("shows", {}).items():
        base = show_name.split(" #")[0]
        if base not in SHOW_BYTES:
            continue
        byte = SHOW_BYTES[base]
        decimated = decimate(samples, args.interval_ms, args.skip_ms)
        # Clip to the first loop iteration so the picker can never
        # match a sample beyond t = skip_ms + loop_ms — keeps the
        # user's max wait bounded by the loop length, not the 90 s
        # capture window.
        loop_ms = SHOW_LOOP_MS.get(base, DEFAULT_LOOP_MS)
        loop_cutoff = args.skip_ms + loop_ms
        clipped = [s for s in decimated if s["t_ms"] <= loop_cutoff]
        show_summary.append((base, len(clipped), loop_ms))
        for s in clipped:
            obs_rgb = (int(s["rgb"][0]), int(s["rgb"][1]),
                       int(s["rgb"][2]))
            r, g, b = apply_ccm(M, obs_rgb)
            show_entries.append(
                (byte, int(s["t_ms"]), r, g, b))

    # ---- Solids: write the CANONICAL values, not the observed
    # camera values. Solids are by definition the fixed-RGB
    # targets the CCM was fit to, so storing them as canonical
    # makes a #ff0000 tap from the card land as an exact distance-0
    # match (combined with the picker's solid_preference bias).
    solid_entries: list[tuple[int, int, int, int]] = []
    for name, canon in SOLID_CANONICAL.items():
        if name not in SOLID_BYTES:
            continue
        r, g, b = canon
        solid_entries.append((SOLID_BYTES[name], r, g, b))

    # ---- Ambient (apply CCM too so unreachable-floor stays in
    # the same color space as the show samples). ----
    ambient_obs = data.get("ambient_rgb") or [0, 0, 0]
    ar, ag, ab = apply_ccm(M, (int(ambient_obs[0]),
                                int(ambient_obs[1]),
                                int(ambient_obs[2])))

    # ---- Header text ----
    lines = []
    lines.append("// Auto-generated by tools/generate_show_lut.py")
    lines.append(f"// Source: {args.inp}")
    lines.append(f"// Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"// Decimation: 1 sample per {args.interval_ms} ms, "
                 f"skip first {args.skip_ms} ms.")
    lines.append("//")
    lines.append("// Calibration: 3x3 CCM fit observed→canonical via "
                 "least-squares")
    lines.append("// over the 5 documented solids. Show samples are "
                 "stretched by")
    lines.append("// the matrix; solid entries are the exact canonical "
                 "values.")
    lines.append("// CCM (rows):")
    for row in M:
        lines.append(f"//   [{row[0]:7.4f}  {row[1]:7.4f}  {row[2]:7.4f}]")
    lines.append("// Anchor residuals (pred → target):")
    for name, canon in SOLID_CANONICAL.items():
        if name not in residuals:
            continue
        pred = residuals[name]
        lines.append(f"//   {name:22s}: pred={pred}  target={canon}")
    lines.append("//")
    lines.append("// DO NOT EDIT — regenerate with:")
    lines.append(f"//   python tools/generate_show_lut.py --in {args.inp} "
                 f"--out {args.out}")
    lines.append("")
    lines.append("#pragma once")
    lines.append("")
    lines.append("#include <cstdint>")
    lines.append("#include <cstddef>")
    lines.append("")
    lines.append("namespace esphome {")
    lines.append("namespace colorsplash_xg {")
    lines.append("")
    lines.append("struct LutSample {")
    lines.append("  uint8_t  start_byte;")
    lines.append("  uint32_t wait_ms;  // up to 90s — uint16 overflows")
    lines.append("  uint8_t  r, g, b;")
    lines.append("};")
    lines.append("")
    lines.append("struct SolidEntry {")
    lines.append("  uint8_t  start_byte;")
    lines.append("  uint8_t  r, g, b;")
    lines.append("};")
    lines.append("")

    lines.append(f"// Per-show samples — {len(show_entries)} entries:")
    for name, n, loop_ms in show_summary:
        lines.append(f"//   {name:22s}: {n:4d} samples  "
                     f"(loop = {loop_ms} ms)")
    lines.append("constexpr LutSample SHOW_LUT[] = {")
    for byte, t, r, g, b in show_entries:
        lines.append(f"  {{0x{byte:02x}, {t:6d}, {r:3d}, {g:3d}, {b:3d}}},")
    lines.append("};")
    lines.append(f"constexpr size_t SHOW_LUT_LEN = "
                 f"sizeof(SHOW_LUT) / sizeof(SHOW_LUT[0]);")
    lines.append("")

    lines.append(f"// Solids — {len(solid_entries)} entries (one per "
                 "documented solid preset):")
    lines.append("constexpr SolidEntry SOLID_LUT[] = {")
    for byte, r, g, b in solid_entries:
        lines.append(f"  {{0x{byte:02x}, {r:3d}, {g:3d}, {b:3d}}},")
    lines.append("};")
    lines.append(f"constexpr size_t SOLID_LUT_LEN = "
                 f"sizeof(SOLID_LUT) / sizeof(SOLID_LUT[0]);")
    lines.append("")

    lines.append("// Ambient (Standby) baseline — the camera reading "
                 "with the fixture off.")
    lines.append("// Used by the picker as a 'this color is "
                 "unreachable' floor.")
    lines.append(f"constexpr uint8_t AMBIENT_R = {ar};")
    lines.append(f"constexpr uint8_t AMBIENT_G = {ag};")
    lines.append(f"constexpr uint8_t AMBIENT_B = {ab};")
    lines.append("")
    lines.append("}  // namespace colorsplash_xg")
    lines.append("}  // namespace esphome")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n")
    sz = args.out.stat().st_size
    print(f">>> wrote {args.out} ({sz} bytes, "
          f"{len(show_entries)} show samples + "
          f"{len(solid_entries)} solids)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
