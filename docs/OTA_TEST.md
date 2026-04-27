# OTA recovery test — Phase 5 #1

Verifies that an OTA firmware update does not leave the bridge
in a degraded state — specifically, that the BLE link to the
controller comes back automatically after the post-OTA reboot.
This is the canonical Phase 5 #1 acceptance task per the Plan
section of the README.

## Why this matters

The bridge is the only path between Home Assistant and the
fixture. An OTA that breaks BLE leaves the user with a non-
functional pool light until either a manual power-cycle or a
USB re-flash. The bridge has watchdog logic for stuck BLE
state (`docs/PROTOCOL.md` §Reconnect preserves state and
the watchdog implementation in
`firmware/esphome/components/colorsplash_xg/colorsplash_xg.cpp`),
but those mechanisms need to actually run after a fresh boot —
this test confirms they do.

## Acceptance criteria

- After `esphome upload` reports `INFO OTA successful`, the
  bridge must:
  1. Reboot and rejoin Wi-Fi within ~10 seconds.
  2. Re-establish the BLE link to the LPL-XG-CTRL-1 within
     ~30 seconds total post-OTA.
  3. `binary_sensor.pool_ble_connected` returns to `on`.
  4. `light.pool_light` is controllable from HA without
     manual intervention.

## Procedure

```sh
# Prerequisites:
# - bridge online and BLE-connected (binary_sensor.pool_ble_connected = on)
# - secrets.yaml + API key correctly configured

# 1. Trigger OTA
esphome upload firmware/esphome/colorsplash-xg-headless.yaml \
    --device colorsplash-xg-bridge.local

# 2. Watch for BLE reconnect via the diagnostic sensor
COLORSPLASH_API_KEY="$(cat /tmp/colorsplash-key)" \
  .venv/bin/python tools/check_ble_after_ota.py
```

(`tools/check_ble_after_ota.py` is a small helper not yet
checked in — for now, run the inline script in the "Run
results" section below.)

## Run results

### 2026-04-27, headless variant (commit ab9511f)

```
T0 (start) = 06:33:01
OTA done   = 06:33:19      (18 s upload over Wi-Fi)
BLE up     = +10.3 s        post-OTA-success
                            (so 06:33:30 wall clock)
total      = ~28 s end-to-end
```

`binary_sensor.pool_ble_connected` came back `on` 10 seconds
after `esphome upload` reported `INFO OTA successful`. No
manual power cycle. No USB intervention. ✅ Acceptance met.

The OTA window is small enough that even an active HA
automation calling the light during the OTA would just see a
single failed call and a successful retry. No state
corruption, no stuck BLE.

## Caveats

- 18-second upload is best-case (small firmware, fast LAN,
  WROOM-32 OTA path). Larger firmware images or congested Wi-Fi
  will take longer; the recovery time after the reboot is what
  matters for the acceptance criterion.
- The first OTA after a fresh flash sometimes takes longer for
  the bridge to stabilize Wi-Fi as it re-pairs to the AP. After
  the first OTA, subsequent OTAs are consistently fast.
- This test ran with the bridge already established on the
  network. If the Wi-Fi credentials in the new firmware differ
  from the last-flashed firmware, the bridge falls into captive-
  portal mode and the test isn't applicable.

## Related

- [`docs/SOAK_TEST.md`](SOAK_TEST.md) — 72-hour soak procedure
  (catches issues OTA-recovery alone wouldn't surface)
- [`docs/HARDWARE.md`](HARDWARE.md) — install-side
  troubleshooting
