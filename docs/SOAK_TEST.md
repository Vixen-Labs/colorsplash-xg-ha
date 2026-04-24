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
| Start time (local) | 2026-04-20 21:18 PDT |
| End time (local) | 2026-04-23 21:29 PDT |
| Firmware commit hash | `bf7de66` (PR #44) |
| Bridge location | Indoor — final install spot |
| Controller location | Pool equipment pad |
| Approx signal strength | −83 dBm at end of run (still above the −85 repeater threshold) |
| Capture file | `captures/soak-2026-04-20.log` (gitignored) |
| Notes | Normal HA-side pool usage during the window — no automation changes, no manual intervention with ESP32 or controller. |

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

Generated with `python3 tools/soak_report.py captures/soak-2026-04-20.log`:

## Soak test results

- **Wall time covered:** 72h 10m 53s
- **First event:** 2026-04-20 21:18:44
- **Last event:** 2026-04-23 21:29:38

### Connectivity
- Disconnect events observed: **0**
- Reconnect events observed: **0**
- Failed connect attempts (backoff-counted): **0**
- Watchdog-triggered reboots: **0**

- **Uptime:** 100.000% (no disconnects observed across the run)

### Command activity
- Bytes sent: **28**
- Indication echoes received: **28**

| Byte | Count |
|---:|---:|
| 0x00 | 5 |
| 0x02 | 1 |
| 0x04 | 5 |
| 0x08 | 1 |
| 0x0a | 6 |
| 0x0b | 4 |
| 0x0c | 2 |
| 0x0d | 2 |
| 0x0e | 2 |

### Acceptance check (#13)
- [x] ≥72 h wall-time coverage
- [x] No watchdog reboots
- [x] ≥99% connectivity uptime

## Deviations / notes

**Zero disconnects across 72 hours.** The watchdog backoff and
reboot paths in `colorsplash_xg.cpp` never fired — they're latent
fail-safes. The 1:1 send/echo ratio (28/28) means every command
the user issued during the window was both transmitted and
confirmed by the controller at the BLE layer.

**End-of-run RSSI −83 dBm** is significantly weaker than the −56
to −66 dBm we saw during the #12 10-trial watchdog test. The ESP
was in a more favourable location during that test; the final
indoor install spot is at the edge of what `docs/PLAN.md` §Named
risks #2 flagged as the repeater threshold. **Despite the marginal
signal, the link stayed healthy for 72 continuous hours.** This
is strong evidence the current placement is viable without a BLE
proxy — issue #42 (indoor-range investigation) can be closed
without further work.

**Command-mix observations:** the user exercised a broad subset of
opcodes during the window — 5 solids (including the new Miami Pink
`0x0c` via button entity), 2 shows (Super Nova `0x02`, Tidal Wave
`0x04`), plus Standby / Lock / Return. No unexpected opcodes
appeared in the byte histogram; the protocol table in
`docs/PROTOCOL.md` is complete as-is.
