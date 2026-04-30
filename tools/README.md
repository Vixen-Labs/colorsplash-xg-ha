# tools/

Helper scripts for the reverse-engineering workflow (Phase 1) plus the soak-test report generator (Phase 2 #13). All target Python 3 and prefer stdlib where practical.

## `capture-session`

Interactive SWEEP_LOG logger that drives an Android HCI snoop capture session end to end: creates the session directory, prompts for each action with a remaining-time countdown, timestamps every entry in UTC millisecond format, and runs `adb bugreport` on exit to extract `btsnoop_hci.log` from the tablet.

```sh
cd captures
../tools/capture-session                 # default suffix: first-pair
../tools/capture-session steady-state    # second pass after bonding
```

See [`docs/CAPTURING.md`](../docs/CAPTURING.md) §3 for the full procedure.

## `decode_sweep.py`

Decodes a capture session's `btsnoop_hci.log` and correlates the ATT Write Requests with the timestamped actions in `SWEEP_LOG.md`. Outputs a markdown report.

```sh
python3 tools/decode_sweep.py captures/2026-04-19-steady-state3 \
  --skew -25200    # Samsung Tab S9 Ultra localtime-as-UTC quirk
```

Also reads Apple PacketLogger btsnoop exports and nRF sniffer pcaps (see CAPTURING.md §8 and §9).

Unit tests: `python3 -m unittest discover -s tests`.

## `cli.py`

Reference BLE client using `bleak`. Drives the real pool-light controller end-to-end, implementing every protocol claim in [`docs/PROTOCOL.md`](../docs/PROTOCOL.md).

```sh
# one-time setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# drive a single tile
python tools/cli.py --effect parisian-blue

# read Device Information Service
python tools/cli.py --info

# cycle all 12 tile effects, then Standby
python tools/cli.py --sweep

# arbitrary byte (Phase 4a probe hatch)
python tools/cli.py --raw 0x08
```

First run on macOS will trigger a Bluetooth permission prompt for the terminal app; approve it. Per PROTOCOL.md, the client holds the BLE connection open for 8 seconds after each write by default so the fixture's visible transition can complete — pass `--hold 0` to disable.

Works on macOS (confirmed). Linux support via BlueZ is expected but not yet verified on this project.

## `measure_latency_live.py`

Real-time fixture transition latency measurement using the Mac's built-in camera (or another cv2 camera index) while a bleak sequence runs against the controller. Prints per-command onset / nadir / return / total-transition seconds live, then a summary table.

```sh
# single-pass full sweep (~5 min, camera must see the fixture)
python tools/measure_latency_live.py --sequence sweep

# short custom sequence
python tools/measure_latency_live.py --sequence "blue,red,standby" --window 15
```

First run on macOS needs Camera permission for the shell / IDE hosting the Python process (System Settings → Privacy & Security → Camera).

Requires `opencv-python` and `numpy` in the venv in addition to the base `requirements.txt` (install with `pip install opencv-python numpy`).

## `observe_fixture.py`

Short-duration camera observation that classifies the fixture as **CYCLING** (a show like Nova/Patriot Dream — colors change frame-to-frame) or **STABLE** (a solid color or Standby — colors hold). Uses a saturation-and-brightness mask to isolate the fixture pixels from pool water / tile / patio in daylight.

```sh
python tools/observe_fixture.py --seconds 15 --sat-threshold 200
```

Used during #33's investigation to confirm test outcomes without relying on human eyeball classification of the pool fixture from across a yard. Same opencv-python + numpy dependencies as the latency tools.

## `measure_latency.py`

Post-hoc analysis of a separately-recorded video (e.g. a QuickTime `.mov` of a sweep). Reads a companion `sweep.log` from `tools/cli.py`, auto-syncs the video's timeline against the log's wall-clock anchor, and emits the same per-command breakdown as the live tool.

```sh
python tools/measure_latency.py captures/YYYY-MM-DD-latency/
```

Useful when the camera can't be running during capture (e.g., you used QuickTime recording via phone or another Mac and brought the file back later). Same opencv-python + numpy dependency as `measure_latency_live.py`.

## `soak_report.py`

Consumes an `esphome logs` capture (plaintext or `.gz`) from the #13 72-hour soak test and emits a markdown summary: reconnect-latency distribution, uptime fraction, command / error counts, watchdog reboot events. Stdlib-only.

```sh
python tools/soak_report.py captures/soak-2026-04-20.log
```

See [`docs/SOAK_TEST.md`](../docs/SOAK_TEST.md) for the full soak procedure. Paste the generated report into that file's Results section before opening the follow-up PR that closes #13.
