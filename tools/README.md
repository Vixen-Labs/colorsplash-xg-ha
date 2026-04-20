# tools/

Three helper scripts for the Phase 1 reverse-engineering workflow.
All target Python 3 and prefer stdlib where practical.

## `capture-session`

Interactive SWEEP_LOG logger that drives an Android HCI snoop capture
session end to end: creates the session directory, prompts for each
action with a remaining-time countdown, timestamps every entry in
UTC millisecond format, and runs `adb bugreport` on exit to extract
`btsnoop_hci.log` from the tablet.

```sh
cd captures
../tools/capture-session                 # default suffix: first-pair
../tools/capture-session steady-state    # second pass after bonding
```

See [`docs/CAPTURING.md`](../docs/CAPTURING.md) §3 for the full
procedure.

## `decode_sweep.py`

Decodes a capture session's `btsnoop_hci.log` and correlates the
ATT Write Requests with the timestamped actions in `SWEEP_LOG.md`.
Outputs a markdown report.

```sh
python3 tools/decode_sweep.py captures/2026-04-19-steady-state3 \
  --skew -25200    # Samsung Tab S9 Ultra localtime-as-UTC quirk
```

Also reads Apple PacketLogger btsnoop exports and nRF sniffer pcaps
(see CAPTURING.md §8 and §9).

Unit tests: `python3 -m unittest discover -s tests`.

## `cli.py`

Reference BLE client using `bleak`. Drives the real pool-light
controller end-to-end, implementing every protocol claim in
[`docs/PROTOCOL.md`](../docs/PROTOCOL.md).

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

First run on macOS will trigger a Bluetooth permission prompt for the
terminal app; approve it. Per PROTOCOL.md, the client holds the BLE
connection open for 8 seconds after each write by default so the
fixture's visible transition can complete — pass `--hold 0` to
disable.

Works on macOS (confirmed). Linux support via BlueZ is expected but
not yet verified on this project.
