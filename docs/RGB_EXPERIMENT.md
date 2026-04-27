# Phase 4a — direct RGB probe (negative)
# Phase 4b — show-scrub picker (positive)

## Phase 4a result

**No arbitrary RGB is reachable via the LPL-XG-CTRL-1's BLE
protocol directly.** The controller exposes exactly the 15
documented single-byte opcodes (Standby + 7 shows + 5 solids +
Lock + Return) and silently rejects everything else. The 12-tile
palette in the official J&J ColorSplash XG app is the complete
user-reachable surface — there are no hidden opcodes, no
parameterised commands, and no multi-byte writes.

See [§Phase 4a method + findings](#phase-4a-method-and-findings)
for the probe details.

## Phase 4b result

**Show-scrub works as a reliable arbitrary-RGB mechanism.** Every
one of the 7 shows has a deterministic per-replay transition
envelope: command-to-first-color timing reproduces with σ ≤ 112 ms
across 3 replays per show. The picker tool
(`tools/pick_color.py`) loads a calibration dataset, finds the
sample whose observed RGB is closest to a target, and either
recommends or directly executes a `(start_byte, wait_ms)` recipe.

### Per-show consistency (3 replays each)

| Show | Cmd→color mean | σ | Picker precision (95% CI) |
|---|---:|---:|---:|
| Super Nova | 4408 ms | 29 ms | ±58 ms |
| Desert Skies | 6341 ms | 30 ms | ±60 ms |
| Nova | 6874 ms | 33 ms | ±66 ms |
| Peruvian Paradise | 3972 ms | 38 ms | ±75 ms |
| Patriot Dream | 6005 ms | 62 ms | ±124 ms |
| Tidal Wave | 5454 ms | 101 ms | ±201 ms |
| Northern Lights | 4946 ms | 112 ms | ±224 ms |

Every show landed at GOOD on the analyzer's verdict
threshold (σ ≤ 200 ms). Five of seven shows are tight (σ ≤ 65
ms); two show somewhat looser timing (Tidal Wave / Northern
Lights, both ≤ 225 ms 95 % CI), still well under the windows
where the show's color visibly changes.

The "old-color persists" pre-blackout latency is consistently
~50–70 ms across all shows (σ = 5–6 ms each) — that's the
fixed BLE write + BGScript dispatch delay before the controller
acts on the new command.

### Tool stack

- **`tools/calibrate_show_colors.py`** — drives the bridge
  through ambient + 5 solids + 7 shows, sampling RGB via cv2
  + camera. Produces a calibration JSON with per-show timeline
  data.
- **`tools/extract_colors_from_video.py`** — alternative
  calibration path: post-process a video file (e.g. an iPhone
  Final Cut Camera recording with locked WB + exposure) +
  events log to produce the same JSON shape but with cleaner
  color data.
- **`tools/replay_probe.py`** — drives one show N times back-
  to-back and samples cv2 throughout. Used for measuring
  per-show timing reproducibility.
- **`tools/analyze_replay_consistency.py`** — reports per-show
  timing distribution (mean, σ, min, max) and a GOOD / USABLE /
  POOR verdict.
- **`tools/pick_color.py`** — given a target observed RGB,
  finds the closest reachable sample (solid or show-scrub),
  prints the recipe, and optionally fires the bridge to display
  it (`pool_send_byte` for solids, `pool_scrub` for shows).

### Picker behaviour

- **Solid preference bias** (default 30 RGB units): when a
  target is close to one of the 5 named solid presets, the
  solid wins over a marginally-closer show sample. Solids are
  deterministic — no scrub timing, no Lock — so a small
  distance penalty for shows is justified by zero timing
  variance.
- **Skip-early window** (default 2500 ms): samples in the
  pre-blackout / firmware-dispatch window are excluded from
  matching, so the picker never recommends a `wait_ms` value
  that lands during the controller's old-color-persists period.
- **Replay-mode-aware**: the picker recognises `<show> #N`
  keys from `replay_probe.py` output and matches the base
  show name, so a single dataset can mix calibration data and
  replay-test data without confusing the search.

### Reachable color gamut

The fixture + pool reflectance combination determines what RGB
targets are actually attainable. From the
`tools/show_colors_video.json` calibration:

| Target style | Attainable? | Best match |
|---|---|---|
| Pure red `(200, 30, 30)` | ✓ | Brazilian Red solid (dist 68) |
| Pure blue `(30, 30, 200)` | ✓ | Parisian Blue solid (dist 48) |
| Cyan `(0, 200, 200)` | ✗ | Tidal Wave dist 113 (saturated cyan unreachable) |
| Yellow `(230, 200, 30)` | weak | Nova @ 70 s dist 85 |
| Pink `(220, 90, 180)` | weak | Northern Lights @ 74 s dist 63 |
| Muted purple `(140, 80, 180)` | ✓ | Northern Lights @ 32 s dist 5 |

In general, distances ≤ 30 are excellent matches; 30–80 are
acceptable; > 100 means the target is genuinely outside the
fixture's gamut.

## Phase 4a method and findings

The probe ran against the headless ESP32 bridge
(`firmware/esphome/colorsplash-xg-headless.yaml`) on
2026-04-25, against the production controller in normal install
location (RSSI ~−67 dBm — solid link).

Two probe surfaces were added to the bridge YAML, both calling
into the existing `colorsplash_xg` custom component:

- **Single-byte probe** — `text.pool_probe_byte_hex` +
  `button.pool_probe_send_byte`. The button's lambda parses the
  hex string and calls
  `id(xg).send_effect_byte((uint8_t) value)`, which uses the
  documented single-byte protocol path (1-byte ATT Write Request
  to handle 0x000f).
- **Multi-byte probe** — `text.pool_probe_bytes_hex` +
  `button.pool_probe_send_bytes`. The button's lambda parses the
  hex stream and calls
  `id(xg).probe_write_raw(std::vector<uint8_t>)`, a new escape
  hatch on the component that bypasses the single-byte queue and
  issues an N-byte ATT Write Request directly. Up to 20 bytes
  (the BLE MTU is capped by the controller at 23 — see
  `docs/PROTOCOL.md` §iOS cross-check — minus the 3-byte ATT
  Write Request header).

Indication echoes from the controller were observed via
`text_sensor.pool_last_echo`, which surfaces the component's
`last_echoed_byte()` getter. Per `docs/PROTOCOL.md`
§Controller-to-central indications, the indication echo is the
authoritative "command accepted" signal — its absence indicates
the controller did not act on the write.

### Single-byte sweep — bytes outside the documented range alias to the documented opcodes via modulo 14

The documented opcode space is 0x00..0x0e (15 values: Standby +
7 shows + 5 solids + Lock + Return). Probing a sample of bytes
above 0x0e revealed that the controller silently maps each one
to a documented opcode according to:

```
mapped_opcode = ((n - 1) mod 14) + 1     for n ≥ 1
mapped_opcode = 0x00                      for n == 0
```

Verified data points:

| Probed byte | Predicted (formula) | Observed visible effect |
|---:|---|---|
| 0x0f (15) | (14 mod 14)+1 = 1 = **Peruvian Paradise** | matched |
| 0x10 (16) | (15 mod 14)+1 = 2 = **Super Nova** | matched |
| 0x1c (28) | (27 mod 14)+1 = 14 = **Return** | matched (with ~20 s blackout — see below) |

The indication echo carries the byte we wrote (e.g. writing 0x0f
echoes 0x0f back), so the alias happens at the
opcode-interpretation layer, not at the BLE wire layer.

**Implication**: there are no hidden first-class opcodes to
discover by sweeping the upper byte range. The 14 visible-effect
opcodes are the complete set; the controller defaults
out-of-range bytes back into them.

### Anomalous transition latency on out-of-range bytes

Writing 0x1c (which aliases to Return) produced a fixture
blackout of approximately 20 seconds before the visible Return
color appeared — well outside the documented 5-10 s
solid-to-solid transition envelope (`docs/PROTOCOL.md` §Visual
transition latency). The fixture initially appeared to have
entered Standby; only after the extended blackout did the locked
color come up.

This may indicate that the controller's input-sanitization path
for out-of-range bytes adds extra processing time, or that there
is a side effect of feeding it an unmapped value beyond just the
modulo lookup. Not investigated further — the alias result was
the relevant data point.

### Multi-byte writes are silently rejected

Writing `08 00 00` (3 bytes, first byte = Parisian Blue):

- ESPHome `text_sensor.pool_last_command` updated to
  `raw[3] 08 00 00` — confirming our firmware did issue the
  3-byte ATT Write Request.
- `text_sensor.pool_last_echo` did NOT update — the controller
  did not emit an indication echo for this write.
- Fixture state did NOT change (was Arctic White before the
  write, stayed Arctic White after).

Writing `08` (1 byte) through the **same** multi-byte path:

- Fixture changed to Parisian Blue, indication echo updated to
  `0x08`.

The two results together prove:

1. The new multi-byte send path is not buggy — it works for
   length 1 and the BLE wire layer succeeds in delivering the
   bytes (the central does not see an ATT error response, since
   esp_ble_gattc_write_char did not return failure either).
2. The controller silently discards writes with payload length
   > 1: it neither acts on them nor echoes them back.

This rules out parameterised commands of any flavour (RGB
triplet, RGBW quad, length-prefixed, opcode + parameter, etc.)
on the documented command characteristic. There is no other
writable characteristic on this controller (only DIS read-only
chars, the command char at 0x000f, and its CCCD).

## Caveats

- Tested on one controller unit. Different LPL-XG-CTRL-1
  firmware revisions could in theory expose different behaviour;
  the controller does not expose a Firmware Revision String so
  we cannot identify which build this is. Cross-confirmation
  from other XG owners would strengthen both the negative
  Phase 4a result and the positive Phase 4b model.
- 3 replays per show in Phase 4b is enough to demonstrate
  reproducibility but is not a tight statistical bound. A 10×
  or 20× replay run would tighten the σ estimates if needed for
  a future picker integration.
- Calibration is camera + pool-reflectance specific. The
  observed RGB values in `tools/show_colors_video.json` are
  what *this* user's pool surface looks like through *this*
  camera. Re-calibration is required for a different
  installation.
- The picker operates entirely in observed-RGB space — no
  display-referred color management or perceptual distance
  metrics (Lab, CIEDE2000) are applied. Euclidean RGB distance
  is fine for "look-like" matching against the camera-observed
  reference, which is the picker's actual purpose.
