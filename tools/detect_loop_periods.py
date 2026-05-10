#!/usr/bin/env python3
"""Detect each show's loop period from a calibration JSON via
RGB-space autocorrelation.

For every candidate period P in a search range, we compute the
mean Euclidean RGB distance between the sample at time t and the
sample at time t+P over all samples where both fall inside the
captured window. The period with the lowest mean distance is the
detected loop.

The detector reads timestamps directly from each sample's `t_ms`
(no uniform-frame-rate assumption — works for 24 fps, 30 fps,
duplicate frames, dropped frames, etc.).

A run also reports cycle-closure deltas at the detected period,
so we can verify GH issue #55's "delta < 30 per channel" criterion.

Usage:
    python tools/detect_loop_periods.py \\
        --in tools/show_colors_floor_v4.json \\
        [--skip-ms 2500] [--search-min-ms 2000] [--search-max-ms 120000] \\
        [--step-ms 100]

Output: a table per show with detected period, min score, top-3
local minima (so a near-miss alternative is visible), and the
cycle-closure RGB delta. Suggested SHOW_LOOP_MS / CARD_SHOW_LOOP_MS
overrides are printed at the end in copy-pasteable form.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def detect_loop_period(
    samples: list[dict],
    skip_ms: int = 2500,
    search_min_ms: int = 2000,
    search_max_ms: int = 120000,
    step_ms: int = 100,
    min_overlap_samples: int = 100,
) -> tuple[int | None, float | None, list[tuple[int, float]]]:
    """Return (best_period_ms, best_score, all_scores).

    `all_scores` is a list of (period_ms, score) for every candidate
    in the search range — useful for plotting or finding alternative
    minima near the global one. `best_score` is the mean per-pixel
    Euclidean RGB distance at the detected period; values below ~30
    indicate a clean cycle (issue #55 criterion).
    """
    # Filter out the leading dark/transition frames.
    kept = [s for s in samples if s["t_ms"] >= skip_ms]
    if len(kept) < 50:
        return None, None, []

    times = np.array([s["t_ms"] for s in kept], dtype=np.int64)
    rgbs = np.array([s["rgb"] for s in kept], dtype=np.float32)

    t_max = int(times[-1])
    scores: list[tuple[int, float]] = []

    for period in range(search_min_ms, min(search_max_ms, t_max - skip_ms) + 1,
                        step_ms):
        # For each sample at time t, look up the sample at time
        # t+period via linear interpolation (gracefully handles
        # variable sample spacing). Restrict to samples where
        # t+period stays inside the captured window.
        t_query = times + period
        valid_mask = t_query <= t_max
        if int(valid_mask.sum()) < min_overlap_samples:
            continue
        rgb_at_t = rgbs[valid_mask]
        t_q = t_query[valid_mask]
        # Per-channel linear interp
        rgb_at_t_plus = np.column_stack([
            np.interp(t_q, times, rgbs[:, c]) for c in range(3)
        ])
        dist = np.linalg.norm(rgb_at_t - rgb_at_t_plus, axis=1).mean()
        scores.append((period, float(dist)))

    if not scores:
        return None, None, []
    best = min(scores, key=lambda x: x[1])
    return best[0], best[1], scores


def cycle_closure_delta(samples: list[dict], period_ms: int,
                        skip_ms: int = 2500) -> tuple[int, int, int] | None:
    """Per-channel max |Δ| between sample at t and sample at t+period,
    averaged over the first cycle. Issue #55 wants this < 30 per
    channel to call the cycle 'clean'."""
    kept = [s for s in samples if s["t_ms"] >= skip_ms]
    if len(kept) < 50:
        return None
    times = np.array([s["t_ms"] for s in kept], dtype=np.int64)
    rgbs = np.array([s["rgb"] for s in kept], dtype=np.float32)
    t_max = int(times[-1])

    t_query = times + period_ms
    valid = t_query <= t_max
    if int(valid.sum()) < 50:
        return None
    rgb_at_t = rgbs[valid]
    t_q = t_query[valid]
    rgb_at_t_plus = np.column_stack([
        np.interp(t_q, times, rgbs[:, c]) for c in range(3)
    ])
    abs_diff = np.abs(rgb_at_t - rgb_at_t_plus)
    # Per-channel mean of the absolute deltas
    return tuple(int(round(x)) for x in abs_diff.mean(axis=0))


def find_local_minima(scores: list[tuple[int, float]],
                      n: int = 3) -> list[tuple[int, float]]:
    """Return up to N local minima sorted by score (lowest first).
    A local minimum is a (period, score) where the neighbours on
    either side have higher scores. Useful for spotting harmonics
    and near-miss alternatives."""
    if len(scores) < 3:
        return scores[:n]
    minima = []
    for i in range(1, len(scores) - 1):
        if scores[i][1] < scores[i - 1][1] and scores[i][1] < scores[i + 1][1]:
            minima.append(scores[i])
    minima.sort(key=lambda x: x[1])
    return minima[:n]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--in", dest="inp", type=Path, required=True,
                   help="calibration JSON (output of "
                        "calibrate_show_colors.py)")
    p.add_argument("--skip-ms", type=int, default=2500,
                   help="exclude leading samples; default 2500 covers "
                        "the BLE+dispatch latency + post-byte blackout")
    p.add_argument("--search-min-ms", type=int, default=2000,
                   help="candidate period range lower bound (default 2000 — "
                        "below 2 s is below perceptual cycle floor and "
                        "tends to land on PWM artifacts. Lower if "
                        "diagnosing a known fast cycle.)")
    p.add_argument("--search-max-ms", type=int, default=120000,
                   help="candidate period range upper bound")
    p.add_argument("--step-ms", type=int, default=100,
                   help="step between candidate periods")
    p.add_argument("--clean-threshold", type=int, default=30,
                   help="report a show as 'clean' if min score < this")
    args = p.parse_args()

    if not args.inp.is_file():
        print(f"error: {args.inp} not found", file=sys.stderr)
        return 1

    data = json.loads(args.inp.read_text())
    shows = data.get("shows", {})
    if not shows:
        print("error: no 'shows' key in JSON", file=sys.stderr)
        return 1

    print(f">>> Loop-period detection on {args.inp}")
    print(f"    skip_ms={args.skip_ms}, search "
          f"{args.search_min_ms}-{args.search_max_ms} ms "
          f"step {args.step_ms}, clean<{args.clean_threshold}\n")

    print(f"{'show':22s} {'period':>10s} {'score':>8s} {'closure ΔRGB':>16s}  "
          f"{'verdict':10s}  alternates")
    print("-" * 110)

    suggestions: dict[str, int] = {}
    for name, samples in shows.items():
        period, score, all_scores = detect_loop_period(
            samples,
            skip_ms=args.skip_ms,
            search_min_ms=args.search_min_ms,
            search_max_ms=args.search_max_ms,
            step_ms=args.step_ms,
        )
        if period is None:
            print(f"{name:22s}  no detection (capture too short?)")
            continue

        delta = cycle_closure_delta(samples, period, skip_ms=args.skip_ms)
        delta_str = (f"({delta[0]:3d},{delta[1]:3d},{delta[2]:3d})"
                     if delta else "—")
        clean = score < args.clean_threshold
        verdict = "CLEAN" if clean else "noisy"

        # Show top alternates (excluding the global min and any within
        # 5% of period to avoid showing immediate neighbours).
        local = find_local_minima(all_scores, n=4)
        alternates = [(p, s) for p, s in local
                      if abs(p - period) > max(period * 0.05, args.step_ms * 2)]
        alts_str = ", ".join(f"{p}ms({s:.1f})" for p, s in alternates[:3])

        print(f"{name:22s}  {period:>7d} ms  {score:6.1f}  {delta_str:>16s}  "
              f"{verdict:10s}  {alts_str}")
        if clean:
            suggestions[name] = period

    if suggestions:
        print()
        print(">>> Suggested SHOW_LOOP_MS / CARD_SHOW_LOOP_MS overrides:")
        print()
        for name, period in suggestions.items():
            print(f'    "{name}": {period},')
        print()
        print("    (Verify visually before committing — pair with a "
              "card-side timeline render.)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
