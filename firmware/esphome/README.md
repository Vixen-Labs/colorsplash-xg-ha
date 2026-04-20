# firmware/esphome

ESPHome firmware for the ColorSplash XG → Home Assistant bridge,
targeting a Waveshare ESP32-S3-Touch-LCD-7 (ESP32-S3-WROOM-1-N16R8,
16 MB flash, 8 MB octal PSRAM).

## Files

- **`colorsplash-xg.yaml`** — the canonical config. Phase 2 #9 scope:
  boot, Wi-Fi, Home Assistant API, OTA, captive-portal fallback. No
  BLE, no display, no LVGL yet.
- **`secrets.yaml.example`** — template for the values `!secret` refers
  to in the main config. Copy to `secrets.yaml` (gitignored) and fill
  in real values.
- **`secrets.yaml`** — gitignored; never commit.

## First-time setup

1. Copy the secrets template and edit it:
   ```sh
   cd firmware/esphome
   cp secrets.yaml.example secrets.yaml
   ```
2. Generate a fresh API encryption key:
   ```sh
   python3 -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
   ```
   Paste the output into `secrets.yaml` as `api_key`. Don't reuse a
   key from another ESPHome device.
3. Fill in `wifi_ssid`, `wifi_password`, `fallback_ap_password` (≥8
   characters), and `ota_password`.
4. Validate the config without flashing:
   ```sh
   esphome config firmware/esphome/colorsplash-xg.yaml
   ```

## First flash (USB)

The `esphome` CLI on macOS handles this end-to-end.

1. Connect the Waveshare board to the Mac via USB-C.
2. If the board isn't seen by the host OS, hold **BOOT**, tap
   **RESET**, release **BOOT** to enter ROM bootloader.
3. Flash + monitor:
   ```sh
   esphome run firmware/esphome/colorsplash-xg.yaml
   ```
   The CLI will compile, flash over USB, then stream the serial log.

Expected log output on success (abbreviated):
```
[I][wifi:...]: Connected to Wi-Fi … IP: 192.168.x.y
[I][api:...]: Listening on 0.0.0.0:6053
[I][mdns:...]: Advertising hostname colorsplash-xg.local
```

## Subsequent updates (OTA)

Once the device is on Wi-Fi, `esphome run` auto-discovers it and
uploads firmware over the network:

```sh
esphome run firmware/esphome/colorsplash-xg.yaml
```

No USB needed after the first flash.

## Using from the Home Assistant ESPHome add-on

If you prefer to manage this device from the HA ESPHome add-on:

1. Copy `colorsplash-xg.yaml` and `secrets.yaml` into
   `/config/esphome/` on the HA host (via Samba / File Editor / SSH).
2. In the add-on UI: the device appears in the dashboard. Click
   **Install** and pick OTA as the method.

The canonical YAML lives in this repository; copy-into-HA is just the
deployment mechanism.

## After this issue closes

- **#10** — BLE client + `colorsplash_xg` custom component
- **#11** — expose as a Home Assistant `light` entity
- **#12** — auto-reconnect + BLE watchdog
- **#13** — diagnostic sensors + 72 h soak test
- **#14** — display + touch driver (Phase 3)
