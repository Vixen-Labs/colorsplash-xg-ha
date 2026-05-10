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
    "Nova":              60000,  # detect_loop_periods.py on v5: score 4.9
    "Super Nova":        25000,  # detect_loop_periods.py on v5: score 6.5
    "Tidal Wave":        32000,  # detect_loop_periods.py on v5: score 3.5
    "Patriot Dream":     12200,  # autocorr picked 24400 (2× harmonic);
                                 # 12200 alternate (score 7.1) is the
                                 # true fundamental — keep it for picker
                                 # responsiveness
    "Desert Skies":      31700,  # detect_loop_periods.py on v5: score 4.0
    "Peruvian Paradise": 47900,  # detect_loop_periods.py on v5: score 3.8
                                 # (replaces 30000 DEFAULT fallback)
    # Northern Lights has no clean autocorrelation cycle (aurora-like
    # chaotic colors); detector lands at search-min boundary every
    # time. Use PR #60's manually-determined 5200 ms perceptual
    # sub-cycle below in CARD_SHOW_LOOP_MS instead.
}
DEFAULT_LOOP_MS = 30000

# Card-side loop periods used by the timeline visualization.
# Mostly mirrors SHOW_LOOP_MS, but a few values were re-measured
# from the un-clipped 90 s capture by checking which period gives
# the cleanest cycle closure (sample at activeStart matches
# sample at activeStart + period). Northern Lights turned out to
# have a fast ~5 s sub-cycle that the autocorrelation missed
# during the original analysis; Tidal Wave's exact period is
# slightly longer than the firmware's 32 s clip.
#
# These don't change the firmware picker's behavior — the
# firmware uses SHOW_LOOP_MS above for its LUT clipping. They
# only control the card's timeline strip width and click-mapping
# range.
CARD_SHOW_LOOP_MS = {
    "Nova":              60000,  # detect_loop_periods.py on v5: score 4.9
    "Tidal Wave":        32000,  # detect_loop_periods.py on v5: score 3.5
    "Patriot Dream":     12200,  # documented; 24400 detected as 2× harmonic
    "Desert Skies":      31700,  # detect_loop_periods.py on v5: score 4.0
    "Northern Lights":  120000,  # aurora-chaotic; no autocorr cycle, but
                                 # actual color phases run 10-30 s each
                                 # (blue→red→purple→green sweeps over
                                 # ~120 s). PR #60's 5200 ms hypothesis
                                 # only showed the post-blackout blue
                                 # phase. 120 s window shows the show's
                                 # full color range in the card strip.
    "Peruvian Paradise": 47900,  # detect_loop_periods.py on v5: score 3.8
    "Super Nova":        25000,  # detect_loop_periods.py on v5: score 6.5
}

# Shows whose color sequence is discrete (no blending) and whose
# hold durations are long enough to step-detect cleanly. For these,
# the LUT stores one entry per color hold, with t_ms placed at the
# midpoint of the hold so the Lock byte fires when the fixture is
# squarely on the target color (not during a transition).
#
# Verified deterministic via the 3-replay test in
# show_colors_replay_Nova.json: same 16-color sequence on every
# start, mean cross-run RGB drift only 1-2 (camera noise level).
DISCRETE_STEP_SHOWS = {"Nova"}

# Shows excluded from the LUT entirely. Super Nova is dropped
# because it visits the SAME color set as Nova (palette Jaccard
# 0.45, top-10 colors identical percentages, sequence first-16
# matches segment-for-segment) but with ~5.36× faster holds. For
# wheel-pick → Lock targeting, Nova's slower 1966 ms holds give
# the Lock byte a much wider window to land on the intended color.
# The "Super Nova" effect stays in HA's effect dropdown — only
# its color samples are removed from the picker's matching pool.
LUT_EXCLUDE_SHOWS = {"Super Nova"}


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


