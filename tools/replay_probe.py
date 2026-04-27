#!/usr/bin/env python3
"""Drive the bridge through N back-to-back replays of a single show
or solid colour, sampling a camera throughout to capture the timing
envelope of each replay. Used to measure replay-to-replay timing
consistency of the controller's transition envelope per command —
i.e. is the AC-interrupt-pattern dispatch deterministic, or does it
drift?

For timing analysis we don't need colorimetric accuracy; the FaceTime
camera (or any cv2-openable camera) is fine. The metric we care
about is when brightness drops (transition starts) and rises (new
colour appears) — auto-WB drift doesn't change those events.

Output JSON has the same shape as
`tools/extract_colors_from_video.py`'s output, with each replay as
a separate "<show> #N" entry, so
`tools/analyze_replay_consistency.py` can consume it directly
without any post-process video extraction step.

Usage:
    export COLORSPLASH_API_KEY="$(cat /tmp/colorsplash-key)"
    python tools/replay_probe.py --show "Patriot Dream" --count 5

    # skip the click prompt with saved ROI:
    python tools/replay_probe.py --show "Patriot Dream" \\
        --roi-cx 640 --roi-cy 360 --roi-half 60

Timing per replay (defaults):
    30 s Standby reset → 60 s show observation = 90 s per replay
    5 replays × 90 s + start/end ≈ 8 min total
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from aioesphomeapi import APIClient, UserService
except ImportError as exc:
    print(f"missing aioesphomeapi: pip install aioesphomeapi  ({exc})",
          file=sys.stderr)
    sys.exit(2)

try:
    import cv2
    import numpy as np
except ImportError as exc:
    print(f"missing cv2 / numpy: pip install opencv-python numpy  "
          f"({exc})", file=sys.stderr)
    sys.exit(2)


STANDBY_BYTE = 0x00

NAME_TO_BYTE = {
    # Solids
    "Parisian Blue": 0x08,
    "Brazilian Red": 0x0a,
    "Arctic White": 0x0b,
    "Miami Pink": 0x0c,
    "New Zealand Green": 0x09,
    # Shows
    "Nova": 0x07,
    "Super Nova": 0x02,
    "Northern Lights": 0x03,
    "Tidal Wave": 0x04,
    "Patriot Dream": 0x05,
    "Desert Skies": 0x06,
    "Peruvian Paradise": 0x01,
    # Controls
    "Lock": 0x0d,
    "Return": 0x0e,
}


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


def select_roi(camera: cv2.VideoCapture, half: int = 60) -> Roi:
    print("\n>>> Click the lit pool spot to set the ROI centre, then "
          "press Enter. Esc to abort.")
    state = {"point": None}

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN:
            state["point"] = (x, y)

    win = "Replay probe — click ROI centre"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)
    while True:
        ok, frame = camera.read()
        if not ok:
            print("camera read failed", file=sys.stderr)
            sys.exit(1)
        d = frame.copy()
        if state["point"]:
            x, y = state["point"]
            cv2.rectangle(d, (x - half, y - half),
                          (x + half, y + half), (0, 255, 0), 2)
            cv2.putText(d, f"({x},{y})", (x + half + 5, y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        else:
            cv2.putText(d, "click to place ROI",
                        (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (255, 255, 255), 2)
        cv2.imshow(win, d)
        k = cv2.waitKey(1) & 0xFF
        if k == 13 and state["point"]:
            break
        if k == 27:
            cv2.destroyWindow(win)
            sys.exit(1)
    cv2.destroyWindow(win)
    cx, cy = state["point"]
    print(f"    ROI = ({cx},{cy}, half={half})")
    return Roi(cx=cx, cy=cy, half=half)


def sample_frames(camera: cv2.VideoCapture, roi: Roi,
                  duration_s: float, label: str
                  ) -> list[tuple[float, tuple[int, int, int]]]:
    """Pull frames for `duration_s` seconds. t in returned tuples is
    monotonic-relative-to-call. Caller anchors to the byte send."""
    samples = []
    t0 = time.monotonic()
    deadline = t0 + duration_s
    last_print = t0
    while time.monotonic() < deadline:
        ok, frame = camera.read()
        if not ok:
            time.sleep(0.005)
            continue
        rgb = roi.sample_rgb(frame)
        now = time.monotonic()
        samples.append((now - t0, rgb))
        if now - last_print >= 1.0:
            print(f"  [{label}] t={now - t0:5.1f}s  rgb={rgb}",
                  flush=True)
            last_print = now
    return samples


async def connect_bridge(host: str, port: int, noise_psk: str
                         ) -> tuple[APIClient, UserService]:
    api = APIClient(host, port, password="", noise_psk=noise_psk)
    await api.connect(login=True)
    _, services = await api.list_entities_services()
    svc = next((s for s in services if s.name == "pool_send_byte"), None)
    if svc is None:
        names = ", ".join(s.name for s in services) or "(none)"
        raise RuntimeError(
            f"bridge does not expose pool_send_byte; available: {names}",
        )
    return api, svc


def write_event(events_file, byte_val: int | None, kind: str, label: str,
                ) -> float:
    t_send = time.monotonic()
    if events_file is not None:
        e = {
            "wall_clock": datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"),
            "monotonic": t_send,
            "kind": kind,
            "label": label,
        }
        if byte_val is not None:
            e["byte"] = int(byte_val)
            e["byte_hex"] = f"0x{byte_val:02x}"
        events_file.write(json.dumps(e) + "\n")
        events_file.flush()
    return t_send


async def sample_one_replay(api: APIClient, svc: UserService,
                            camera: cv2.VideoCapture, roi: Roi,
                            byte_val: int, observe_s: float,
                            label: str, events_file
                            ) -> list[tuple[float, tuple[int, int, int]]]:
    """Send the byte (anchoring t=0), then sample frames for
    `observe_s` seconds. Returns samples with t relative to the
    byte send."""
    write_event(events_file, byte_val, "show", label)
    t0 = time.monotonic()
    await api.execute_service(svc, {"byte": byte_val})
    samples: list[tuple[float, tuple[int, int, int]]] = []
    deadline = t0 + observe_s
    last_print = t0
    while time.monotonic() < deadline:
        ok, frame = camera.read()
        if not ok:
            await asyncio.sleep(0.005)
            continue
        rgb = roi.sample_rgb(frame)
        now = time.monotonic()
        samples.append((now - t0, rgb))
        if now - last_print >= 1.0:
            print(f"  [{label}] t={now - t0:5.1f}s  rgb={rgb}",
                  flush=True)
            last_print = now
    return samples


async def main_async(args: argparse.Namespace) -> int:
    noise_psk = os.environ.get("COLORSPLASH_API_KEY") or args.api_key
    if not noise_psk:
        print("error: pass --api-key or set COLORSPLASH_API_KEY env var",
              file=sys.stderr)
        return 2

    if args.show not in NAME_TO_BYTE:
        names = ", ".join(NAME_TO_BYTE)
        print(f"error: unknown --show '{args.show}'. options: {names}",
              file=sys.stderr)
        return 1

    target_byte = NAME_TO_BYTE[args.show]
    events_path = Path(args.events_log) if args.events_log else None
    if events_path:
        events_path.parent.mkdir(parents=True, exist_ok=True)

    print(f">>> connecting to {args.host}:{args.port} ...")
    api, svc = await connect_bridge(args.host, args.port, noise_psk)

    camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        print(f"error: cv2 cannot open camera index {args.camera}",
              file=sys.stderr)
        await api.disconnect()
        return 1

    events_file = open(events_path, "w") if events_path else None

    try:
        if args.roi_cx is not None and args.roi_cy is not None:
            roi = Roi(cx=args.roi_cx, cy=args.roi_cy,
                      half=args.roi_half)
            print(f"    using saved ROI ({roi.cx},{roi.cy},"
                  f"half={roi.half})")
        else:
            roi = select_roi(camera, half=args.roi_half)
            print(f"    re-use next time: --roi-cx {roi.cx} "
                  f"--roi-cy {roi.cy} --roi-half {roi.half}")

        write_event(events_file, None, "run-start",
                    f"replay-probe '{args.show}' × {args.count}")
        print(f"    show: {args.show} (0x{target_byte:02x})")
        print(f"    replays: {args.count}")
        print(f"    reset hold: {args.reset_secs:.0f}s standby")
        print(f"    observe: {args.observe_secs:.0f}s after start")
        total = args.count * (args.reset_secs + args.observe_secs)
        print(f"    estimated runtime: {total:.0f}s ({total/60:.1f} min)")
        print()

        # Sample ambient first (just observe a few seconds before
        # we start driving anything) — used by the analyzer as the
        # baseline brightness for transition detection.
        print(">>> initial Standby + ambient sample ...")
        write_event(events_file, STANDBY_BYTE, "ambient",
                    "initial Standby (run pre-state)")
        await api.execute_service(svc, {"byte": STANDBY_BYTE})
        await asyncio.sleep(args.reset_secs)
        ambient_samples = sample_frames(
            camera, roi, args.ambient_sample, "ambient")
        ambient_arr = np.array(
            [s[1] for s in ambient_samples], dtype=np.float64)
        ambient_rgb = (
            int(round(ambient_arr[:, 0].mean())),
            int(round(ambient_arr[:, 1].mean())),
            int(round(ambient_arr[:, 2].mean())),
        )
        print(f"    ambient RGB = {ambient_rgb}")

        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "show": args.show,
            "byte": target_byte,
            "byte_hex": f"0x{target_byte:02x}",
            "count": args.count,
            "roi": {"cx": roi.cx, "cy": roi.cy, "half": roi.half,
                    "xywh": list(roi.xywh)},
            "camera_index": args.camera,
            "ambient_rgb": list(ambient_rgb),
            "shows": {},
        }

        for i in range(1, args.count + 1):
            label = f"{args.show} #{i}"
            print(f"\n>>> replay {i}/{args.count}: '{label}'")
            samples = await sample_one_replay(
                api, svc, camera, roi, target_byte,
                args.observe_secs, label, events_file,
            )
            result["shows"][label] = [
                {"t_ms": int(round(t * 1000)), "rgb": list(rgb)}
                for t, rgb in samples
            ]
            print(f"    captured {len(samples)} samples")

            if i < args.count:
                print(f"    reset Standby — holding "
                      f"{args.reset_secs:.0f}s ...")
                write_event(events_file, STANDBY_BYTE, "ambient",
                            f"reset before #{i+1}")
                await api.execute_service(svc, {"byte": STANDBY_BYTE})
                await asyncio.sleep(args.reset_secs)

        print("\n>>> end-of-run Standby ...")
        write_event(events_file, STANDBY_BYTE, "end-standby",
                    "end-of-run Standby")
        await api.execute_service(svc, {"byte": STANDBY_BYTE})
        write_event(events_file, None, "run-end",
                    "replay-probe complete")

        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2))
        print(f"\n>>> wrote {out_path} ({out_path.stat().st_size} bytes)")
        return 0
    finally:
        if events_file:
            events_file.close()
        camera.release()
        cv2.destroyAllWindows()
        await api.disconnect()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--show", required=True,
                   help="name of the show or solid to replay")
    p.add_argument("--count", type=int, default=5,
                   help="number of back-to-back replays (default 5)")
    p.add_argument("--reset-secs", type=float, default=30.0,
                   help="seconds to hold Standby between replays "
                        "(default 30)")
    p.add_argument("--observe-secs", type=float, default=60.0,
                   help="seconds to sample after each start byte "
                        "(default 60)")
    p.add_argument("--ambient-sample", type=float, default=3.0,
                   help="seconds to sample after initial Standby "
                        "to establish ambient baseline (default 3)")
    p.add_argument("--camera", type=int, default=0,
                   help="cv2 camera index (default 0 = built-in)")
    p.add_argument("--roi-cx", type=int, default=None)
    p.add_argument("--roi-cy", type=int, default=None)
    p.add_argument("--roi-half", type=int, default=60,
                   help="ROI half-width (default 60 = 120×120 box)")
    p.add_argument("--host", default="colorsplash-xg-bridge.local")
    p.add_argument("--port", type=int, default=6053)
    p.add_argument("--api-key", default=None)
    p.add_argument("--output",
                   default="tools/show_colors_replay.json",
                   help="output JSON path "
                        "(default tools/show_colors_replay.json)")
    p.add_argument("--events-log",
                   default="tools/replay_events.jsonl",
                   help="optional JSONL events log "
                        "(default tools/replay_events.jsonl); "
                        "pass empty string to disable")
    args = p.parse_args()

    if args.events_log == "":
        args.events_log = None

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(main_async(args))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    finally:
        loop.close()


if __name__ == "__main__":
    sys.exit(main())
