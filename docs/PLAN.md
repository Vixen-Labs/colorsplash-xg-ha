# ColorSplash XG → ESPHome → Home Assistant — Project Plan

Status: approved 2026-04-18
Branch: `claude/colorsplash-bluetooth-plan-zPafv`

## Goal

Replace the stock J&J ColorSplash XG mobile app with a permanently-online
bridge that:

- Maintains a continuous BLE connection to an LPL-XG-CTRL-1 controller
- Exposes the controller to Home Assistant as a Light (plus diagnostic
  entities) via ESPHome's native API over the LAN
- Presents a local LVGL touchscreen UI that keeps working when HA is down
- Automatically reconnects to the controller after any dropout
- (stretch, time-boxed) explores whether arbitrary RGB is achievable beyond
  the factory 5 colors / 7 shows

## Established facts

| Item | Value |
|------|-------|
| Controller | J&J Electronics LPL-XG-CTRL-1 (Bluetooth) |
| Controller power | 120 VAC, 60 Hz, 400 W max load |
| Fixture | XG pool/spa RGB (preset palette in fixture firmware) |
| Bridge hardware | Waveshare ESP32-S3-Touch-LCD-7 (7" 800×480 RGB parallel, GT911 cap touch, PSRAM, BLE 5) |
| HA location | Same LAN as the ESP32 |
| Install location | Indoor wall near the equipment pad |
| BLE exclusivity | ESP32 owns the link 24/7; phone app cannot connect while ESP32 is connected |
| Capture tools | Android HCI snoop, iOS via macOS PacketLogger, nRF52840 USB dongle (on hand) |

## Confirmed app UI surface

The official ColorSplash XG app exposes exactly these controls (user-confirmed exhaustive; any captured traffic that doesn't map to one of these is a red flag worth investigating):

- **Connect** — opens a sheet, no password/confirmation
- **Disconnect** — closes BLE
- **Standby on/off** — blanks the light; resuming restores the previous color/show (controller maintains state)
- **Lock** — freezes the current color during a show (this is the "Hold" / freeze primitive used by Phase 4b)
- **Return** — semantics unclear; possibly recalls the last Lock-held color. To be determined by the Phase 1 sweep
- **5 solid colors** and **7 shows**

No brightness slider, no show-speed slider, no scheduling, no settings screen, no long-press behaviors. The HA light entity will therefore expose `on/off` + `effect` only (no `brightness`).

## Architecture

```
[J&J LPL-XG-CTRL-1] ──BLE GATT (single client)──► [Waveshare ESP32-S3 7" + LVGL] ──ESPHome native API / LAN──► [Home Assistant]
                                                        │
                                                        └── local 7" touchscreen UI (standalone-capable)
```

## Named risks

1. **Arbitrary RGB is unlikely.** The XG RGB fixture palette lives in the
   fixture's firmware, not the controller. The controller almost certainly
   drives the fixture with timed AC interruption sequences that each select a
   preset color or show. Treated as a time-boxed experiment, not a goal.
2. **BLE range.** Waveshare's on-PCB antenna vs. pool controller through
   walls. If RSSI at the chosen wall spot is worse than about −85 dBm we will
   add a second ESP32 as a BLE proxy closer to the pad.
3. **Phone app stops working** whenever the ESP32 is connected. Accepted.
4. **S3 resource contention.** RGB parallel display + LVGL + BLE + Wi-Fi is a
   lot on one chip. Pin BLE to one core, keep LVGL framebuffers in PSRAM,
   keep the UI redraw modest.
5. **Pairing / encryption.** If the controller uses LE Secure Connections we
   must capture the pairing handshake. The nRF52840 sniffer is how we do
   that; it is on hand.
6. **Legal.** Reverse engineering for interoperability is permitted under
   DMCA §1201. We will not redistribute decompiled APK code.

## Phases

### Phase 0 — Scaffolding (1 issue)

- Repo layout (`docs/`, `firmware/esphome/`, `tools/`, `captures/`,
  `protocol/`)
- `.gitignore` for Python, ESPHome build dirs, captures (pcap, btsnoop)
- Issue / PR templates
- This file

### Phase 1 — Reverse engineering (7 issues)

1. Document Android HCI snoop capture procedure (Developer Options →
   Enable Bluetooth HCI snoop log → reproduce → pull `btsnoop_hci.log`).
2. Pull and decompile the Android APK with jadx; identify the BLE service
   class, service / characteristic UUIDs, packet builders, any framing
   constants. No decompiled code checked in.
3. Set up nRF52840 USB dongle in Wireshark via Nordic's nRF Sniffer for
   Bluetooth LE plugin; confirm captures show the controller's advertisements
   and GATT traffic.
4. Structured capture sweep: a scripted procedure that exercises every app
   action (connect, power on / off, each of the 5 solid colors, each of the 7
   shows, any brightness / speed sliders, disconnect) with timestamps, so
   each packet can be correlated back to a UI action.
5. iOS cross-check: use macOS PacketLogger to capture the same sweep from
   the iOS app, confirm both apps speak the same protocol, record any
   version-gated differences.
6. Decode the protocol into `docs/PROTOCOL.md`: service / characteristic
   UUIDs, packet framing, opcodes, parameters, any handshake or auth, any
   checksum, known unknowns.
7. Python `bleak` reference client in `tools/cli.py` that replays every
   command end-to-end against the real controller; ship-quality CLI so later
   phases can regression-test the protocol.

### Phase 2 — ESPHome bridge, headless (5 issues)

1. Waveshare ESP32-S3-Touch-LCD-7 base ESPHome config: board definition,
   PSRAM enable, Wi-Fi, OTA, native API, logger, captive portal fallback.
   No BLE or display yet — just a boot-and-connect baseline.
2. `ble_client` configuration + `firmware/esphome/components/colorsplash_xg/`
   custom component that wraps the protocol discovered in Phase 1 (commands,
   notifications, framing).
3. `light` entity on top of the custom component, with `effects:` listing
   the 7 shows + 5 colors as discrete named effects, on / off, and brightness
   if the controller supports it.
4. Auto-reconnect strategy: `auto_connect: true`, exponential backoff
   watchdog (e.g., retry at 1 s, 2 s, 5 s, 15 s, then every 30 s), BLE-stack
   reset after N consecutive failures, HA-visible `connected` binary sensor.
5. Diagnostics: RSSI sensor, connected binary sensor, last-command text
   sensor, command counter, error counter. Then a 72-hour soak test leaving
   the device connected; log every disconnect and the time to reconnect.

### Phase 3 — LVGL touchscreen UI (4 issues)

1. ESPHome display + touch driver for the Waveshare 7": RGB parallel panel
   pins, GT911 I²C touch, LVGL buffer sizing in PSRAM.
2. Main screen: power toggle, current-effect label, 12-button grid (7 shows
   + 5 colors) with clear visual feedback of the active effect.
3. Brightness / speed sliders — implemented only if Phase 1 confirms the
   controller exposes them; otherwise the UI omits the slider rather than
   showing a dead control.
4. Status bar (Wi-Fi, HA API, BLE, RSSI) plus a standalone-mode verification
   pass: disconnect HA, confirm every UI action still drives the light.

### Phase 4 — RGB experiment (2 issues, time-boxed ~2 days total)

**4a — Direct arbitrary RGB probe (~1 day).** After the protocol is
understood, spend one focused session probing undocumented opcodes,
out-of-range parameters, raw 3-byte writes, and any channel-style commands.
Write up the result — positive or negative — in `docs/RGB_EXPERIMENT.md`.

**4b — Show-scrub fallback (~1 day), if 4a is negative.** Mirror the manual
technique pool owners use today — and which the official app exposes
explicitly via a **"Hold" button** that freezes the fixture on whatever
color it's currently displaying mid-show. Concretely:

1. **Characterize every show.** Record each of the 7 shows on video under
   controlled lighting starting from a known t=0 (the moment the "start
   show" command is sent). Sample frames at a fixed interval, extract the
   dominant RGB, and build a time-series per show. Result: a table mapping
   `(show_id, t_ms) → (R, G, B)`.
2. **Capture the Hold opcode.** The "Hold" button in the official app is
   already the freeze primitive — no discovery work needed beyond capturing
   the BLE write that the button generates during the Phase 1 sweep.
3. **Build the picker.** In the custom component, expose a `set_color(r,g,b)`
   method that (a) finds the closest `(show, offset)` in the characterized
   table, (b) issues the "start show" command, (c) waits `offset_ms`,
   (d) issues the Hold opcode. Report back the actual achieved color
   (nearest-point distance) so HA can show the delta.
4. **UX.** If 4b works: add an HSV/color-wheel to the LVGL UI and an
   `hs_color` mode on the HA light entity, with a "closest match" badge when
   the target isn't exactly reachable.

**Timing source for show-scrub (priority order):**
1. **A controller-emitted notification on state change**, if Phase 1 finds
   one. Cleanest, no extra hardware.
2. **Naive wall-clock from the BLE write**, accepting 30–200 ms of jitter.
   May produce a noticeable hue error but probably acceptable for a
   slow-changing pool light.
3. **External photodiode** observing the fixture's brief blackout when it
   transitions to a new state. Deterministic t=0 on the rising edge after
   blackout. Mounting location TBD (indoor with sightline through a window,
   or a separate outdoor ESPNow sensor node) — deferred until Phases 1 and
   4b prove the sensor is actually needed. Bonus: a photodiode also gives
   us ground-truth "is the light on" confirmation, useful outside
   show-scrub.

Honest caveats on 4b:
- Show characterization is a one-time step per firmware version; if the
  controller or fixture firmware changes, the table is invalidated.
- Color coverage depends entirely on which shows exist. Some shows may be
  abrupt (bad for scrubbing); at least one smooth hue-sweep show is needed
  for wide coverage.
- Even with perfect timing, the reachable gamut is bounded by the palette
  the fixture's LED drivers produce during transitions — we may get a
  decent hue sweep but limited saturation/brightness control.
- The photodiode option only works at night; daylight overwhelms the pool
  light and the blackout becomes undetectable.

### Phase 5 — Reliability & polish (3 issues)

1. End-to-end OTA flow verified, including that the BLE link recovers
   cleanly after OTA reboots.
2. Example HA automations / blueprint (sunset-on, sunrise-off, scene glue).
3. `docs/HARDWARE.md` with wiring photos, enclosure notes, install steps,
   troubleshooting tree.

### Phase 6 — Release (1 issue)

- Tag `v0.1.0`, update the README, post to the HA community forum to solicit
  cross-confirmation from other XG owners on different controller firmware
  versions.

## Deliverables

- `docs/PLAN.md` (this file)
- `docs/PROTOCOL.md` — discovered BLE protocol
- `docs/HARDWARE.md` — wiring, photos, install
- `docs/RGB_EXPERIMENT.md` — what we tried and what worked
- `firmware/esphome/colorsplash-xg.yaml` — main config
- `firmware/esphome/components/colorsplash_xg/` — custom component
- `tools/cli.py` — bleak-based reference client
- `captures/` — gitignored, except a README explaining how to reproduce

## What this project will not do

- Ship a custom Home Assistant Python integration. ESPHome's native API
  already is the HA integration; writing a second one would only duplicate
  ESPHome's entity plumbing.
- Redistribute decompiled APK source.
- Buy or recommend more hardware unless the Phase 2 field test proves the
  current BLE range is inadequate.

## Issue / milestone map

Each phase above becomes a GitHub milestone. Each numbered bullet inside a
phase becomes one GitHub issue. Total: 24 issues across 6 milestones
(Phase 4 expanded from 1 to 3 issues to cover the show-scrub fallback and
an optional photodiode sync sensor).
