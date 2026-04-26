#!/usr/bin/env python3
"""Drive the bridge through N back-to-back replays of a single show
or solid colour, with consistent Standby resets between, while writing
every send to an events log. Used to measure replay-to-replay timing
consistency of the controller's transition envelope per command —
i.e. is the AC-interrupt-pattern dispatch deterministic, or does it
drift?

The script does not sample a camera. Pair with a Final Cut Camera
(or other) recording on the iPhone, with locked WB + exposure.
After the run, post-process the .mov against the events log via
tools/extract_colors_from_video.py + tools/analyze_replay_consistency.py.

Usage:
    export COLORSPLASH_API_KEY="$(cat /tmp/colorsplash-key)"
    python tools/replay_probe.py --show "Patriot Dream" --count 5

Each replay labels its event uniquely ("Patriot Dream #1",
"Patriot Dream #2", …) so the existing extract tool produces one
JSON entry per replay. The analyzer then aggregates them.

Timing per replay (defaults):
    30 s Standby reset → 60 s show observation = 90 s per replay
    5 replays × 90 s + start/end ≈ 8 min total

Suggested workflow:
    1. Start FCP camera recording on iPhone, aimed at the pool.
    2. Run this script.
    3. Stop recording when prompted (script prints
       "RECORDING-CAN-STOP" at the end).
    4. AirDrop .mov to Mac.
    5. Run extract_colors_from_video.py against it + the events log.
    6. Run analyze_replay_consistency.py against the extracted JSON.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from aioesphomeapi import APIClient, UserService
except ImportError as exc:
    print(f"missing aioesphomeapi: pip install aioesphomeapi  ({exc})",
          file=sys.stderr)
    sys.exit(2)


STANDBY_BYTE = 0x00

# Maps human names → byte. Subset (the ones likely to be probed for
# consistency); add more if needed.
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
    events_path = Path(args.events_log)
    events_path.parent.mkdir(parents=True, exist_ok=True)

    print(f">>> connecting to {args.host}:{args.port} ...")
    api, svc = await connect_bridge(args.host, args.port, noise_psk)

    async def send(byte_val: int) -> None:
        await api.execute_service(svc, {"byte": byte_val})

    try:
        with open(events_path, "w") as ef:
            write_event(ef, None, "run-start",
                        f"replay-probe '{args.show}' × {args.count}")
            print(f"    events log: {events_path}")
            print(f"    show: {args.show} (0x{target_byte:02x})")
            print(f"    replays: {args.count}")
            print(f"    reset hold: {args.reset_secs:.0f}s standby")
            print(f"    observe hold: {args.observe_secs:.0f}s after start")
            print(f"    estimated total runtime: "
                  f"{args.count * (args.reset_secs + args.observe_secs):.0f}s "
                  f"({args.count * (args.reset_secs + args.observe_secs) / 60:.1f} min)")
            print()

            # Initial Standby to put fixture in a known starting state.
            print(">>> initial Standby reset ...")
            write_event(ef, STANDBY_BYTE, "ambient",
                        "initial Standby (run pre-state)")
            await send(STANDBY_BYTE)
            await asyncio.sleep(args.reset_secs)

            for i in range(1, args.count + 1):
                label = f"{args.show} #{i}"
                print(f">>> replay {i}/{args.count}: sending "
                      f"'{label}' (0x{target_byte:02x}) ...")
                write_event(ef, target_byte, "show", label)
                await send(target_byte)
                # observe for `observe_secs` to capture full transition
                # + at least one cycle of the show
                await asyncio.sleep(args.observe_secs)

                # Reset for next replay (unless this is the last one).
                if i < args.count:
                    reset_label = f"reset before #{i+1}"
                    print(f"    reset Standby — holding "
                          f"{args.reset_secs:.0f}s ...")
                    write_event(ef, STANDBY_BYTE, "ambient", reset_label)
                    await send(STANDBY_BYTE)
                    await asyncio.sleep(args.reset_secs)

            # End of run — explicit Standby for safety.
            print("\n>>> end-of-run Standby ...")
            write_event(ef, STANDBY_BYTE, "end-standby",
                        "end-of-run Standby")
            await send(STANDBY_BYTE)
            write_event(ef, None, "run-end",
                        "replay-probe complete")

        print()
        print("RECORDING-CAN-STOP — stop the FCP camera recording now.")
        return 0
    finally:
        await api.disconnect()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--show", required=True,
                   help="name of the show or solid to replay (e.g. "
                        "'Patriot Dream' — see NAME_TO_BYTE in source)")
    p.add_argument("--count", type=int, default=5,
                   help="number of back-to-back replays (default 5)")
    p.add_argument("--reset-secs", type=float, default=30.0,
                   help="seconds to hold Standby between replays "
                        "(default 30 — long enough for the fixture to "
                        "fully dim before the next start byte)")
    p.add_argument("--observe-secs", type=float, default=60.0,
                   help="seconds to wait after the start byte before "
                        "the next reset (default 60 — covers transition "
                        "envelope + some show cycle time)")
    p.add_argument("--host", default="colorsplash-xg-bridge.local")
    p.add_argument("--port", type=int, default=6053)
    p.add_argument("--api-key", default=None,
                   help="ESPHome native-API noise PSK; falls back to env "
                        "COLORSPLASH_API_KEY")
    p.add_argument("--events-log", default="tools/replay_events.jsonl",
                   help="JSONL output path (default tools/replay_events.jsonl)")
    args = p.parse_args()

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
