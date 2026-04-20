#!/usr/bin/env python3
"""Measure fixture visual-transition latency from a sweep video + log.

Given:
  - a QuickTime / MP4 recording of the pool fixture during a bleak
    --sweep run
  - the cli.py sweep.log (write timestamps + effect names)

This tool extracts per-frame brightness from the video, auto-syncs
the video's time axis to the log's wall-clock using the first major
brightness change as the anchor, then for each write event finds:
  - onset_s    : time from write to fixture going dark (brightness drop)
  - nadir_s    : time from write to darkest point (blackout midpoint)
  - stable_s   : time from write to steady-state new brightness
  - total_s    : same as stable_s — the full visible transition
  - dark_s     : duration the fixture was below the dark threshold

Outputs a markdown table to stdout. Intended to replace the
"5-8 s estimate" in docs/PROTOCOL.md with measured values.

Usage:
    python tools/measure_latency.py CAPTURE_DIR [--sample-fps N]

CAPTURE_DIR must contain session.mov (or session.mp4) and sweep.log.

Requires opencv-python + numpy in the active venv.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np


WRITE_RE = re.compile(
    r"\[(\d{2}:\d{2}:\d{2})\.(\d{3})\s+INFO\s+ble\.indication\.echo\]\s+"
    r"byte=0x([0-9a-f]{2})\s+name=\"([^\"]+)\""
)


@dataclass
class WriteEvent:
    wall_ts: datetime  # absolute laptop wall clock, tz-naive
    byte: int
    name: str


@dataclass
class Measurement:
    name: str
    byte: int
    onset_s: float | None
    nadir_s: float | None
    dark_s: float | None
    stable_s: float | None


def parse_sweep_log(path: Path) -> list[WriteEvent]:
    """Extract write events from a cli.py sweep log."""
    events: list[WriteEvent] = []
    today = datetime.now().date()
    for line in path.read_text().splitlines():
        m = WRITE_RE.search(line)
        if not m:
            continue
        hms, ms, byte_hex, name = m.groups()
        t = datetime.strptime(f"{today} {hms}.{ms}000", "%Y-%m-%d %H:%M:%S.%f")
        events.append(WriteEvent(wall_ts=t, byte=int(byte_hex, 16), name=name))
    return events


def sample_video_brightness(
    video_path: Path, sample_fps: float = 2.0
) -> tuple[list[float], list[float]]:
    """Return (times_s, brightnesses) sampled at roughly sample_fps.

    brightness is mean of V channel in HSV, 0..255.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(int(round(fps / sample_fps)), 1)

    times: list[float] = []
    brights: list[float] = []
    i = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if i % step == 0:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            # Mean V (value/brightness).
            v = float(hsv[:, :, 2].mean())
            times.append(i / fps)
            brights.append(v)
        i += 1
    cap.release()
    return times, brights


def find_first_drop(
    brights: list[float], threshold_drop: float = 30.0, window: int = 5
) -> int | None:
    """Return the index of the first sample where brightness drops by
    threshold_drop within `window` samples, or None.

    Heuristic: the first "fixture goes dark" transition.
    """
    if len(brights) < window + 1:
        return None
    for i in range(window, len(brights)):
        if brights[i - window] - brights[i] >= threshold_drop:
            return i - window
    return None


def measure_transitions(
    events: list[WriteEvent],
    times: list[float],
    brights: list[float],
    video_start_wall: datetime,
    search_window_s: float = 20.0,
    dark_threshold_frac: float = 0.35,
) -> list[Measurement]:
    """For each write event, find the transition window in the video."""
    arr_t = np.asarray(times)
    arr_b = np.asarray(brights)

    measurements: list[Measurement] = []
    for ev in events:
        rel = (ev.wall_ts - video_start_wall).total_seconds()
        # Window: [rel, rel + search_window_s]
        mask = (arr_t >= rel) & (arr_t <= rel + search_window_s)
        if not mask.any():
            measurements.append(
                Measurement(ev.name, ev.byte, None, None, None, None)
            )
            continue
        win_t = arr_t[mask]
        win_b = arr_b[mask]

        # Establish pre-event baseline: mean brightness in the 2 s before
        # the write. If the fixture was already dark (e.g. last effect
        # transitioning), this might be low.
        pre_mask = (arr_t >= rel - 3.0) & (arr_t < rel)
        baseline = float(arr_b[pre_mask].mean()) if pre_mask.any() else float(win_b[:2].mean())

        # Dark threshold: fraction of the baseline (or 60 of raw, whichever
        # is smaller, so we don't get stuck if baseline is already low).
        dark_thresh = min(baseline * dark_threshold_frac, 60.0)

        # Nadir within window.
        nadir_idx = int(np.argmin(win_b))
        nadir_s = float(win_t[nadir_idx] - rel)

        # Onset: first index where brightness dips below (baseline - 20).
        onset_thresh = baseline - 20.0
        below = np.where(win_b <= onset_thresh)[0]
        onset_s = float(win_t[below[0]] - rel) if below.size else None

        # Dark duration: samples below dark_thresh.
        dark_mask = win_b <= dark_thresh
        dark_s = float(dark_mask.sum() / max(1, len(win_b)) * search_window_s)

        # Stable: first index AFTER nadir where brightness returns above
        # baseline * 0.8 AND stays above for >= 1.0 s of samples.
        stable_thresh = baseline * 0.8
        stable_s: float | None = None
        if nadir_idx < len(win_b) - 1:
            tail = win_b[nadir_idx + 1 :]
            tail_t = win_t[nadir_idx + 1 :]
            # For each crossing, check the next ~2 s stays above.
            for j, v in enumerate(tail):
                if v >= stable_thresh:
                    # Confirm stability: look ahead 1 s.
                    lookahead_end = tail_t[j] + 1.0
                    ahead = tail[(tail_t >= tail_t[j]) & (tail_t <= lookahead_end)]
                    if len(ahead) and ahead.min() >= stable_thresh * 0.85:
                        stable_s = float(tail_t[j] - rel)
                        break

        # If stable didn't resolve, and the last sample is above threshold,
        # use the last sample conservatively.
        if stable_s is None and len(win_b) and win_b[-1] >= stable_thresh:
            stable_s = float(win_t[-1] - rel)

        measurements.append(
            Measurement(ev.name, ev.byte, onset_s, nadir_s, dark_s, stable_s)
        )

    return measurements


