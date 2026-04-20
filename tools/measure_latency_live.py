#!/usr/bin/env python3
"""Measure ColorSplash XG fixture visual-transition latency in real time.

Opens the Mac's FaceTime camera (or another cv2-openable video source),
runs a BLE sweep against the real controller via bleak, and for each
command written, tracks brightness samples from the camera to infer:

  - onset_s : time from write to the start of the fixture's blackout
  - nadir_s : time to the minimum brightness within the measurement window
  - return_s: time the brightness first recovers to near-baseline
  - total_s : time the brightness is stably near or above baseline for
              >= settle_window seconds (i.e. the full visible transition)

All per-command measurements print after each transition so you can sanity
check in real time. A summary table lands at the end.

Usage (from the repo root, after `source .venv/bin/activate`):
    python tools/measure_latency_live.py --sequence sweep
    python tools/measure_latency_live.py --sequence "blue,red,nova,standby"
    python tools/measure_latency_live.py --camera 0 --sequence sweep

macOS will prompt for Camera permission the first time. Approve in the
terminal app's Settings → Privacy & Security → Camera if it doesn't pop.

Requires opencv-python, numpy, bleak (see requirements.txt + comments
in tools/cli.py).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cli import (  # noqa: E402
    BleakClient,  # noqa: F401 -- re-exported from cli for its lazy import
    COMMAND_CHAR_UUID,
    EFFECT_TABLE,
    SWEEP_EFFECTS,
    _connect,
    _make_indication_queue,
    _require_bleak,
    _setup_logging,
    _subscribe,
    _log,
    parse_effect,
)


# --- measurement parameters ---------------------------------------------

WINDOW_S = 20.0  # cap per-command observation at this many seconds
PRE_WINDOW_S = 2.0  # sample this long BEFORE each write to set baseline
SETTLE_WINDOW_S = 2.0  # brightness must stay near a value for this long to be "stable"
BRIGHTNESS_ONSET_DELTA = 15.0  # raw V-channel drop required to declare onset
STABLE_BAND = 10.0  # ±V units that count as "same" brightness for settling
RETURN_THRESH_FRAC = 0.85  # brightness >= this * baseline counts as "returned"

# Camera frame sample rate: run as fast as the camera gives us, which is
# typically 30 fps. We downsample to this many per-second measurements for
# the stability heuristic so noise at higher rates doesn't matter.
SAMPLE_HZ_TARGET = 10.0


@dataclass
class Sample:
    t: float  # monotonic seconds since tool start
    v: float  # mean V-channel brightness (0..255)


@dataclass
class Measurement:
    byte: int
    name: str
    baseline: float
    nadir_v: float
    onset_s: float | None
    nadir_s: float | None
    return_s: float | None
    total_s: float | None


class CameraWatcher:
    """Async wrapper around a cv2 camera producing brightness samples."""

    def __init__(self, cam_index: int):
        self.cam_index = cam_index
        self.cap: cv2.VideoCapture | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.samples: deque[Sample] = deque(maxlen=20_000)

    def open(self) -> None:
        self.cap = cv2.VideoCapture(self.cam_index)
        if not self.cap.isOpened():
            raise RuntimeError(
                f"could not open camera {self.cam_index}. On macOS, grant the "
                "terminal Camera permission in System Settings → Privacy."
            )
        # Warm up: discard the first handful of frames.
        for _ in range(5):
            self.cap.read()
        _log("cam.open", index=self.cam_index,
             w=int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
             h=int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
             fps=int(self.cap.get(cv2.CAP_PROP_FPS) or 0))

    async def run(self) -> None:
        assert self.cap is not None
        interval = 1.0 / SAMPLE_HZ_TARGET
        last_sample = 0.0
        t0 = time.monotonic()
        while not self._stop.is_set():
            # cv2.read is blocking — offload.
            ret, frame = await asyncio.to_thread(self.cap.read)
            if not ret:
                await asyncio.sleep(0.05)
                continue
            now = time.monotonic() - t0
            if now - last_sample < interval:
                continue
            last_sample = now
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            v = float(hsv[:, :, 2].mean())
            self.samples.append(Sample(t=now, v=v))

    async def start(self) -> None:
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
        if self.cap:
            self.cap.release()

    def samples_between(self, t_start: float, t_end: float) -> list[Sample]:
        # Copy to snapshot — deque append may happen concurrently.
        snap = list(self.samples)
        return [s for s in snap if t_start <= s.t <= t_end]


# --- analysis ----------------------------------------------------------


def analyze(
    samples_pre: list[Sample],
    samples_post: list[Sample],
    write_monotonic: float,
) -> Measurement:
    """Compute per-command latency breakdown from pre/post samples."""
    baseline = float(np.mean([s.v for s in samples_pre])) if samples_pre else 0.0

    if not samples_post:
        return Measurement(
            byte=-1, name="", baseline=baseline,
            nadir_v=float("nan"),
            onset_s=None, nadir_s=None, return_s=None, total_s=None,
        )

    t = np.array([s.t - write_monotonic for s in samples_post])
    v = np.array([s.v for s in samples_post])

    # Onset: first sample where v drops by BRIGHTNESS_ONSET_DELTA below baseline.
    below = np.where(v <= baseline - BRIGHTNESS_ONSET_DELTA)[0]
    onset_s = float(t[below[0]]) if below.size else None

    # Nadir: global min in window.
    nadir_idx = int(np.argmin(v))
    nadir_s = float(t[nadir_idx])
    nadir_v = float(v[nadir_idx])

    # Return: first sample after nadir where v >= baseline * RETURN_THRESH_FRAC.
    return_thresh = baseline * RETURN_THRESH_FRAC
    after_nadir = np.where((v >= return_thresh) & (t > t[nadir_idx]))[0]
    return_s = float(t[after_nadir[0]]) if after_nadir.size else None

    # Total / stable: after the nadir, wait for brightness to RECOVER clearly
    # (rise by RECOVERY_DELTA above nadir), then require a SETTLE_WINDOW_S
    # window where samples stay within STABLE_BAND*2.5 of each other. This
    # keeps us from falsely flagging the dark period itself as "stable."
    # Standby (intentionally dark) is a special case: if the samples after
    # nadir stay at or near nadir, the new stable state IS the dark state —
    # accept it as soon as the brightness stops dropping further.
    RECOVERY_DELTA = 15.0
    total_s: float | None = None
    after_nadir_idx = [i for i in range(len(t)) if t[i] >= t[nadir_idx]]
    # Find first recovery: sample where v >= nadir_v + RECOVERY_DELTA.
    recovery_idx = next(
        (i for i in after_nadir_idx if v[i] >= nadir_v + RECOVERY_DELTA),
        None,
    )
    if recovery_idx is not None:
        # Look for stability starting from recovery_idx onward.
        for i in range(recovery_idx, len(t)):
            t_end = t[i] + SETTLE_WINDOW_S
            window_mask = (t >= t[i]) & (t <= t_end)
            if window_mask.sum() < 3:
                continue
            w = v[window_mask]
            if (w.max() - w.min()) <= (STABLE_BAND * 2.5):
                total_s = float(t[i])
                break
    else:
        # No recovery seen — fixture stays at/near nadir (Standby case).
        # "Stable" is the nadir itself; report when brightness first hit it.
        total_s = nadir_s

    return Measurement(
        byte=-1, name="", baseline=baseline,
        nadir_v=nadir_v,
        onset_s=onset_s, nadir_s=nadir_s,
        return_s=return_s, total_s=total_s,
    )


# --- main flow ---------------------------------------------------------


async def sample_for_duration(cam: CameraWatcher, seconds: float) -> None:
    # Let the camera accumulate samples for this long.
    await asyncio.sleep(seconds)


async def write_and_measure(
    client, byte: int, name: str,
    cam: CameraWatcher,
    indication_queue: asyncio.Queue,
    pre_window: float,
    window: float,
) -> Measurement:
    """Capture pre-samples, write, capture post-samples, analyze."""
    # Pre-window
    t_pre_end = time.monotonic()
    pre_start = t_pre_end - time.monotonic() + (cam.samples[-1].t if cam.samples else 0) - pre_window
    # Simpler: just wait pre_window and slice later using monotonic landmarks.
    pre_marker = cam.samples[-1].t if cam.samples else 0.0
    await asyncio.sleep(pre_window)
    pre_end_marker = cam.samples[-1].t if cam.samples else pre_marker

    # Drain queued indications so we only catch our own echo.
    while not indication_queue.empty():
        try:
            indication_queue.get_nowait()
        except asyncio.QueueEmpty:
            break

    t_write = time.monotonic()
    await client.write_gatt_char(COMMAND_CHAR_UUID, bytes([byte]), response=True)
    # We don't block on indication to measure visual latency from the moment
    # the write bytes go out; log it for reference if it arrives during window.
    write_marker = cam.samples[-1].t if cam.samples else pre_end_marker

    # Observation window
    await asyncio.sleep(window)
    post_end_marker = cam.samples[-1].t if cam.samples else write_marker

    pre_samples = [s for s in list(cam.samples) if pre_marker <= s.t <= pre_end_marker]
    post_samples = [s for s in list(cam.samples) if write_marker <= s.t <= post_end_marker]

    m = analyze(pre_samples, post_samples, write_monotonic=write_marker)
    m.byte = byte
    m.name = name

    _log(
        "measure.done",
        byte=f"0x{byte:02x}",
        name=f'"{name}"',
        baseline=f"{m.baseline:.1f}",
        nadir_v=f"{m.nadir_v:.1f}",
        onset_s=f"{m.onset_s:.2f}" if m.onset_s is not None else "-",
        nadir_s=f"{m.nadir_s:.2f}" if m.nadir_s is not None else "-",
        return_s=f"{m.return_s:.2f}" if m.return_s is not None else "-",
        total_s=f"{m.total_s:.2f}" if m.total_s is not None else "-",
    )
    return m


def resolve_sequence(spec: str) -> list[tuple[int, str]]:
    if spec.lower() == "sweep":
        seq = [(EFFECT_TABLE[n], n.title()) for n in SWEEP_EFFECTS]
        seq.append((EFFECT_TABLE["standby"], "Standby"))
        return seq
    items = [s.strip() for s in spec.split(",") if s.strip()]
    out: list[tuple[int, str]] = []
    for item in items:
        byte = parse_effect(item)
        # Recover canonical name for pretty printing.
        for canonical, b in EFFECT_TABLE.items():
            if b == byte:
                out.append((byte, canonical.title()))
                break
    return out


def format_report(measurements: list[Measurement]) -> str:
    def fmt(v: float | None) -> str:
        return f"{v:.2f}" if v is not None else "-"

    lines = [
        "# Live latency measurements",
        "",
        "| Effect | Byte | Baseline | Nadir V | Onset (s) | Nadir (s) | Return (s) | Total (s) |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for m in measurements:
        lines.append(
            f"| {m.name} | 0x{m.byte:02x} | "
            f"{m.baseline:.1f} | {m.nadir_v:.1f} | "
            f"{fmt(m.onset_s)} | {fmt(m.nadir_s)} | "
            f"{fmt(m.return_s)} | {fmt(m.total_s)} |"
        )

    total_vals = [m.total_s for m in measurements if m.total_s is not None]
    if total_vals:
        lines.extend([
            "",
            f"**Total transition (stable):** min {min(total_vals):.2f} s, "
            f"max {max(total_vals):.2f} s, "
            f"mean {sum(total_vals)/len(total_vals):.2f} s (n={len(total_vals)})",
        ])
    return "\n".join(lines) + "\n"


async def main_async(args: argparse.Namespace) -> int:
    sequence = resolve_sequence(args.sequence)
    if not sequence:
        print("no commands resolved from --sequence", file=sys.stderr)
        return 2

    cam = CameraWatcher(args.camera)
    cam.open()
    await cam.start()

    # Let the user confirm framing by watching baseline settle for a beat.
    _log("cam.warmup", seconds=args.warmup)
    await asyncio.sleep(args.warmup)
    baseline_now = cam.samples[-1].v if cam.samples else 0.0
    _log("cam.warmup.done", current_v=f"{baseline_now:.1f}",
         samples=len(cam.samples))

    _require_bleak()

    client, addr = await _connect(args.address, args.timeout)
    measurements: list[Measurement] = []
    try:
        queue = await _subscribe(client)
        for byte, name in sequence:
            m = await write_and_measure(
                client, byte, name, cam, queue,
                pre_window=args.pre_window,
                window=args.window,
            )
            measurements.append(m)
    finally:
        # Hold the connection briefly so the final command's transition has
        # a chance to finish even though we'd already finished observing.
        await asyncio.sleep(2.0)
        await client.disconnect()
        await cam.stop()

    print()
    print(format_report(measurements))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sequence", default="sweep",
                        help="'sweep' or comma-separated effect names "
                             "(default: sweep)")
    parser.add_argument("--camera", type=int, default=0,
                        help="cv2 camera index (default 0 = built-in)")
    parser.add_argument("--address", help="BLE address override")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--warmup", type=float, default=2.0,
                        help="seconds to let the camera settle before first command")
    parser.add_argument("--pre-window", type=float, default=PRE_WINDOW_S,
                        help=f"seconds of baseline sampling per command (default {PRE_WINDOW_S})")
    parser.add_argument("--window", type=float, default=WINDOW_S,
                        help=f"per-command observation window (default {WINDOW_S})")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    _setup_logging(args.verbose)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
