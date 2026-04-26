#!/usr/bin/env python3
"""Enumerate every cv2-visible camera, identify it, and test whether
the cv2 backend supports locking auto-white-balance / autofocus /
auto-exposure on it.

Used by the calibration workflow to pick a camera that supports a
real WB lock — the built-in FaceTime camera silently rejects the
lock-cap properties on AVFoundation, while iPhone-via-Continuity
typically accepts them.

Usage:
    python tools/probe_cameras.py
    python tools/probe_cameras.py --max-index 6

Output is a table per camera: index, frame size, lock-attempt result
for AUTO_WB / AUTOFOCUS / AUTO_EXPOSURE. Re-run if you change which
cameras are connected.
"""
from __future__ import annotations

import argparse
import sys

import cv2


PROPS = [
    ("AUTO_WB", cv2.CAP_PROP_AUTO_WB, 0),
    ("AUTOFOCUS", cv2.CAP_PROP_AUTOFOCUS, 0),
    ("AUTO_EXPOSURE", cv2.CAP_PROP_AUTO_EXPOSURE, 0.25),
]


def probe(index: int) -> dict | None:
    """Return diagnostic dict for camera at `index`, or None if it
    doesn't open."""
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        return None
    try:
        # Pull one frame to make sure the camera actually delivers
        # data, not just opens. Some indices "open" but never produce
        # frames (placeholder slots).
        ok, frame = cap.read()
        if not ok or frame is None:
            return {"opens": True, "delivers_frame": False}
        h, w = frame.shape[:2]
        result = {"opens": True, "delivers_frame": True, "frame_wh": (w, h)}
        for name, prop, value in PROPS:
            ok = cap.set(prop, value)
            readback = cap.get(prop)
            result[name] = {"set_ok": bool(ok), "readback": readback}
        return result
    finally:
        cap.release()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--max-index", type=int, default=6,
                   help="probe indices 0..max-index inclusive (default 6)")
    args = p.parse_args()

    print(f"probing cv2 camera indices 0..{args.max_index} ...\n")
    found_any = False
    for idx in range(args.max_index + 1):
        info = probe(idx)
        if info is None:
            continue
        found_any = True
        print(f"=== camera index {idx} ===")
        if not info.get("delivers_frame"):
            print("  opens but does not deliver frames (skip)")
            continue
        w, h = info["frame_wh"]
        print(f"  resolution: {w}x{h}")
        for name, _, _ in PROPS:
            r = info[name]
            tag = "✓ LOCKED" if r["set_ok"] else "✗ rejected"
            print(f"  {name:16s} set→{tag}  readback={r['readback']}")
        print()
    if not found_any:
        print("no cameras found", file=sys.stderr)
        return 1
    print("Pick the camera index whose AUTO_WB / AUTO_EXPOSURE both")
    print("show '✓ LOCKED' (or whose AUTO_WB at least is ✓). Pass")
    print("that index to calibrate_show_colors.py via --camera N.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
