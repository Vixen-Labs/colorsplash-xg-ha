#!/usr/bin/env python3
"""Characterise the LPL-XG-CTRL-1's per-show colour cycles via the Mac
laptop camera, by driving the bridge through every preset and recording
how the fixture's light reflects off the pool surface.

The output is a JSON file that maps:

  - ambient    → observed RGB with the fixture in Standby
  - solids[N]  → observed RGB for each of the 5 named solid presets
                 (Parisian Blue, Brazilian Red, Arctic White,
                  Miami Pink, New Zealand Green)
  - shows[N]   → list of `{t_ms: int, rgb: [r, g, b]}` samples from
                 ~90 seconds of continuous observation per show

Phase 4b RGB picker: a separate tool consumes this JSON and, given a
target observed RGB, returns the (start_byte, wait_ms) pair whose
sample sits closest in observed-RGB space. The fixture is then driven
to that show + offset and Lock is fired to freeze the colour.

Workflow this tool implements:

  1. Connect to the bridge via aioesphomeapi (uses the bridge's
     `pool_send_byte` user-service — see colorsplash-xg-headless.yaml).
  2. Open the laptop camera (cv2.VideoCapture).
  3. Show a live preview; user clicks a point on the pool to anchor
     the sample ROI (fixed 60×60 box around the click).
  4. Calibration phases run in sequence with operator confirmation
     between each (so the user can re-aim the camera if needed):
       a) Standby — lights off, ambient baseline.
       b) Each of 5 solids — send byte, hold for transition, then
          sample mean RGB over a settle window.
       c) Each of 7 shows — send byte, hold for transition, then
          sample continuously at frame rate for 90 s.
  5. Save everything to a JSON file.

Usage (from repo root, after `source .venv/bin/activate`):

  export COLORSPLASH_API_KEY="<noise PSK from firmware/esphome/secrets.yaml>"
  python tools/calibrate_show_colors.py --output tools/show_colors.json

Optional flags:
  --host            bridge mDNS name or IP (default colorsplash-xg-bridge.local)
  --port            ESPHome native API port (default 6053)
  --camera N        cv2 camera index (default 0 = built-in FaceTime camera)
  --output PATH     output JSON path
  --show-duration   seconds to sample each show (default 90)
  --solid-hold      seconds to wait for solid transition before sampling (default 12)
  --solid-sample    seconds to sample each solid for (default 5)
  --transition-hold seconds to wait after a show start before sampling (default 12)
  --skip-solids     skip the solid-color calibration phase
  --shows ONLY      only run the named shows (comma-separated names)
  --no-standby-end  don't return to Standby at the end
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

try:
    from aioesphomeapi import APIClient, UserService
except ImportError as exc:  # pragma: no cover
    print(f"missing aioesphomeapi: pip install aioesphomeapi  ({exc})",
          file=sys.stderr)
    sys.exit(2)


# ─── Effect byte table — must match docs/PROTOCOL.md ──────────────────

STANDBY_BYTE = 0x00
LOCK_BYTE = 0x0d
RETURN_BYTE = 0x0e

SOLIDS: list[tuple[int, str]] = [
    (0x08, "Parisian Blue"),
    (0x0a, "Brazilian Red"),
    (0x0b, "Arctic White"),
    (0x0c, "Miami Pink"),
    (0x09, "New Zealand Green"),
]

SHOWS: list[tuple[int, str]] = [
    (0x07, "Nova"),
    (0x02, "Super Nova"),
    (0x03, "Northern Lights"),
    (0x04, "Tidal Wave"),
    (0x05, "Patriot Dream"),
    (0x06, "Desert Skies"),
    (0x01, "Peruvian Paradise"),
]


# ─── Bridge connection ────────────────────────────────────────────────


@dataclass
class BridgeClient:
    """Thin wrapper over aioesphomeapi for the calibration use case."""
    api: APIClient
    send_byte_service: UserService

    @classmethod
    async def connect(cls, host: str, port: int, noise_psk: str) -> "BridgeClient":
        api = APIClient(host, port, password="", noise_psk=noise_psk)
        await api.connect(login=True)
        _, services = await api.list_entities_services()
        send_byte_service = next(
            (s for s in services if s.name == "pool_send_byte"), None,
        )
        if send_byte_service is None:
            names = ", ".join(s.name for s in services) or "(none)"
            raise RuntimeError(
                f"bridge does not expose 'pool_send_byte' service. "
                f"available services: {names}. "
                f"Re-flash with the latest colorsplash-xg-headless.yaml."
            )
        return cls(api=api, send_byte_service=send_byte_service)

    async def send_byte(self, byte_value: int) -> None:
        """Send one byte to the controller via the bridge's user-service."""
        await self.api.execute_service(
            self.send_byte_service, {"byte": byte_value},
        )

    async def disconnect(self) -> None:
        await self.api.disconnect()


