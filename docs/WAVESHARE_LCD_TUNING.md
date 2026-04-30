# Tear-free RGB on Waveshare ESP32-S3-Touch-LCD-7

Settings required to get a clean, glitch-free display on the Waveshare ESP32-S3-Touch-LCD-7 (800×480 RGB-parallel + GT911 touch
+ CH422G I/O expander) under ESPHome with concurrent BLE + Wi-Fi

These tunings were derived from [Waveshare's official ESP32-S3-Touch-LCD-7B reference][wave-ref] plus empirical testing during Phase 3 #15. ESPHome's bundled `mipi_rgb` preset for this board (as of 2026.4.0) gets the pin map right but does **not** carry the vendor's recommended PSRAM and panel-DMA tunings.

[wave-ref]: https://github.com/waveshareteam/ESP32-S3-Touch-LCD-7B/tree/main/examples/ESP-IDF/13_LVGL_TRANSPLANT

## Symptoms when these tunings are missing

- **Bursty vertical scanline shifts** — parts (or all) of the screen briefly offset down by a few rows, then snap back. Caused by RGB panel DMA losing pclk cycles when the PSRAM bus is contended by Wi-Fi/BLE bursts
- **Idle flicker** even when nothing is being drawn
- **Glitches under interaction** (button taps, list scrolls)
- No color noise, no whole-screen flicker, no banding — pure scanline desync

## Recipe (ALL pieces required; partial fixes are *worse* than none)

### 1. Vendor-aligned ESP-IDF sdkconfig + PSRAM speed

In `colorsplash-xg.yaml`'s `esp32:` block:

```yaml
esp32:
  board: esp32-s3-devkitc-1
  variant: ESP32S3
  flash_size: 8MB
  framework:
    type: esp-idf
    version: recommended
    advanced:
      enable_idf_experimental_features: true   # required for 120 MHz PSRAM
    sdkconfig_options:
      CONFIG_FREERTOS_HZ: "1000"               # 1 ms tick — smoother scheduling
      CONFIG_ESP32S3_DATA_CACHE_LINE_64B: y    # better PSRAM cache patterns
      CONFIG_COMPILER_OPTIMIZATION_PERF: y     # optimize for speed not size

psram:
  mode: octal
  speed: 120MHz                                # not 80 — bus headroom matters
```

**Why `LV_ATTRIBUTE_FAST_MEM_USE_IRAM` is NOT set**: Waveshare's reference enables it but that Kconfig is for ESP-IDF's managed-components LVGL packaging. ESPHome's LVGL packaging doesn't define the corresponding macro under that flag, so enabling it produces compile errors. Skip it.

### 2. Patched `mipi_rgb` component

ESPHome 2026.4.0 hardcodes `num_fbs = 1` and lacks `bb_invalidate_cache` and `psram_trans_align`. Without these the panel runs single-buffered, has stale pixels in CPU cache when DMA reads, and burst-reads are misaligned with the cache line.

Workaround: copy the upstream `mipi_rgb` component into the project as a local override and patch its setup. With the project's existing `external_components.local` block pointing at `firmware/esphome/components/`, ESPHome picks up the local copy instead of the built-in.

```sh
mkdir -p firmware/esphome/components/mipi_rgb
cp -r $(brew --prefix esphome)/libexec/lib/python3.*/site-packages/esphome/components/mipi_rgb/* \
      firmware/esphome/components/mipi_rgb/
rm -rf firmware/esphome/components/mipi_rgb/__pycache__
```

Then in `firmware/esphome/components/mipi_rgb/mipi_rgb.cpp`, inside `MipiRgb::common_setup_()`, change:

```cpp
config.flags.fb_in_psram = 1;
config.bounce_buffer_size_px = this->width_ * 10;
config.num_fbs = 1;                      // ← original
```

to:

```cpp
config.flags.fb_in_psram = 1;
config.bounce_buffer_size_px = this->width_ * 10;   // 10 lines, vendor recipe
config.num_fbs = 2;                                  // double-buffered
config.flags.bb_invalidate_cache = 1;                // CPU cache flush
config.psram_trans_align = 64;                       // cache-line align
```

### 3. LVGL config

```yaml
lvgl:
  displays: main_display
  touchscreens: pool_touch
  rotation: 90                # or 270 depending on mount orientation
  buffer_size: 100%           # full back-buffer; no partial dirty-region writes
  full_refresh: true          # render whole screen each tick → atomic swap
  bg_color: 0x0D0D14
  text_color: 0xF0F0F0
```

When `lvgl.rotation:` is set, **do not** add `swap_xy` / `mirror_x` / `mirror_y` on the touchscreen — LVGL handles input rotation itself, and a layered transform double-rotates and scrambles the mapping.

### 4. Display + touch

```yaml
display:
  - platform: mipi_rgb
    id: main_display
    model: ESP32-S3-TOUCH-LCD-7-800X480
    # Native landscape; LVGL rotates.

touchscreen:
  - platform: gt911
    id: pool_touch
    i2c_id: bus_a
    interrupt_pin: GPIO4
    reset_pin:
      ch422g: io_expander
      number: 1
    display: main_display
```

(Reset pin via the CH422G I/O expander, not a direct GPIO — the preset relies on this.)

## What did NOT help

| Tried | Result |
|---|---|
| `lvgl.buffer_size: 100%` alone (no `num_fbs=2`) | Still glitching |
| `lvgl.full_refresh: true` alone | No change |
| `lvgl.buffer_size: 25%` (smaller back-buffer in SRAM) | Glitches at idle |
| `pclk_frequency: 10MHz` | Boot crash, ESPHome fell back to test-card |
| Disabling `lvgl.rotation` | Still glitching in landscape |
| `psram.speed: 40MHz` | Glitches *worse* than 80 MHz |
| `num_fbs=2` without `bb_invalidate_cache` | Worse than with |
| Bigger bounce buffer (width × 30 instead of × 10) | Helped some, but vendor's 10 + alignment + 120 MHz works better |

## Upstream contribution opportunity

The fix would be:

- Expose `num_fbs`, `bounce_buffer_size_px`, `bb_invalidate_cache`, and `psram_trans_align` as YAML options on `mipi_rgb`
- Default `num_fbs` based on whether `lvgl:` is present (need double-buffering when rendering animations) and on available PSRAM

A PR against ESPHome would eliminate the local-override step for this and similar boards. Issue: the patch above is local-only until upstreamed.

## Verifying the fix

1. Compile + flash via USB cable (`esphome run … --device /dev/cu.usbmodem*`).
2. Press RESET if the chip doesn't auto-boot the new firmware.
3. Watch the screen for 60 s at idle: no flicker, no scanline shifts.
4. Tap each tile / open the dropdown / scroll: clean redraws.
5. Check ESPHome boot log for `120 MHz PSRAM` confirmation.

## Critical files this touches

- `firmware/esphome/colorsplash-xg.yaml` — psram, framework, lvgl, touchscreen blocks
- `firmware/esphome/components/mipi_rgb/mipi_rgb.cpp` — local patch
- `firmware/esphome/components/mipi_rgb/{__init__.py,display.py,mipi_rgb.h,models/}` — verbatim copies of upstream (kept intact so ESPHome's loader treats the local override as a complete package)
