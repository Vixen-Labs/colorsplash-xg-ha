#!/usr/bin/env python3
"""Aggregate per-replay timings from a `show_colors_video.json` produced
by `tools/extract_colors_from_video.py` against a `replay_probe.py`
events log, and report the across-replay consistency statistics for a
single show.

Inputs:
    --extracted PATH    show_colors_video.json from extract_colors_from_video.py
                        (must have entries like 'Patriot Dream #1',
                        'Patriot Dream #2', …)
    --show NAME         the human name of the show under test
                        (e.g. "Patriot Dream"). Matches all entries
                        whose key starts with "<NAME> #".

Outputs (stdout):
  - Per-replay metrics:
      * "old color persists" duration (t = 0 → first dark frame)
      * blackout duration (first dark → first new color)
      * total command-to-first-color delay
      * RGB at the first new-color sample
  - Across-replay summary (mean ± stdev, min, max)
  - A verdict on whether the timing is reproducible enough for the
    Phase 4b RGB picker.

Usage:
    python tools/analyze_replay_consistency.py \\
        --extracted tools/show_colors_replay.json \\
        --show "Patriot Dream"
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Optional


def _brightness(rgb: list[int]) -> float:
    return sum(rgb) / 3.0


def detect_transition(samples: list[dict],
                      ambient_brightness: float,
                      ) -> Optional[dict]:
    """Walk one show's per-frame samples (each a dict with t_ms and
    rgb). Find the dark-period start (first dark frame after t=0)
    and the new-color appearance (first sustained-bright frame after
    >=1 s of dark). Return a dict of metrics or None if the pattern
    couldn't be detected."""
    if len(samples) < 30:
        return None
    dark_thresh = ambient_brightness + 15
    color_thresh = ambient_brightness + 30

    # First dark frame (after t=0).
    dark_idx = next(
        (i for i, s in enumerate(samples)
         if _brightness(s["rgb"]) < dark_thresh),
        None,
    )
    if dark_idx is None:
        return None

    # Walk forward to first sustained color (>= 0.5 s above
    # color_thresh after at least 1 s of dark).
    n = len(samples)
    color_idx = None
    for i in range(dark_idx + 30, n - 15):
        if _brightness(samples[i]["rgb"]) > color_thresh:
            ok = all(_brightness(samples[j]["rgb"]) > color_thresh
                     for j in range(i, min(i + 15, n)))
            if ok:
                color_idx = i
                break
    if color_idx is None:
        return None

    return {
        "old_color_persists_ms": samples[dark_idx]["t_ms"],
        "blackout_duration_ms":
            samples[color_idx]["t_ms"] - samples[dark_idx]["t_ms"],
        "command_to_color_ms": samples[color_idx]["t_ms"],
        "first_color_rgb": samples[color_idx]["rgb"],
    }


def summarise(label: str, values: list[float]) -> None:
    if not values:
        print(f"  {label:30s}: (no data)")
        return
    if len(values) == 1:
        print(f"  {label:30s}: {values[0]:.0f}  (n=1)")
        return
    mean = statistics.mean(values)
    sd = statistics.pstdev(values)
    print(f"  {label:30s}: mean={mean:.0f}  sd={sd:.0f}  "
          f"min={min(values):.0f}  max={max(values):.0f}  n={len(values)}")