def detect_color_holds(samples: list[dict], skip_ms: int,
                       jump_threshold: float = 40.0,
                       min_segment_frames: int = 3
                       ) -> list[dict]:
    """Find frames where RGB jumps by more than `jump_threshold`,
    cluster contiguous frames into "color holds", and return one
    entry per hold:

        [{t_mid_ms, t_start_ms, t_end_ms, r, g, b}, ...]

    `t_mid_ms` is the midpoint of the hold — the LUT places its
    sample there so the Lock byte fires when the fixture is
    squarely on the held color rather than during a transition.

    Used only for shows in DISCRETE_STEP_SHOWS where the color
    sequence is verified to be a clean step pattern (no blending).
    """
    sorted_s = [s for s in sorted(samples, key=lambda s: s["t_ms"])
                if s["t_ms"] >= skip_ms]
    if len(sorted_s) < 10:
        return []
    times = [s["t_ms"] for s in sorted_s]
    rgbs = np.array([s["rgb"] for s in sorted_s], dtype=float)
    diffs = np.linalg.norm(np.diff(rgbs, axis=0), axis=1)
    step_idx = ([0]
                + [i + 1 for i, d in enumerate(diffs) if d > jump_threshold]
                + [len(rgbs)])
    holds = []
    for a, b in zip(step_idx[:-1], step_idx[1:]):
        if b - a < min_segment_frames:
            # Skip transient transition segments (controller blackout
            # between colors registers as a brief dark micro-segment).
            continue
        seg_rgb = rgbs[a:b].mean(axis=0)
        t_start = times[a]
        t_end = times[b - 1]
        holds.append({
            "t_start_ms": t_start,
            "t_end_ms":   t_end,
            "t_mid_ms":   (t_start + t_end) // 2,
            "r": int(round(seg_rgb[0])),
            "g": int(round(seg_rgb[1])),
            "b": int(round(seg_rgb[2])),
        })
    return holds


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
    p.add_argument("--card-out", type=Path, default=None,
                   help="optional: also rewrite the SHOW_LUT_DATA "
                        "block in dashboard/colorsplash-xg-card.js "
                        "between the auto-gen marker comments so "
                        "the JS card has the same data the firmware "
                        "uses for the timeline visualization (#56)")
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

    # ---- Show samples ----
    # Two extraction modes:
    #   (a) Discrete-step shows (Nova): one entry per detected color
    #       hold, t_ms placed at the hold's midpoint so Lock fires
    #       cleanly inside the steady color, not during a transition.
    #   (b) Smooth-gradient shows (Tidal Wave, Desert Skies, etc.):
    #       100 ms decimated samples, clipped to one loop length.
    # Shows in LUT_EXCLUDE_SHOWS are skipped entirely (the named
    # effect still works in HA — only the picker's matching pool
    # excludes them).
    #
    # Two output streams:
    # - show_entries: loop-clipped, written to firmware.h. Keeps
    #   the picker's max wait bounded by one loop period.
    # - show_entries_full: un-clipped, written to the card.js.
    #   The card's timeline visualization needs a clean loop
    #   window (which can fall in loop iteration 1, 2, or 3
    #   depending on where first-lit lands), so it benefits from
    #   the full ~90 s capture per show.
    show_entries: list[tuple[int, int, int, int, int]] = []
    show_entries_full: list[tuple[int, int, int, int, int]] = []
    show_summary: list[tuple[str, int, int, str]] = []
    for show_name, samples in data.get("shows", {}).items():
        base = show_name.split(" #")[0]
        if base not in SHOW_BYTES:
            continue
        if base in LUT_EXCLUDE_SHOWS:
            show_summary.append((base, 0, 0, "excluded"))
            continue
        byte = SHOW_BYTES[base]
        loop_ms = SHOW_LOOP_MS.get(base, DEFAULT_LOOP_MS)

        if base in DISCRETE_STEP_SHOWS:
            holds = detect_color_holds(samples, args.skip_ms)
            # Firmware stream: trim to one loop's worth of holds.
            kept_holds = [h for h in holds
                          if h["t_mid_ms"] <= args.skip_ms + loop_ms]
            for h in kept_holds:
                obs_rgb = (h["r"], h["g"], h["b"])
                r, g, b = apply_ccm(M, obs_rgb)
                show_entries.append(
                    (byte, int(h["t_mid_ms"]), r, g, b))
            # Card stream: all detected holds across the full
            # 90 s capture (multiple loop iterations included).
            for h in holds:
                obs_rgb = (h["r"], h["g"], h["b"])
                r, g, b = apply_ccm(M, obs_rgb)
                show_entries_full.append(
                    (byte, int(h["t_mid_ms"]), r, g, b))
            show_summary.append(
                (base, len(kept_holds), loop_ms, "step"))
        else:
            decimated = decimate(samples, args.interval_ms,
                                 args.skip_ms)
            # Firmware stream: clip to one loop.
            loop_cutoff = args.skip_ms + loop_ms
            clipped = [s for s in decimated if s["t_ms"] <= loop_cutoff]
            for s in clipped:
                obs_rgb = (int(s["rgb"][0]), int(s["rgb"][1]),
                           int(s["rgb"][2]))
                r, g, b = apply_ccm(M, obs_rgb)
                show_entries.append(
                    (byte, int(s["t_ms"]), r, g, b))
            # Card stream: full decimated capture.
            for s in decimated:
                obs_rgb = (int(s["rgb"][0]), int(s["rgb"][1]),
                           int(s["rgb"][2]))
                r, g, b = apply_ccm(M, obs_rgb)
                show_entries_full.append(
                    (byte, int(s["t_ms"]), r, g, b))
            show_summary.append(
                (base, len(clipped), loop_ms, "decimated"))

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
    for name, n, loop_ms, mode in show_summary:
        if mode == "excluded":
            lines.append(f"//   {name:22s}: 0 samples       "
                         f"(excluded — see LUT_EXCLUDE_SHOWS)")
        else:
            lines.append(f"//   {name:22s}: {n:4d} samples  "
                         f"(loop = {loop_ms} ms, mode = {mode})")
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

    if args.card_out is not None:
        update_card_data_block(
            card_path=args.card_out,
            show_entries=show_entries_full,
            show_summary=show_summary,
            ambient_rgb=(ar, ag, ab),
        )

    return 0


