#!/usr/bin/env python3
"""Short camera observation to classify fixture state.

Opens the Mac's FaceTime camera, samples brightness for N seconds, and
reports whether the fixture is in a CYCLING state (likely Nova / another
show) or STABLE (a solid color or Standby).

Used interactively to verify test outcomes for issue #33 without
requiring a human observer to watch the pool.

Usage:
    python tools/observe_fixture.py [--seconds 10] [--camera 0]
"""

import argparse
import sys
import time

import cv2
import numpy as np


def observe(camera: int, seconds: float, sample_hz: float = 10.0,
            sat_threshold: int = 100) -> dict:
    """Observe the fixture through the camera; return motion stats + class.

    Auto-locates the fixture each frame by finding highly-saturated pixels
    (the fixture is typically the only saturated-colored thing in frame;
    pool water, tile, patio are mostly desaturated). Tracks the mean BGR
    of saturated pixels across time; cycling is detected via frame-to-
    frame color distance. Robust to daylight ambient without requiring
    precise camera framing.
    """
    cap = cv2.VideoCapture(camera)
    if not cap.isOpened():
        raise RuntimeError(
            f"could not open camera {camera}. On macOS, grant terminal "
            "Camera permission in Privacy settings."
        )
    for _ in range(5):
        cap.read()  # warm up

    interval = 1.0 / sample_hz
    samples: list[np.ndarray] = []  # BGR means of saturated pixels per sample
    v_samples: list[float] = []
    sat_pixel_counts: list[int] = []
    t_start = time.monotonic()
    last = 0.0
    while time.monotonic() - t_start < seconds:
        ret, frame = cap.read()
        if not ret:
            continue
        now = time.monotonic() - t_start
        if now - last < interval:
            continue
        last = now
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        # Require both high saturation AND decent brightness — shadows
        # in the pool water can be strongly saturated but dark, and we
        # don't want to mistake those for the fixture.
        sat_mask = (hsv[:, :, 1] >= sat_threshold) & (hsv[:, :, 2] >= 120)
        n_sat = int(sat_mask.sum())
        sat_pixel_counts.append(n_sat)
        if n_sat >= 10:
            bgr_mean = frame[sat_mask].mean(axis=0).astype(float)
            v_mean = float(hsv[:, :, 2][sat_mask].mean())
        else:
            # Fallback: no saturated pixels seen; use full-frame mean so
            # we still emit a sample (will classify as STABLE, which is
            # correct for Standby/dark).
            bgr_mean = frame.reshape(-1, 3).mean(axis=0).astype(float)
            v_mean = float(hsv[:, :, 2].mean())
        samples.append(bgr_mean)
        v_samples.append(v_mean)
    cap.release()

    if len(samples) < 2:
        raise RuntimeError("too few camera samples; camera may be blocked")

    bgr = np.array(samples)
    # Frame-to-frame Euclidean distance in BGR space.
    deltas = np.linalg.norm(np.diff(bgr, axis=0), axis=1)
    mean_delta = float(deltas.mean())
    max_delta = float(deltas.max())

    # Color range: span of the sample cloud — tells us how much the
    # fixture's dominant color varied during observation.
    color_range = float(np.linalg.norm(bgr.max(axis=0) - bgr.min(axis=0)))

    v_arr = np.array(v_samples)

    # CYCLING heuristic: sustained high frame-to-frame motion AND large
    # total color range indicates the fixture is cycling colors.
    # STABLE: both metrics small.
    cycling = mean_delta >= 2.5 and color_range >= 25.0

    return {
        "n_samples": len(samples),
        "mean_sat_pixels": float(np.mean(sat_pixel_counts)),
        "mean_v": float(v_arr.mean()),
        "std_v": float(v_arr.std()),
        "mean_delta_bgr": mean_delta,
        "max_delta_bgr": max_delta,
        "color_range_bgr": color_range,
        "classification": "CYCLING" if cycling else "STABLE",
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seconds", type=float, default=10.0)
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--sat-threshold", type=int, default=100,
                   help="saturation threshold (0-255) for isolating the "
                        "fixture from desaturated pool/patio background. "
                        "Default 100.")
    args = p.parse_args()

    try:
        result = observe(args.camera, args.seconds,
                         sat_threshold=args.sat_threshold)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(
        f"{result['classification']:<8}  "
        f"n={result['n_samples']}  "
        f"sat_px={result['mean_sat_pixels']:.0f}  "
        f"V_mean={result['mean_v']:.1f}  "
        f"BGR_delta_mean={result['mean_delta_bgr']:.2f}  "
        f"BGR_delta_max={result['max_delta_bgr']:.2f}  "
        f"BGR_range={result['color_range_bgr']:.1f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
