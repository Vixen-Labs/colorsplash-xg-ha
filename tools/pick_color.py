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
                 top_n: int) -> list[dict]:
    """Search every show sample whose t_ms >= skip_ms, return top_n
    candidates ranked by RGB distance, each as a dict with show name,
    t_ms, observed RGB, distance, and start_byte."""
    candidates: list[tuple[float, str, int, list[int]]] = []
    for show_name, samples in dataset.get("shows", {}).items():
        # Guard against any non-base shows like "Patriot Dream #1"
        # that came from replay_probe — match the *base* show name to
        # SHOW_BYTES, skipping anything we don't recognise.
        base = show_name.split(" #")[0]
        if base not in SHOW_BYTES:
            continue
        for s in samples:
            if s["t_ms"] < skip_ms:
                continue
            d = distance(target, s["rgb"])
            candidates.append((d, show_name, s["t_ms"], s["rgb"]))
    candidates.sort(key=lambda c: c[0])
    return [
        {
            "distance": d,
            "show": show_name,
            "start_byte": SHOW_BYTES[show_name.split(" #")[0]],
            "wait_ms": t_ms,
            "rgb": rgb,
        }
        for d, show_name, t_ms, rgb in candidates[:top_n]
    ]


def format_match(m: dict) -> str:
    rgb = m["rgb"]
    return (f"  {m['show']:22s}  start_byte=0x{m['start_byte']:02x}  "
            f"wait_ms={m['wait_ms']:6d}  observed RGB=({rgb[0]:3d}, "
            f"{rgb[1]:3d}, {rgb[2]:3d})  distance={m['distance']:5.1f}")


async def send_via_bridge(host: str, port: int, noise_psk: str,
                          start_byte: int, wait_ms: int) -> None:
    """Call the bridge's pool_scrub service to actually display the
    match. The bridge sends start_byte, waits wait_ms, then sends
    Lock (0x0d)."""
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
        svc = next((s for s in services if s.name == "pool_scrub"), None)
        if svc is None:
            print("error: bridge does not expose 'pool_scrub' service.",
                  file=sys.stderr)
            return
        await api.execute_service(
            svc, {"start_byte": start_byte, "wait_ms": wait_ms},
        )
        print(f">>> sent pool_scrub(start_byte=0x{start_byte:02x}, "
              f"wait_ms={wait_ms}) to bridge.")
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

    matches = find_matches(args.target, data, args.skip_ms, args.top)
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
            args.host, args.port, noise_psk,
            best["start_byte"], best["wait_ms"],
        ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