def auto_sync(
    events: list[WriteEvent],
    times: list[float],
    brights: list[float],
    expected_onset_s: float = 0.8,
) -> datetime:
    """Infer video_start wall clock.

    Assumption: the first meaningful brightness drop in the video is
    the response to the first write. The drop arrives ~onset_s after
    the write byte went out on the wire. This handles the user having
    hit record at some arbitrary time before the sweep started.
    """
    first_drop_idx = find_first_drop(brights)
    if first_drop_idx is None:
        raise RuntimeError(
            "could not find a meaningful brightness drop in the video; "
            "is the fixture actually in frame?"
        )
    first_drop_t = times[first_drop_idx]
    first_write_wall = events[0].wall_ts
    # first_drop_t == (first_write_wall + expected_onset_s) - video_start_wall
    # → video_start_wall = first_write_wall + expected_onset_s - first_drop_t
    video_start_wall = first_write_wall + timedelta(
        seconds=expected_onset_s - first_drop_t
    )
    return video_start_wall


def format_report(
    measurements: list[Measurement],
    video_start_wall: datetime,
    first_write_wall: datetime,
) -> str:
    sync_offset = (first_write_wall - video_start_wall).total_seconds()

    def fmt(v: float | None) -> str:
        return f"{v:.2f}" if v is not None else "-"

    lines = [
        f"# Visual-transition latency measurements",
        "",
        f"Video-to-log sync: first write was {sync_offset:.2f} s into the recording.",
        "",
        "| Effect | Byte | Onset (s) | Nadir (s) | Dark (s) | Stable (s) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for m in measurements:
        lines.append(
            f"| {m.name} | 0x{m.byte:02x} | "
            f"{fmt(m.onset_s)} | {fmt(m.nadir_s)} | "
            f"{fmt(m.dark_s)} | {fmt(m.stable_s)} |"
        )

    # Summary stats across commands that resolved.
    stable_vals = [m.stable_s for m in measurements if m.stable_s is not None]
    dark_vals = [m.dark_s for m in measurements if m.dark_s is not None]
    if stable_vals:
        lines.extend(
            [
                "",
                "**Summary:**",
                f"- total transition (stable): "
                f"min {min(stable_vals):.2f} s, "
                f"max {max(stable_vals):.2f} s, "
                f"mean {sum(stable_vals)/len(stable_vals):.2f} s "
                f"(n={len(stable_vals)})",
            ]
        )
    if dark_vals:
        lines.append(
            f"- dark duration: "
            f"min {min(dark_vals):.2f} s, "
            f"max {max(dark_vals):.2f} s, "
            f"mean {sum(dark_vals)/len(dark_vals):.2f} s "
            f"(n={len(dark_vals)})"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("--sample-fps", type=float, default=2.0,
                        help="video sampling rate (default 2 fps)")
    parser.add_argument("--expected-onset", type=float, default=0.8,
                        help="expected seconds from write to blackout onset, for sync (default 0.8)")
    args = parser.parse_args()

    cdir = args.capture_dir
    log = cdir / "sweep.log"
    video = next((cdir / n for n in ("session.mov", "session.mp4") if (cdir / n).exists()), None)
    if video is None:
        print(f"no session.mov or session.mp4 in {cdir}", file=sys.stderr)
        return 2
    if not log.exists():
        print(f"no sweep.log in {cdir}", file=sys.stderr)
        return 2

    events = parse_sweep_log(log)
    if not events:
        print(f"no write events parsed from {log}", file=sys.stderr)
        return 1
    print(f"parsed {len(events)} write events from {log.name}", file=sys.stderr)

    print(f"sampling {video.name} at {args.sample_fps} fps...", file=sys.stderr)
    times, brights = sample_video_brightness(video, sample_fps=args.sample_fps)
    print(f"  got {len(times)} samples, span {times[-1]:.1f} s", file=sys.stderr)

    video_start_wall = auto_sync(events, times, brights, args.expected_onset)
    print(f"inferred video start: {video_start_wall.strftime('%H:%M:%S.%f')[:-3]}",
          file=sys.stderr)

    measurements = measure_transitions(events, times, brights, video_start_wall)
    print(format_report(measurements, video_start_wall, events[0].wall_ts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
