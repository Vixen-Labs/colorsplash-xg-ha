# firmware/esphome

ESPHome firmware for the ColorSplash XG → Home Assistant bridge.
Two configs are shipped:

- **`colorsplash-xg-headless.yaml`** — primary going forward.
  Targets a plain ESP32-WROOM-32 dev kit placed near the equipment
  pad (best BLE link margin to the LPL-XG-CTRL-1). HA is the
  user-facing UI.
- **`colorsplash-xg-display.yaml`** — historical / preserved.
  Targets a Waveshare ESP32-S3-Touch-LCD-7 (7" touchscreen,
  ESP32-S3-WROOM-1-N16R8, 8 MB octal PSRAM) and adds a full LVGL
  UI on the panel. Frozen at git tag `v0.1.0-display`; usable for
  anyone who wants the touchscreen path.

Both configs share the custom `colorsplash_xg` BLE component, the
HA `light.pool_light` entity, and the same diagnostic sensors —
they're identical from HA's point of view, just different bridge
hardware.

## Files

- **`colorsplash-xg-headless.yaml`** — headless bridge config.
- **`colorsplash-xg-display.yaml`** — display variant config (LVGL
  UI, RGB panel, touch, vendor PSRAM tunings).
- **`components/colorsplash_xg/`** — external ESPHome component
  wrapping the single-byte BLE protocol from `docs/PROTOCOL.md`.
  Self-contained: scans for the controller's advertised local name
  `BGScripr` and connects. An optional `mac_address:` YAML
  override disambiguates when multiple BGScripr devices are in
  range.
- **`components/mipi_rgb/`** — local override of ESPHome's
  bundled `mipi_rgb` component, patched for tear-free RGB panel
  output on the Waveshare 7" display. Used only by the display
  variant; the headless variant ignores it.
- **`secrets.yaml.example`** — template for the values `!secret`
  refers to in the configs. Copy to `secrets.yaml` (gitignored)
  and fill in real values. Both configs share the same secrets
  file.
- **`secrets.yaml`** — gitignored; never commit.

## Controller pairing

No manual pairing needed. The firmware scans continuously for a
peripheral advertising the local name `BGScripr` (Silicon Labs
BT121 BGScript runtime — that's what the ColorSplash XG controller
reports). On match it connects, subscribes to indications on the
vendor command characteristic, and is ready to drive the fixture.

Debug it from Home Assistant → Developer Tools → Logs. You should
see:

```
[I][colorsplash_xg:...]: found ColorSplash XG controller at ... (rssi=-??)
[I][colorsplash_xg:...]: indications enabled — ready to drive fixture
```

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
   Paste the output into `secrets.yaml` as `api_key`. Don't reuse
   a key from another ESPHome device.
3. Fill in `wifi_ssid`, `wifi_password`, `fallback_ap_password`
   (≥8 characters), and `ota_password`.
4. Validate the config without flashing:
   ```sh
   esphome config firmware/esphome/colorsplash-xg-headless.yaml
   # or, for the display variant:
   esphome config firmware/esphome/colorsplash-xg-display.yaml
   ```

## Flashing — headless variant (ESP32-WROOM-32)

1. Connect the WROOM-32 dev kit via USB. The board's CP2102 /
   CH340 USB bridge enumerates as `/dev/cu.usbserial-*` (or
   `/dev/cu.SLAB_USBtoUART` on some macOS setups).
2. Flash:
   ```sh
   esphome run firmware/esphome/colorsplash-xg-headless.yaml
   ```
   ESPHome handles the BOOT/RESET dance via DTR/RTS automatically;
   no manual button press required.
3. After upload, the board reboots and joins Wi-Fi (typically
   within 10 s), advertising `colorsplash-xg-bridge.local` over
   mDNS.

## Flashing — display variant (Waveshare 7")

The Waveshare board exposes **two USB-C ports** — one labeled
`UART1` (CH343 bridge) and one labeled `USB` (the ESP32-S3's
native USB-JTAG/Serial). **Use the `USB` port for flashing.** The
`UART1` bridge corrupts the esptool protocol stream on this board
(stub upload fails with checksum errors at every baud rate).

1. Connect USB-C to the port labeled **`USB`** on the board.
2. Hold **BOOT**, tap **RESET**, release **BOOT** to enter ROM
   bootloader. A `/dev/cu.usbmodem*` device appears.
3. Flash:
   ```sh
   esphome run firmware/esphome/colorsplash-xg-display.yaml --no-logs
   ```
4. **Press the physical RESET button on the board** after the
   upload finishes. The `Hard resetting via RTS` step esptool
   performs does not actually reset the chip over native
   USB-JTAG — without a manual RESET, the board stays in the
   stub loader and never runs the new firmware.

`logger.hardware_uart: USB_SERIAL_JTAG` in the display YAML routes
log output back over the same `USB` port, so `esphome logs` works
without a second cable.

## Verifying after flash

```sh
dns-sd -B _esphomelib._tcp local.            # should list the device
dns-sd -G v4 colorsplash-xg-bridge.local      # (or colorsplash-xg.local for display)
nc -zv <ip> 6053                              # HA API port open
```

## Headless config option: experimental RGB color picker

`light.pool_light` defaults to **classic** mode (on/off +
12 named effects, no color wheel). Phase 4b shipped an
experimental color-wheel that drives the fixture via an
embedded show-scrub LUT — opt in by adding `rgb_mode: true`
to the light's YAML config:

```yaml
light:
  - platform: colorsplash_xg
    # … other options …
    rgb_mode: true   # advertises ColorMode::RGB to HA
    # rgb_mode: false  # default — classic effects-only
```

After changing `rgb_mode`, you must re-flash the bridge AND
reload the ESPHome integration in HA (Settings → Devices &
Services → ESPHome → 3-dot menu → Reload). HA caches the
device's color-mode capability at integration setup; just
re-flashing isn't enough.

Why it's experimental: the fixture's reachable color gamut is
constrained, so target RGBs land approximately rather than
exactly (issue #54 has full context). The future preset-card
work (issue #53) will give users a way to save & tweak specific
known-good colors as named presets, sidestepping the gamut
imprecision.

## Subsequent updates (OTA)

Once the device is on Wi-Fi, `esphome run` auto-discovers it and
uploads firmware over the network — no USB needed:

```sh
esphome run firmware/esphome/colorsplash-xg-headless.yaml
```

## Using from the Home Assistant ESPHome add-on

If you prefer to manage the device from the HA ESPHome add-on:

1. Copy the desired YAML and `secrets.yaml` into `/config/esphome/`
   on the HA host (via Samba / File Editor / SSH).
2. In the add-on UI: the device appears in the dashboard. Click
   **Install** and pick OTA as the method.

The canonical YAML lives in this repository; copy-into-HA is just
the deployment mechanism.
