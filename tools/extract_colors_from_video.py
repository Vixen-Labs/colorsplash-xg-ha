#!/usr/bin/env python3
"""Post-process a video file (e.g. from Final Cut Pro with manually
locked white balance + exposure) and align it to a calibration events
log to produce high-quality per-show color timelines.

Pipeline:

  1. Open the video (cv2.VideoCapture); read every frame.
  2. Sample mean RGB inside a fixed ROI for each frame, building a
     timeseries of (video_t_ms, rgb).
  3. Auto-detect the sync flash — the WB-cal Arctic White send near
     the start of the calibration run produces a sharp brightness
     step in the video. Find the frame where mean ROI brightness
     first exceeds ambient + a margin, and call that frame
     `t_video = T_first_white`.
  4. Read the events log (JSONL); the first `kind=wb-cal` event has
     the script's `monotonic` timestamp `T_script_first_white`. The
     offset between the two timelines is then known.
  5. For every event in the log, locate the corresponding video
     frame and (for show events) extract a 90 s window of frames as
     samples in the same JSON shape as
     `tools/calibrate_show_colors.py`'s output.

Usage:
    python tools/extract_colors_from_video.py \\
        --video /path/to/recording.mov \\
        --events tools/events.jsonl \\
        --roi-cx 1280 --roi-cy 540 --roi-half 80 \\
        --output tools/show_colors_video.json

The video's ROI coordinates are in the FCP recording's pixel space
(usually 1920×1080 or 4K), independent of any cv2 camera ROI used
during the live calibration. Click an ROI on a still from the video
in any image viewer or use --roi-preview to step through frames.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


@dataclass
class Roi:
    cx: int
    cy: int
    half: int = 60

    @property
    def xywh(self) -> tuple[int, int, int, int]:
        x = max(0, self.cx - self.half)
        y = max(0, self.cy - self.half)
        w = self.half * 2
        h = self.half * 2
        return x, y, w, h

    def sample_rgb(self, frame_bgr: np.ndarray) -> tuple[int, int, int]:
        x, y, w, h = self.xywh
        patch = frame_bgr[y : y + h, x : x + w]
        if patch.size == 0:
            return (0, 0, 0)
        b, g, r = patch.mean(axis=(0, 1))
        return (int(round(r)), int(round(g)), int(round(b)))


def load_events(path: Path) -> list[dict]:
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def select_roi_from_video(video_path: Path, half: int) -> Roi:
    """Open the video, show frame near the start (Arctic White
    expected to be the brightest spot), let user click the pool ROI."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"error: cannot open {video_path}", file=sys.stderr)
        sys.exit(1)
    # Seek a few seconds in so the brightness step from the sync
    # flash is visible.
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    target_frame = int(min(15.0 * fps, cap.get(cv2.CAP_PROP_FRAME_COUNT) - 1))
    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        print("error: cannot read frame from video", file=sys.stderr)
        sys.exit(1)

    state = {"point": None}

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN:
            state["point"] = (x, y)

    win = "Pick ROI on video — click the lit pool spot, then Enter"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)
    print(f"\n>>> Click the pool's lit spot in the video preview "
          f"(frame at ~15s, {half}-pixel half-width). Press Enter "
          "when satisfied.")
    while True:
        display = frame.copy()
        if state["point"]:
            x, y = state["point"]
            cv2.rectangle(display, (x - half, y - half), (x + half, y + half),
                          (0, 255, 0), 2)
            cv2.putText(display, f"({x}, {y})", (x + half + 5, y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imshow(win, display)
        k = cv2.waitKey(20) & 0xFF
        if k == 13 and state["point"]:
            break
        if k == 27:
            cv2.destroyWindow(win)
            sys.exit(1)
    cv2.destroyWindow(win)
    cx, cy = state["point"]
    print(f"    ROI = (cx={cx}, cy={cy}, half={half})")
    return Roi(cx=cx, cy=cy, half=half)


def walk_video(video_path: Path, roi: Roi
               ) -> tuple[float, list[tuple[float, tuple[int, int, int]]]]:
    """Walk every frame of the video, return (fps, [(video_t_s, rgb), ...])."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    samples = []
    idx = 0
    last_print = time.monotonic()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t_s = idx / fps
            samples.append((t_s, roi.sample_rgb(frame)))
            idx += 1
            now = time.monotonic()
            if now - last_print >= 2.0:
                print(f"  walked {idx} frames "
                      f"(video t={t_s:.1f}s) ...", flush=True)
                last_print = now
    finally:
        cap.release()
    print(f"  walked {idx} frames total ({idx / fps:.1f}s @ {fps:.1f}fps)")
    return fps, samples


def find_sync_flash(samples: list[tuple[float, tuple[int, int, int]]],
                    threshold_delta: float = 50.0,
                    skip_initial_s: float = 1.0,
                    fps_hint: float = 30.0,
                    ) -> Optional[float]:
    """Find the frame timestamp where the brightness first jumps by
    `threshold_delta` over the rolling baseline. Skip the first
    `skip_initial_s` seconds to ignore camera startup transients."""
    if not samples:
        return None
    skip_n = int(skip_initial_s * fps_hint)
    if len(samples) <= skip_n + 5:
        return None
    # Baseline = median brightness of the first chunk (before the flash).
    baseline_samples = samples[skip_n : skip_n + int(2.0 * fps_hint)]
    if not baseline_samples:
        baseline_samples = samples[:skip_n]
    baseline_brightness = np.median(
        [sum(rgb) / 3.0 for _, rgb in baseline_samples],
    )
    target = baseline_brightness + threshold_delta
    print(f"  sync-flash search: baseline brightness = "
          f"{baseline_brightness:.1f}, looking for ≥ {target:.1f}")
    for t, rgb in samples[skip_n:]:
        if sum(rgb) / 3.0 >= target:
            return t
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--video", required=True, type=Path,
                   help="video file (.mov / .mp4) of the calibration run")
    p.add_argument("--events", required=True, type=Path,
                   help="events JSONL produced by calibrate_show_colors.py "
                        "--events-log")
    p.add_argument("--output", required=True, type=Path,
                   help="output JSON in the same shape as show_colors.json")
    p.add_argument("--roi-cx", type=int, default=None,
                   help="ROI centre x in video pixels")
    p.add_argument("--roi-cy", type=int, default=None,
                   help="ROI centre y in video pixels")
    p.add_argument("--roi-half", type=int, default=60,
                   help="ROI half-width in video pixels (default 60)")
    p.add_argument("--show-duration", type=float, default=90.0,
                   help="how many seconds of frames to extract per show "
                        "(default 90, matches calibrate_show_colors.py)")
    p.add_argument("--solid-sample", type=float, default=5.0,
                   help="how many seconds of frames to average for each "
                        "solid (default 5, matches calibrate_show_colors.py)")
    p.add_argument("--solid-hold", type=float, default=12.0,
                   help="seconds the calibration script waited after each "
                        "solid send before sampling (default 12)")
    p.add_argument("--offset", type=float, default=None,
                   help="override the script-to-video timeline offset, "
                        "in seconds (video_t = script_t + offset). Use "
                        "this when the WB-cal Arctic-White auto-detect "
                        "fails — e.g. because the fixture was already "
                        "white when the video recording started, so "
                        "there's no brightness step to detect.")
    args = p.parse_args()

    if not args.video.exists():
        print(f"error: video not found: {args.video}", file=sys.stderr)
        return 1
    if not args.events.exists():
        print(f"error: events log not found: {args.events}", file=sys.stderr)
        return 1

    events = load_events(args.events)
    if not events:
        print("error: events log is empty", file=sys.stderr)
        return 1
    print(f">>> loaded {len(events)} events from {args.events}")

    if args.roi_cx is not None and args.roi_cy is not None:
        roi = Roi(cx=args.roi_cx, cy=args.roi_cy, half=args.roi_half)
        print(f"    using ROI (cx={roi.cx}, cy={roi.cy}, "
              f"half={roi.half})")
    else:
        roi = select_roi_from_video(args.video, half=args.roi_half)

    print(f">>> walking video frames ...")
    fps, video_samples = walk_video(args.video, roi)

    # Determine the script-to-video timeline offset.
    # video_t = script_t + offset (where script_t is monotonic).
    flash_t_video = None
    flash_t_script = None
    if args.offset is not None:
        # Caller supplied an explicit offset relative to script
        # run-start (which has script_t = events[0]["monotonic"]).
        run_start_event = next(
            (e for e in events if e.get("kind") == "run-start"), events[0])
        flash_t_script = run_start_event["monotonic"]
        flash_t_video = args.offset
        offset = flash_t_video - flash_t_script
        print(f">>> using explicit --offset {args.offset:.3f}s "
              f"(video t={args.offset:.3f}s = script run-start)")
    else:
        flash_t_video = find_sync_flash(video_samples, fps_hint=fps)
        if flash_t_video is None:
            print("error: could not find sync flash in video; pass "
                  "--offset N to override (video t in seconds where "
                  "the calibration's run-start fell). check ROI / "
                  "video / start of recording.", file=sys.stderr)
            return 1
        print(f">>> sync flash found at video t = {flash_t_video:.3f}s")
        wb_cal_event = next(
            (e for e in events if e.get("kind") == "wb-cal"), None)
        if wb_cal_event is None:
            print("error: no wb-cal event in events log; was "
                  "--events-log passed to calibrate_show_colors.py?",
                  file=sys.stderr)
            return 1
        flash_t_script = wb_cal_event["monotonic"]
        offset = flash_t_video - flash_t_script
        print(f">>> timeline offset: video_t = script_t + {offset:.3f}s "
              f"(video started {-offset:+.3f}s relative to script start)")

    def script_to_video_t(script_monotonic: float) -> float:
        return script_monotonic + offset

    def video_t_to_index(t: float) -> int:
        # Convert video time to nearest sample index (samples are
        # spaced 1/fps apart by construction).
        return max(0, min(len(video_samples) - 1, int(round(t * fps))))

    # Build the output in the same shape as show_colors.json.
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_video": str(args.video),
        "source_events": str(args.events),
        "video_fps": fps,
        "video_frames": len(video_samples),
        "roi": {"cx": roi.cx, "cy": roi.cy, "half": roi.half,
                "xywh": list(roi.xywh)},
        "sync_flash_video_t": flash_t_video,
        "sync_flash_script_t": flash_t_script,
        "video_to_script_offset_s": offset,
        "ambient_rgb": None,
        "solids": {},
        "shows": {},
    }

    # ---- Ambient: average frames in [hold .. hold+sample] after the
    # ambient (Standby) event. Matches what the live tool did.
    ambient_evt = next((e for e in events if e.get("kind") == "ambient"),
                      None)
    if ambient_evt:
        t0 = script_to_video_t(ambient_evt["monotonic"]) + args.solid_hold
        t1 = t0 + args.solid_sample
        i0, i1 = video_t_to_index(t0), video_t_to_index(t1)
        if i1 > i0:
            arr = np.array([rgb for _, rgb in video_samples[i0:i1]],
                          dtype=np.float64)
            r, g, b = arr.mean(axis=0)
            result["ambient_rgb"] = [int(round(r)), int(round(g)),
                                     int(round(b))]
            print(f">>> ambient RGB (post-process) = "
                  f"{result['ambient_rgb']}")

    # ---- Solids: same recipe.
    for evt in events:
        if evt.get("kind") != "solid":
            continue
        name = evt["label"]
        t0 = script_to_video_t(evt["monotonic"]) + args.solid_hold
        t1 = t0 + args.solid_sample
        i0, i1 = video_t_to_index(t0), video_t_to_index(t1)
        if i1 > i0:
            arr = np.array([rgb for _, rgb in video_samples[i0:i1]],
                          dtype=np.float64)
            r, g, b = arr.mean(axis=0)
            result["solids"][name] = [int(round(r)), int(round(g)),
                                      int(round(b))]
            print(f"  solid {name:22s}: {result['solids'][name]}")

    # ---- Shows: extract show_duration seconds from each show event.
    # t_ms is relative to the byte send (matches sample_show()).
    for evt in events:
        if evt.get("kind") != "show":
            continue
        name = evt["label"]
        t_send_video = script_to_video_t(evt["monotonic"])
        t_end_video = t_send_video + args.show_duration
        i0, i1 = video_t_to_index(t_send_video), video_t_to_index(t_end_video)
        samples_out = []
        for vt, rgb in video_samples[i0:i1]:
            t_rel_ms = int(round((vt - t_send_video) * 1000))
            samples_out.append({"t_ms": t_rel_ms, "rgb": list(rgb)})
        result["shows"][name] = samples_out
        print(f"  show  {name:22s}: {len(samples_out)} samples "
              f"(video t={t_send_video:.1f}..{t_end_video:.1f}s)")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(f"\n>>> wrote {args.output} "
          f"({args.output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