def update_card_data_block(card_path: Path,
                           show_entries: list,
                           show_summary: list,
                           ambient_rgb: tuple) -> None:
    """Rewrite the SHOW_LUT_DATA block inside the JS card file
    between the auto-gen marker comments. Single Lovelace
    resource, no extra registration needed by the user."""
    if not card_path.exists():
        print(f">>> WARN: --card-out {card_path} not found; "
              "skipping card-side data write.")
        return
    src = card_path.read_text()
    begin_marker = "// === SHOW_LUT_DATA BEGIN (auto-generated by tools/generate_show_lut.py) ==="
    end_marker = "// === SHOW_LUT_DATA END ==="
    if begin_marker not in src or end_marker not in src:
        print(f">>> WARN: marker comments not found in "
              f"{card_path} — add the begin/end markers to enable "
              "card-side data injection.")
        return

    # Build the JS block. Compact array-of-arrays per row keeps
    # the bundle small (~30 KB at current sample count).
    lines = [begin_marker,
             "// Auto-generated by tools/generate_show_lut.py — do not edit by hand.",
             "// Each row: [start_byte, t_ms, r, g, b]. start_byte identifies",
             "// the show; t_ms is the sample's offset from the show's send byte.",
             "const SHOW_LUT_DATA = ["]
    for byte, t, r, g, b in show_entries:
        lines.append(f"  [{byte},{t},{r},{g},{b}],")
    lines.append("];")
    lines.append("")
    lines.append("// Per-show loop period in ms — drives the timeline ")
    lines.append("// strip's right edge so the cycle closes back on its")
    lines.append("// starting color. Sourced from CARD_SHOW_LOOP_MS")
    lines.append("// (refined from the un-clipped capture), falling back")
    lines.append("// to the firmware's SHOW_LOOP_MS / DEFAULT_LOOP_MS.")
    lines.append("const SHOW_LOOPS_MS = {")
    for name, _n, _loop_ms, _mode in show_summary:
        byte = SHOW_BYTES.get(name)
        if byte is None:
            continue
        card_loop = CARD_SHOW_LOOP_MS.get(name,
                       SHOW_LOOP_MS.get(name, DEFAULT_LOOP_MS))
        lines.append(f"  {byte}: {card_loop},  // {name}")
    lines.append("};")
    lines.append(end_marker)

    new_block = "\n".join(lines)
    pre, _, after_begin = src.partition(begin_marker)
    _, _, post = after_begin.partition(end_marker)
    rewritten = pre + new_block + post
    card_path.write_text(rewritten)
    print(f">>> updated SHOW_LUT_DATA block in {card_path} "
          f"({len(show_entries)} samples, "
          f"{rewritten.encode('utf-8').__len__()} bytes total)")


if __name__ == "__main__":
    sys.exit(main())
