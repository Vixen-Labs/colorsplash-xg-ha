# Phase 2 #13 — 72-hour soak test

Documents the continuous-connection soak test required by issue #13's
acceptance criteria. The run exercises the bridge under normal-use
conditions for ≥72 hours to surface slow bugs (memory leaks, rare
races, thermal effects, cumulative disconnects) that a quick
functional test can't catch.

## How to run

1. Flash the current `phase2/*` or `main` firmware build via OTA.
2. Start an unattended log capture on a machine that can stay
   connected to the LAN for 72 hours:
   ```sh
   mkdir -p captures
   esphome logs firmware/esphome/colorsplash-xg.yaml \
       --device colorsplash-xg.local \
       > captures/soak-$(date +%Y-%m-%d).log 2>&1 &
   disown
   ```
3. Do not manually intervene with the ESP32 or the ColorSplash
   controller during the window. Normal HA-side use (toggling the
   light, picking effects) is expected.
4. After ≥72 hours, stop the log capture and produce the report:
   ```sh
   python tools/soak_report.py captures/soak-YYYY-MM-DD.log
   ```
5. Paste the report into the **Results** section below and open a
   follow-up PR to close #13.

## Run parameters

Fill these in before the soak starts.

| Field | Value |
|---|---|
| Start time (local) | _TBD_ |
| End time (local) | _TBD_ |
| Firmware commit hash | _TBD_ |
| Bridge location | _TBD_ |
| Controller location | _TBD_ |
| Approx line-of-sight distance | _TBD_ |
| Notes | _TBD_ |

## Entities observed during the run

The bridge exposes these diagnostic entities to HA (all from #12 + #13):

- `binary_sensor.pool_ble_connected` — connected state
- `text_sensor.pool_last_ble_error` — most recent BLE error message
- `text_sensor.pool_last_command` — most recent sent byte (e.g. `"nova (0x07)"`)
- `sensor.pool_ble_rssi` — link-layer RSSI, polled every 30 s
- `sensor.pool_command_count` — monotonic total of sent bytes (resets on reboot)
- `sensor.pool_error_count` — monotonic total of BLE failures (resets on reboot)

HA's recorder captures their history over the soak window as a
second data source, complementary to the log capture.

## Acceptance criteria

- [ ] All five diagnostic entities visible in HA
- [ ] ≥72 h of continuous log capture
- [ ] ≥99% connected uptime across the window
- [ ] No manual intervention required
- [ ] No watchdog-triggered reboots

## Results

_Paste the output of `tools/soak_report.py` here after the run._

```
(soak report not yet generated)
```

## Deviations / notes

_Anything surprising during the run — environmental changes, HA
outages, controller resets, etc. Leave empty if nothing to report._