def verdict(per_replay: list[dict]) -> str:
    """Heuristic call on whether the timing is consistent enough."""
    if len(per_replay) < 3:
        return ("INCONCLUSIVE — need at least 3 replays for a "
                "meaningful spread.")
    blackouts = [r["blackout_duration_ms"] for r in per_replay]
    cmd_to_color = [r["command_to_color_ms"] for r in per_replay]
    blackout_sd = statistics.pstdev(blackouts)
    cmd_sd = statistics.pstdev(cmd_to_color)
    # Heuristic: <=200 ms stdev on command-to-color is "tight";
    # 200-500 ms is "usable with a tolerance window"; >500 ms is
    # "too jittery for a deterministic picker."
    if cmd_sd <= 200:
        return (f"GOOD — command-to-color sd is {cmd_sd:.0f} ms "
                f"(tight). Picker can predict transitions to within "
                f"~{int(2 * cmd_sd)} ms (95% confidence).")
    if cmd_sd <= 500:
        return (f"USABLE — command-to-color sd is {cmd_sd:.0f} ms. "
                f"Picker should leave a ~{int(3 * cmd_sd)} ms "
                f"tolerance window when locking onto a target color.")
    return (f"POOR — command-to-color sd is {cmd_sd:.0f} ms (>500 ms). "
            f"The transition envelope drifts too much for a "
            f"deterministic picker; consider photodiode sync or "
            f"in-loop color feedback (Phase 4c).")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--extracted", required=True, type=Path)
    p.add_argument("--show", required=True,
                   help="show name to aggregate (matches "
                        "'<show> #N' keys in the extracted JSON)")
    args = p.parse_args()

    if not args.extracted.exists():
        print(f"error: not found: {args.extracted}", file=sys.stderr)
        return 1

    data = json.loads(args.extracted.read_text())
    if "ambient_rgb" not in data or data["ambient_rgb"] is None:
        print("error: extracted JSON has no ambient_rgb baseline; "
              "cannot detect transitions.", file=sys.stderr)
        return 1
    ambient = _brightness(data["ambient_rgb"])
    print(f"ambient brightness baseline: {ambient:.1f}")

    prefix = f"{args.show} #"
    matching = sorted(
        (k for k in data["shows"] if k.startswith(prefix)),
        key=lambda k: int(k.split("#")[-1]),
    )
    if not matching:
        keys = ", ".join(data["shows"]) or "(none)"
        print(f"error: no entries matching '{prefix}<N>' in extracted "
              f"JSON. available shows: {keys}", file=sys.stderr)
        return 1

    print(f"\nfound {len(matching)} replays of '{args.show}':")
    print()
    print(f"  {'replay':10s}  {'old-color persists':>19s}  "
          f"{'blackout':>10s}  {'cmd→color':>11s}  rgb at first color")
    print("  " + "-" * 90)
    per_replay: list[dict] = []
    for key in matching:
        samples = data["shows"][key]
        result = detect_transition(samples, ambient)
        if result is None:
            print(f"  {key:10s}  (transition not detected — fewer "
                  f"frames than expected, or no dark→color cycle)")
            continue
        per_replay.append(result)
        replay_n = key.split("#")[-1]
        print(f"  #{replay_n:9s}  "
              f"{result['old_color_persists_ms']:>16d}ms  "
              f"{result['blackout_duration_ms']:>7d}ms  "
              f"{result['command_to_color_ms']:>8d}ms  "
              f"{result['first_color_rgb']}")

    print()
    print("Across-replay distribution:")
    summarise("old-color persists (ms)",
              [r["old_color_persists_ms"] for r in per_replay])
    summarise("blackout duration (ms)",
              [r["blackout_duration_ms"] for r in per_replay])
    summarise("command-to-color (ms)",
              [r["command_to_color_ms"] for r in per_replay])

    print()
    print(f"Verdict: {verdict(per_replay)}")

    # Bonus: report first-color RGB consistency. If the controller's
    # AC-interrupt sequence is reproducible, the first new color
    # the fixture lands on should also be reproducible.
    if len(per_replay) >= 2:
        rs = [r["first_color_rgb"][0] for r in per_replay]
        gs = [r["first_color_rgb"][1] for r in per_replay]
        bs = [r["first_color_rgb"][2] for r in per_replay]
        print()
        print("First-color RGB across replays:")
        summarise("R", rs)
        summarise("G", gs)
        summarise("B", bs)

    return 0


if __name__ == "__main__":
    sys.exit(main())