# ─── Camera + ROI ─────────────────────────────────────────────────────


@dataclass
class Roi:
    """Square sample region centred on (cx, cy) with half-width `half`."""
    cx: int
    cy: int
    half: int = 30

    @property
    def xywh(self) -> tuple[int, int, int, int]:
        x = max(0, self.cx - self.half)
        y = max(0, self.cy - self.half)
        w = self.half * 2
        h = self.half * 2
        return x, y, w, h

    def sample_rgb(self, frame_bgr: np.ndarray) -> tuple[int, int, int]:
        """Return mean (R, G, B) inside the ROI as 0-255 ints."""
        x, y, w, h = self.xywh
        patch = frame_bgr[y : y + h, x : x + w]
        if patch.size == 0:
            return (0, 0, 0)
        # cv2 reads in BGR; flip to RGB.
        b, g, r = patch.mean(axis=(0, 1))
        return (int(round(r)), int(round(g)), int(round(b)))


def select_roi(camera: cv2.VideoCapture, half: int = 30) -> Roi:
    """Show a live preview; user clicks once to set the ROI centre.
    Press Enter to accept, Esc to abort."""
    print("\n>>> Click anywhere on the pool / target surface to set the "
          "sample ROI. Then press Enter to confirm, or Esc to abort.")
    state = {"point": None, "done": False, "abort": False}

    def on_mouse(event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN:
            state["point"] = (x, y)

    win = "Calibrate — click ROI centre, then Enter"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)
    while True:
        ok, frame = camera.read()
        if not ok:
            print("camera read failed", file=sys.stderr)
            sys.exit(1)
        display = frame.copy()
        if state["point"] is not None:
            x, y = state["point"]
            cv2.rectangle(display, (x - half, y - half), (x + half, y + half),
                          (0, 255, 0), 2)
            cv2.putText(display, f"({x}, {y})", (x + half + 5, y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        else:
            cv2.putText(display, "click to place ROI",
                        (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (255, 255, 255), 2)
        cv2.imshow(win, display)
        key = cv2.waitKey(1) & 0xFF
        if key == 13 and state["point"] is not None:  # Enter
            break
        if key == 27:  # Esc
            cv2.destroyWindow(win)
            print("aborted by user", file=sys.stderr)
            sys.exit(1)
    cv2.destroyWindow(win)
    cx, cy = state["point"]
    return Roi(cx=cx, cy=cy, half=half)


def sample_window(camera: cv2.VideoCapture, roi: Roi, duration_s: float,
                  preview: bool = True,
                  label: str = "") -> list[tuple[float, tuple[int, int, int]]]:
    """Pull frames from `camera` for `duration_s` seconds, return list of
    (t_relative_s, (r, g, b)). Optionally show a live preview with the
    ROI overlay so the operator can confirm aim."""
    if preview:
        win = f"Sampling — {label}" if label else "Sampling"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    samples: list[tuple[float, tuple[int, int, int]]] = []
    t0 = time.monotonic()
    deadline = t0 + duration_s
    last_print = t0
    while True:
        now = time.monotonic()
        if now >= deadline:
            break
        ok, frame = camera.read()
        if not ok:
            time.sleep(0.01)
            continue
        rgb = roi.sample_rgb(frame)
        samples.append((now - t0, rgb))
        if preview:
            x, y, w, h = roi.xywh
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(frame, f"{label}  RGB={rgb}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (0, 255, 0), 2)
            remaining = max(0.0, deadline - now)
            cv2.putText(frame, f"{remaining:0.1f}s remaining",
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (255, 255, 255), 2)
            cv2.imshow(win, frame)
            cv2.waitKey(1)
        # CLI heartbeat every second so the user knows we're alive even
        # without preview.
        if now - last_print >= 1.0:
            print(f"  [{label}] t={now - t0:5.1f}s  rgb={rgb}",
                  flush=True)
            last_print = now
    if preview:
        cv2.destroyWindow(win)
    return samples


async def sample_show(bridge: "BridgeClient", camera: cv2.VideoCapture,
                      roi: Roi, byte_val: int, duration_s: float,
                      label: str, preview: bool = True
                      ) -> list[tuple[float, tuple[int, int, int]]]:
    """Send the show's start byte and immediately begin sampling the
    fixture's response. t=0 in the returned samples is the moment the
    BLE write was issued (so t_ms in the JSON corresponds directly to
    wait_ms in the future picker — picker can do
    `lock at t = wait_ms` to recover the colour observed at that point
    in this sample).

    Captures the entire transition envelope: t=0..~0.5s is BLE write
    in flight, t=~0.5..~10s is the fixture's blackout transition,
    then the show actively cycles through its colour sequence.

    Replaces the old "send → sleep transition_hold → sample" pattern
    that was missing the entire transition phase and shifting the
    timeline by 12 s.
    """
    if preview:
        win = f"Sampling — {label}" if label else "Sampling"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    samples: list[tuple[float, tuple[int, int, int]]] = []
    # Anchor t0 at the moment we ISSUE the BLE write. The send_byte
    # await returns when the bridge has accepted the service call;
    # the actual ATT Write Request to the controller follows within
    # 50-200 ms (BLE latency). Close enough for our timing needs —
    # the fixture won't visibly respond for several more seconds.
    t0 = time.monotonic()
    await bridge.send_byte(byte_val)
    deadline = t0 + duration_s
    last_print = t0
    while True:
        now = time.monotonic()
        if now >= deadline:
            break
        ok, frame = camera.read()
        if not ok:
            await asyncio.sleep(0.005)
            continue
        rgb = roi.sample_rgb(frame)
        samples.append((now - t0, rgb))
        if preview:
            x, y, w, h = roi.xywh
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(frame, f"{label}  RGB={rgb}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (0, 255, 0), 2)
            remaining = max(0.0, deadline - now)
            cv2.putText(frame, f"{remaining:0.1f}s remaining",
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (255, 255, 255), 2)
            cv2.imshow(win, frame)
            cv2.waitKey(1)
        if now - last_print >= 1.0:
            print(f"  [{label}] t={now - t0:5.1f}s  rgb={rgb}",
                  flush=True)
            last_print = now
    if preview:
        cv2.destroyWindow(win)
    return samples


def mean_rgb(samples: list[tuple[float, tuple[int, int, int]]]
             ) -> tuple[int, int, int]:
    if not samples:
        return (0, 0, 0)
    arr = np.array([s[1] for s in samples], dtype=np.float64)
    r, g, b = arr.mean(axis=0)
    return (int(round(r)), int(round(g)), int(round(b)))


# ─── Calibration sequence ─────────────────────────────────────────────


@dataclass
class CalibrationResult:
    timestamp: str
    bridge_host: str
    roi: dict
    ambient_rgb: Optional[tuple[int, int, int]] = None
    solids: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    shows: dict[str, list[dict]] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "bridge_host": self.bridge_host,
            "roi": self.roi,
            "ambient_rgb": list(self.ambient_rgb) if self.ambient_rgb else None,
            "solids": {
                name: list(rgb) for name, rgb in self.solids.items()
            },
            "shows": self.shows,
        }


async def run_calibration(args: argparse.Namespace) -> int:
    noise_psk = os.environ.get("COLORSPLASH_API_KEY") or args.api_key
    if not noise_psk:
        print("error: pass --api-key or set COLORSPLASH_API_KEY env var",
              file=sys.stderr)
        return 2

    print(f">>> connecting to {args.host}:{args.port} ...")
    bridge = await BridgeClient.connect(args.host, args.port, noise_psk)
    print(f"    connected; pool_send_byte service is reachable.")

    camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        print(f"error: cv2 could not open camera index {args.camera}",
              file=sys.stderr)
        await bridge.disconnect()
        return 1

    try:
        if args.roi_cx is not None and args.roi_cy is not None:
            roi = Roi(cx=args.roi_cx, cy=args.roi_cy, half=args.roi_half)
            print(f"    using saved ROI centre=({roi.cx},{roi.cy}) "
                  f"half={roi.half} → xywh={roi.xywh} "
                  f"(skipping click prompt)")
        else:
            roi = select_roi(camera, half=args.roi_half)
            print(f"    ROI set to centre=({roi.cx},{roi.cy}) "
                  f"half={roi.half} → xywh={roi.xywh}")
            print(f"    (re-use without re-clicking next time: "
                  f"--roi-cx {roi.cx} --roi-cy {roi.cy} "
                  f"--roi-half {roi.half})")

        result = CalibrationResult(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            bridge_host=args.host,
            roi={"cx": roi.cx, "cy": roi.cy, "half": roi.half,
                 "xywh": list(roi.xywh)},
        )

        def wait_or_skip(label: str) -> None:
            if args.no_prompt:
                print(f"    [no-prompt mode: continuing into {label}]")
                return
            input("    Press Enter when ready ...")

        # ---- Camera white-balance calibration ----
        # Drive the fixture to Arctic White, give the camera time to
        # adapt to that reference, then lock the auto-WB / autofocus /
        # auto-exposure loops so they can't drift during the rest of
        # the run. If we skipped this, every solid + show colour would
        # shift the camera's WB target and wash out subsequent
        # readings (Brazilian Red came in muted in the un-locked run
        # because the camera had adapted to Parisian Blue first).
        if not args.skip_wb_cal:
            print("\n>>> WB calibration: driving Arctic White, "
                  f"holding {args.wb_settle:.1f}s for camera to adapt.")
            await bridge.send_byte(0x0b)  # Arctic White
            await asyncio.sleep(args.wb_settle)
            # cv2 returns False for properties the AVFoundation backend
            # doesn't support; we attempt and log each outcome and
            # proceed regardless. The 0.25 magic value for
            # AUTO_EXPOSURE is the AVFoundation convention for
            # "manual exposure mode" (locks the current value).
            cam_props = [
                ("AUTO_WB", cv2.CAP_PROP_AUTO_WB, 0),
                ("AUTOFOCUS", cv2.CAP_PROP_AUTOFOCUS, 0),
                ("AUTO_EXPOSURE", cv2.CAP_PROP_AUTO_EXPOSURE, 0.25),
            ]
            for name, prop, value in cam_props:
                ok = camera.set(prop, value)
                readback = camera.get(prop)
                print(f"    camera.{name}: set={value} → "
                      f"ok={ok} readback={readback}")
            print(f"    auto loops locked at the white-adapted state.")

        # ---- Phase A: Standby (ambient baseline) ----
        if not args.skip_ambient:
            print("\n>>> Phase A: Standby — lights off, sampling ambient.")
            wait_or_skip("Phase A")
            await bridge.send_byte(STANDBY_BYTE)
            print(f"    sent Standby (0x{STANDBY_BYTE:02x}); "
                  f"holding {args.solid_hold:.1f}s for fixture to dim")
            await asyncio.sleep(args.solid_hold)
            samples = sample_window(camera, roi, args.solid_sample,
                                    label="Ambient")
            result.ambient_rgb = mean_rgb(samples)
            print(f"    ambient RGB = {result.ambient_rgb}")

        # ---- Phase B: Solids ----
        if not args.skip_solids:
            print("\n>>> Phase B: 5 solid colours.")
            wait_or_skip("Phase B")
            for byte_val, name in SOLIDS:
                print(f"\n  -- {name} (0x{byte_val:02x}) --")
                await bridge.send_byte(byte_val)
                print(f"     sent; holding {args.solid_hold:.1f}s")
                await asyncio.sleep(args.solid_hold)
                samples = sample_window(camera, roi, args.solid_sample,
                                        label=name)
                rgb = mean_rgb(samples)
                result.solids[name] = rgb
                print(f"     observed RGB = {rgb}")

        # ---- Phase C: Shows ----
        chosen_shows = SHOWS
        if args.shows:
            wanted = {n.strip().lower() for n in args.shows.split(",")}
            chosen_shows = [s for s in SHOWS if s[1].lower() in wanted]
            if not chosen_shows:
                print(f"error: no shows matched '{args.shows}'",
                      file=sys.stderr)
                return 1

        print("\n>>> Phase C: Shows.")
        wait_or_skip("Phase C")
        for byte_val, name in chosen_shows:
            print(f"\n  -- {name} (0x{byte_val:02x}) — sending start "
                  f"byte and sampling for {args.show_duration:.0f}s "
                  "from t=0 --")
            samples = await sample_show(
                bridge, camera, roi, byte_val,
                args.show_duration, label=name,
            )
            result.shows[name] = [
                {"t_ms": int(round(t * 1000)), "rgb": list(rgb)}
                for t, rgb in samples
            ]
            print(f"     captured {len(samples)} samples")
            # Brief pause between shows so the fixture has a moment
            # to react to the next start byte from a known state
            # rather than mid-cycle. 2 s is enough for the BLE link
            # to settle without making the run drag.
            await asyncio.sleep(2.0)

        # ---- Cleanup: return to Standby unless suppressed ----
        if not args.no_standby_end:
            print("\n>>> Returning to Standby.")
            await bridge.send_byte(STANDBY_BYTE)

        # ---- Persist ----
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result.to_json(), indent=2))
        print(f"\n>>> wrote {out_path} ({out_path.stat().st_size} bytes)")
        return 0

    finally:
        camera.release()
        cv2.destroyAllWindows()
        await bridge.disconnect()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", default="colorsplash-xg-bridge.local")
    p.add_argument("--port", type=int, default=6053)
    p.add_argument("--api-key", default=None,
                   help="ESPHome API encryption key (Noise PSK). "
                        "Falls back to env var COLORSPLASH_API_KEY.")
    p.add_argument("--camera", type=int, default=0,
                   help="cv2 camera index (default 0)")
    p.add_argument("--output", default="tools/show_colors.json")
    p.add_argument("--roi-half", type=int, default=30,
                   help="half-width of the sample ROI in pixels")
    p.add_argument("--roi-cx", type=int, default=None,
                   help="ROI centre x (skip the click prompt). "
                        "Useful at night: set ROI during dusk, then "
                        "re-run with these flags after dark.")
    p.add_argument("--roi-cy", type=int, default=None,
                   help="ROI centre y (paired with --roi-cx)")
    p.add_argument("--show-duration", type=float, default=90.0)
    p.add_argument("--solid-hold", type=float, default=12.0)
    p.add_argument("--solid-sample", type=float, default=5.0)
    p.add_argument("--transition-hold", type=float, default=12.0)
    p.add_argument("--skip-ambient", action="store_true")
    p.add_argument("--skip-solids", action="store_true")
    p.add_argument("--shows", default=None,
                   help="comma-separated subset (case-insensitive) — "
                        "default runs all 7")
    p.add_argument("--no-standby-end", action="store_true")
    p.add_argument("--no-prompt", action="store_true",
                   help="skip the 'Press Enter when ready' between "
                        "phases — required for non-interactive runs. "
                        "Pair with --roi-cx/--roi-cy so the click "
                        "step is also skipped.")
    p.add_argument("--skip-wb-cal", action="store_true",
                   help="skip the Arctic-White camera white-balance "
                        "calibration step (rarely useful — only for "
                        "debugging the script itself)")
    p.add_argument("--wb-settle", type=float, default=10.0,
                   help="seconds to wait after Arctic White is sent "
                        "before locking the camera's auto loops")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    # Make Ctrl-C terminate cleanly even mid-asyncio.
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(run_calibration(args))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    finally:
        loop.close()


if __name__ == "__main__":
    sys.exit(main())
