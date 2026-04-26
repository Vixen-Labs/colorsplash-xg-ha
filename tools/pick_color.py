#!/usr/bin/env python3
"""Phase 4b show-scrub picker. Given a target observed RGB, find the
(show, wait_ms) pair from a calibration dataset whose sample is
nearest to the target, and optionally drive the bridge to display it.

The picker operates in OBSERVED-RGB space — not the fixture's true
emitted RGB. The colour the user picks is "what the pool looks like"
through whatever camera the calibration was performed with. No
display-referred colour-management transforms are applied.

Usage:
    # show top match for a target RGB:
    python tools/pick_color.py --target 200,50,100

    # show top 5 candidates instead:
    python tools/pick_color.py --target 200,50,100 --top 5

    # drive the bridge to display the best match (calls pool_scrub):
    export COLORSPLASH_API_KEY="$(cat /tmp/colorsplash-key)"
    python tools/pick_color.py --target 200,50,100 --send

    # use a different dataset (default tools/show_colors_video.json):
    python tools/pick_color.py --target 200,50,100 \\
        --dataset tools/show_colors.json

Match recipe details:
- Distance metric: Euclidean in observed RGB. Perceptual distances
  (Lab/CIEDE2000) would be more accurate for human-meaningful colour
  matching but require colorimetric calibration we don't have. The
  fixture+pool reflectance space is non-standard anyway, so the
  Euclidean metric over observed RGB is fine for "look like" matching.
- Skip-early window: samples with t_ms < --skip-ms are excluded so
  we don't pick a moment in the blackout / "old colour persists"
  early window. Default 2500 ms covers the ~1.6 s firmware-dispatch
  delay + a small margin.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from pathlib import Path


# Show name → start byte. Matches docs/PROTOCOL.md.
SHOW_BYTES = {
    "Nova": 0x07,
    "Super Nova": 0x02,
    "Northern Lights": 0x03,
    "Tidal Wave": 0x04,
    "Patriot Dream": 0x05,
    "Desert Skies": 0x06,
    "Peruvian Paradise": 0x01,
}

# Solid colours — single byte, no scrub needed. Always preferred
# over a show-scrub when their distance is competitive: deterministic,
# no transition timing, no Lock needed.
SOLID_BYTES = {
    "Parisian Blue": 0x08,
    "Brazilian Red": 0x0a,
    "Arctic White": 0x0b,
    "Miami Pink": 0x0c,
    "New Zealand Green": 0x09,
}


def parse_rgb(s: str) -> tuple[int, int, int]:
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"--target must be R,G,B (3 ints 0-255); got '{s}'")
    try:
        rgb = tuple(int(p) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--target values must be integers; got '{s}'")
    if not all(0 <= v <= 255 for v in rgb):
        raise argparse.ArgumentTypeError(
            f"--target values must be in 0-255; got {rgb}")
    return rgb  # type: ignore[return-value]


def distance(a: tuple[int, int, int],
             b: list[int]) -> float:
    """Plain Euclidean distance in RGB space. Good enough for the
    'looks like' matching the picker is for."""
    return math.sqrt(
        (a[0] - b[0]) ** 2
        + (a[1] - b[1]) ** 2
        + (a[2] - b[2]) ** 2,
    )


def find_matches(target: tuple[int, int, int],
                 dataset: dict,
                 skip_ms: int,
                 top_n: int,
                 solid_preference: float = 30.0) -> list[dict]:
    """Search every solid + show sample, return top_n candidates
    ranked by RGB distance.

    Each candidate dict has:
      kind            "solid" or "show"
      name            human label
      start_byte      the byte to send to the controller
      wait_ms         None for solids; integer offset for shows
      rgb             observed RGB at this candidate
      distance        true Euclidean distance to target
      effective_dist  distance used for ranking (solids get
                      `solid_preference` subtracted to bias them
                      over close-but-not-clearly-better show
                      samples — shows are inherently jittery in
                      timing so a deterministic solid is preferred
                      when results are similar)

    Solids are always single-entry; for the picker they're a
    deterministic single-byte command (no scrub, no Lock).
    """
    candidates: list[dict] = []

    # ---- Solids ----
    for name, rgb in dataset.get("solids", {}).items():
        if name not in SOLID_BYTES:
            continue
        d = distance(target, rgb)
        candidates.append({
            "distance": d,
            "effective_dist": max(0.0, d - solid_preference),
            "kind": "solid",
            "name": name,
            "start_byte": SOLID_BYTES[name],
            "wait_ms": None,
            "rgb": rgb,
        })

    # ---- Show samples ----
    for show_name, samples in dataset.get("shows", {}).items():
        # Replay-mode-aware: collapse "<show> #N" to its base name.
        base = show_name.split(" #")[0]
        if base not in SHOW_BYTES:
            continue
        for s in samples:
            if s["t_ms"] < skip_ms:
                continue
            d = distance(target, s["rgb"])
            candidates.append({
                "distance": d,
                "effective_dist": d,
                "kind": "show",
                "name": show_name,
                "start_byte": SHOW_BYTES[base],
                "wait_ms": s["t_ms"],
                "rgb": s["rgb"],
            })

    candidates.sort(key=lambda c: c["effective_dist"])
    return candidates[:top_n]


def format_match(m: dict) -> str:
    rgb = m["rgb"]
    rgb_s = f"({rgb[0]:3d}, {rgb[1]:3d}, {rgb[2]:3d})"
    if m["kind"] == "solid":
        return (f"  [solid] {m['name']:22s}  "
                f"send_byte=0x{m['start_byte']:02x}  "
                f"observed RGB={rgb_s}  distance={m['distance']:5.1f}")
    wait = m["wait_ms"] if m["wait_ms"] is not None else 0
    return (f"  [show ] {m['name']:22s}  "
            f"start_byte=0x{m['start_byte']:02x}  "
            f"wait_ms={wait:6d}  observed RGB={rgb_s}  "
            f"distance={m['distance']:5.1f}")


async def send_via_bridge(host: str, port: int, noise_psk: str,
                          match: dict) -> None:
    """Drive the bridge to display `match`. Solids use the simpler
    `pool_send_byte` (deterministic, no Lock). Shows use `pool_scrub`
    which sends start_byte, waits wait_ms, then sends Lock."""
    try:
        from aioesphomeapi import APIClient
    except ImportError as exc:
        print(f"missing aioesphomeapi: pip install aioesphomeapi  ({exc})",
              file=sys.stderr)
        return

    api = APIClient(host, port, password="", noise_psk=noise_psk)
    await api.connect(login=True)
    try:
        _, services = await api.list_entities_services()
        if match["kind"] == "solid":
            svc = next(
                (s for s in services if s.name == "pool_send_byte"), None)
            if svc is None:
                print("error: bridge does not expose 'pool_send_byte'.",
                      file=sys.stderr)
                return
            await api.execute_service(
                svc, {"byte": match["start_byte"]})
            print(f">>> sent pool_send_byte(byte=0x"
                  f"{match['start_byte']:02x}) — '{match['name']}'.")
        else:
            svc = next(
                (s for s in services if s.name == "pool_scrub"), None)
            if svc is None:
                print("error: bridge does not expose 'pool_scrub'.",
                      file=sys.stderr)
                return
            await api.execute_service(svc, {
                "start_byte": match["start_byte"],
                "wait_ms": match["wait_ms"],
            })
            print(f">>> sent pool_scrub(start_byte=0x"
                  f"{match['start_byte']:02x}, "
                  f"wait_ms={match['wait_ms']}) — "
                  f"'{match['name']}'.")
    finally:
        await api.disconnect()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", required=True, type=parse_rgb,
                   help="target observed RGB as 'R,G,B' (0-255 each)")
    p.add_argument("--dataset", type=Path,
                   default=Path("tools/show_colors_video.json"),
                   help="calibration JSON to search "
                        "(default tools/show_colors_video.json)")
    p.add_argument("--top", type=int, default=1,
                   help="show this many top candidates (default 1). "
                        "Useful for inspecting alternatives — when the "
                        "best match is borderline, the runner-up may "
                        "be a different show with similar distance.")
    p.add_argument("--skip-ms", type=int, default=2500,
                   help="exclude samples with t_ms < this (default "
                        "2500 — covers the ~1.6 s firmware-dispatch "
                        "delay before the show actually starts)")
    p.add_argument("--solid-preference", type=float, default=30.0,
                   help="bias toward solids by subtracting this "
                        "from solid distances when ranking. Solids "
                        "are deterministic; shows have inherent "
                        "timing variance, so a slightly-farther "
                        "solid is usually a better choice than a "
                        "marginally-closer show sample. Default 30 "
                        "— means a solid wins unless a show sample "
                        "is more than 30 RGB-distance closer. Set "
                        "to 0 to disable the bias.")
    p.add_argument("--send", action="store_true",
                   help="after picking the top match, call the "
                        "bridge's pool_scrub service to drive the "
                        "fixture to display it")
    p.add_argument("--host", default="colorsplash-xg-bridge.local")
    p.add_argument("--port", type=int, default=6053)
    p.add_argument("--api-key", default=None,
                   help="ESPHome native-API noise PSK; falls back to "
                        "env COLORSPLASH_API_KEY")
    args = p.parse_args()

    if not args.dataset.exists():
        print(f"error: dataset not found: {args.dataset}",
              file=sys.stderr)
        return 1
    data = json.loads(args.dataset.read_text())

    matches = find_matches(args.target, data, args.skip_ms, args.top,
                           solid_preference=args.solid_preference)
    if not matches:
        print("error: no candidates found in dataset (after skip_ms "
              "filter)", file=sys.stderr)
        return 1

    target_str = f"({args.target[0]}, {args.target[1]}, {args.target[2]})"
    print(f"target observed RGB = {target_str}")
    print(f"dataset = {args.dataset}  ({sum(len(v) for v in data.get('shows', {}).values())} samples across {len(data.get('shows', {}))} shows)")
    print()
    print(f"top {len(matches)} match(es):")
    for m in matches:
        print(format_match(m))

    if args.send:
        best = matches[0]
        print()
        noise_psk = os.environ.get("COLORSPLASH_API_KEY") or args.api_key
        if not noise_psk:
            print("error: --send requires COLORSPLASH_API_KEY env var "
                  "or --api-key", file=sys.stderr)
            return 2
        asyncio.run(send_via_bridge(
            args.host, args.port, noise_psk, best,
        ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
