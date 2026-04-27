# Hardware install — headless ESP32 bridge

Bill of materials, wiring, install notes, and the troubleshooting
tree for the **headless variant** (`firmware/esphome/colorsplash-xg-headless.yaml`).
Located near the pool's equipment pad with the BLE link to the
J&J ColorSplash XG controller well within range. For the
display variant (Waveshare 7" touchscreen), see the README's
"Display variant" subsection — it lives at git tag
`v0.1.0-display` and has a different install story (wall-mount
indoors).

> Status: bridge currently bare-board for testing. Permanent
> enclosure ordered; this doc gets photos + final mount notes
> once it arrives.

## Bill of materials

| Item | Notes |
|---|---|
| ESP32-WROOM-32 dev kit | Any vendor (HiLetgo, ESP32-DevKitC, etc.). Onboard PCB antenna is fine; u.FL connector + external antenna is an upgrade path if RSSI is marginal. |
| USB-C or microUSB cable | Whatever the dev kit uses. Long enough to reach an outlet. |
| 5 V USB power supply | 1 A is plenty; bridge draws < 200 mA peak. Pick one rated for 24/7 duty. |
| Outdoor-rated enclosure | If installing outside near the pad. Should accommodate the dev kit footprint + cable strain relief + a vent or breathing membrane to avoid condensation. |
| Mounting hardware | Velcro / Command strips / screws + standoffs depending on enclosure. |

## Network requirements

| Service | Purpose |
|---|---|
| 2.4 GHz Wi-Fi | ESPHome native API to Home Assistant. WROOM-32 doesn't speak 5 GHz. |
| Same VLAN as HA | mDNS discovery + ESPHome native API on TCP 6053. If HA is on a separate VLAN, you'll need either an mDNS reflector (e.g., Avahi) or a static IP + manual integration entry. |
| Sufficient signal | RSSI as seen by the bridge to the controller should be ≤ −85 dBm or better. The headless variant exists specifically because the wall-mount Waveshare-display install measured −88 to −95 dBm; the WROOM-32 placed near the pad reads ~−67 dBm in our install. |

## BLE link

The fixture's controller (J&J LPL-XG-CTRL-1) accepts exactly one
BLE central at a time. While the bridge holds the connection,
the official phone app cannot connect — that's expected, not a
fault. Verify connection state via the `BT` LED on the
controller's enclosure: blinks while advertising (no central
connected), solid when a central is connected (the bridge).

## Wiring

For the dev-board variant, "wiring" is just USB power. The
WROOM-32 dev kit handles power regulation, USB-UART bridge,
boot mode, and reset internally.

```
   ┌─────────────────────────┐
   │  ESP32-WROOM-32 dev kit │
   │  ┌────────────────────┐ │
   │  │   ESP32 module     │ │
   │  └────────────────────┘ │
   │  ┌──────────┐           │
   │  │ CP2102 / │  micro-B  │ ◄── 5V USB power supply
   │  │  CH340   │  or USB-C │
   │  └──────────┘           │
   └─────────────────────────┘
```

If you eventually move to a permanently-installed PCB or a
custom enclosure with its own DC input, the WROOM-32 module's
`VCC` pin wants a regulated 3.3 V (most dev kits regulate from
the 5 V USB rail to 3.3 V on-board). Don't feed 5 V directly to
the module.

### Soldering / GPIO headers

None needed for the headless variant. The bridge uses only
Wi-Fi + BLE; no display, touch, I²C, or GPIO peripherals are
wired. If you later want a status LED or button, add an LED
on any free GPIO and wire it via the YAML.

## Install location

The headless bridge needs to be reasonably close to the
controller for a strong BLE link. "Reasonably close" in our
install translates to:

- ~5–10 ft from the controller, with a clear or near-clear
  RF path
- Same building / structure (ideally in the same equipment
  enclosure or on the same wall)
- AC power outlet within reach

Outdoor / poolside install considerations:

- **Direct sunlight exposure** heats the dev board. ESP32 is
  rated to ~85 °C junction temperature; an enclosure in full
  sun can exceed that. Mount in shade, or in an enclosure with
  some airflow.
- **Splash zone**: keep it out of any direct splash path. The
  enclosure should be IP54 or better if there's any chance of
  water exposure.
- **Cable run**: pool equipment areas are usually wet
  environments. Run USB power through a drip loop and use an
  outdoor-rated outlet with GFCI protection.

## Troubleshooting tree

### Bridge doesn't appear on the network

1. Confirm USB power is connected (LED on dev kit lit).
2. Try `ping colorsplash-xg-bridge.local` from a device on the
   same VLAN as the bridge.
3. If mDNS doesn't resolve, find the IP from your router's
   DHCP lease table.
4. If the bridge is genuinely offline, USB-attach the dev kit
   and run `esphome logs colorsplash-xg-headless.yaml --device /dev/cu.usbserial-*`.
   Look for Wi-Fi association failures or boot crashes.
5. If Wi-Fi credentials are wrong, the bridge falls back to a
   captive-portal AP named `ColorSplash XG Bridge Fallback`.
   Connect to it from a phone, enter correct credentials.

### BLE link doesn't come up (`binary_sensor.pool_ble_connected = off`)

1. Power-cycle the controller. The BT121 module sometimes hangs
   if it was reset mid-pair.
2. Check `text_sensor.pool_last_ble_error` for the most recent
   error string.
3. Confirm RSSI in `sensor.pool_ble_rssi` — anything worse than
   −90 dBm is on the edge of unstable; consider relocating the
   bridge closer to the controller.
4. If the official phone app is also unable to connect, the
   controller itself may need attention (factory reset, etc.) —
   that's outside this project's scope.
5. For a full BLE-stack reset, restart the bridge: in HA, click
   "Reload" on the ESPHome integration; or pull power for 10 s.

### Fixture doesn't respond to commands

1. Check `sensor.pool_command_count` — does it increment when
   you tap a color? If yes, the bridge is sending; the
   controller may be busy.
2. Check `text_sensor.pool_last_echo` — does it show the byte
   you sent? An echo confirms the controller received the
   write.
3. If there's a `text_sensor.pool_last_command` value but no
   matching echo, the controller dropped the write — usually a
   transient BLE issue. Wait 10 s and retry.

### RGB color picker (Phase 4b) lands the wrong color

1. Confirm the firmware was built with the LUT (the bare
   `git checkout v0.1.0-display` build doesn't have it). Look
   at `text_sensor.pool_last_command` after a color pick — it
   should show the show-byte name, not just `Standby`.
2. If the locked color is consistently downstream of the
   picked target, retune `--lock-comp-ms` in the C++ default
   (currently 700 ms — see commit 223ad93). The right value
   varies with fixture firmware revision.
3. The fixture's reachable gamut is constrained — saturated
   cyan, yellow, etc. aren't achievable. Issue #53 captures
   the future preset-card UI for working around this.

## Related documents

- [`docs/PROTOCOL.md`](PROTOCOL.md) — BLE protocol details
- [`docs/SOAK_TEST.md`](SOAK_TEST.md) — uptime / reliability
  procedure (display variant; headless variant soak pending)
- [`docs/STANDALONE_TEST.md`](STANDALONE_TEST.md) — display
  variant only (verifies the panel keeps working when HA is
  unreachable; not relevant for headless)
- [`docs/RGB_EXPERIMENT.md`](RGB_EXPERIMENT.md) — Phase 4
  results and the Phase 4b picker model
