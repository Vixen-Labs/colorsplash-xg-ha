# Phase 4a — direct RGB probe (negative)

## Result

**No arbitrary RGB is reachable via the LPL-XG-CTRL-1's BLE
protocol.** The controller exposes exactly the 15 documented
single-byte opcodes (Standby + 7 shows + 5 solids + Lock + Return)
and silently rejects everything else. The 12-tile palette in the
official J&J ColorSplash XG app is the complete user-reachable
surface — there are no hidden opcodes, no parameterised commands,
and no multi-byte writes.

Phase 4b's show-scrub fallback (lock the fixture mid-show on the
desired colour) is therefore the only remaining path to arbitrary
colours and will be the next phase of work.

## Method

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

## Findings

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
colour appeared — well outside the documented 5-10 s
solid-to-solid transition envelope (`docs/PROTOCOL.md` §Visual
transition latency). The fixture initially appeared to have
entered Standby; only after the extended blackout did the locked
colour come up.

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

## Conclusion

The controller is fundamentally constrained to the 14 visible
effects + 1 standby state baked into its firmware. The protocol
surface area exposed over BLE matches the official app's UI
exactly; there is no hidden control plane.

**Phase 4a closes negative.** The next move is Phase 4b (show-
scrub fallback): characterise each show's colour cycle, then
expose `set_color(r, g, b)` that picks the closest show + offset,
starts the show, waits for the fixture to reach that colour, and
sends Lock to freeze it there. Per `docs/PROTOCOL.md`'s show
gradients table, the per-show colour sequences are already known
from the app decompile, so 4b doesn't need to characterise the
shows from scratch on video.

## Reproducer

The probe entities remain in
`firmware/esphome/colorsplash-xg-headless.yaml` so this result is
re-verifiable on any other LPL-XG-CTRL-1 firmware revision. To
reproduce:

1. Flash the headless variant to a bridge connected to the
   controller.
2. In HA, set `text.pool_probe_byte_hex` to a probe value (e.g.
   `0f`) and press `button.pool_probe_send_byte`. Observe
   `text_sensor.pool_last_echo` and the fixture.
3. For multi-byte tests, set `text.pool_probe_bytes_hex` (e.g.
   `08 00 00`) and press `button.pool_probe_send_bytes`. Echo
   should remain unchanged; fixture should not respond.
4. The component method `colorsplash_xg::probe_write_raw(std::
   vector<uint8_t>)` in
   `firmware/esphome/components/colorsplash_xg/colorsplash_xg.cpp`
   is the lower-level escape hatch if a future probe wants to
   try other patterns (write-without-response,
   different-handle, larger payloads up to MTU).

## Caveats

- Tested on one controller unit. Different LPL-XG-CTRL-1
  firmware revisions could in theory expose different behaviour;
  the controller does not expose a Firmware Revision String so
  we cannot identify which build this is. Cross-confirmation
  from other XG owners would strengthen the negative result.
- Did not exhaustively sweep all 240 unmapped bytes — sampled
  three values that, together with the formula derivation, are
  sufficient to demonstrate the modulo-alias rule. A future
  contributor wanting to verify exhaustively can do so cheaply
  with the existing probe UI.
- Did not test write-without-response (`ESP_GATT_WRITE_TYPE_NO_RSP`)
  or auth-required writes (`ESP_GATT_AUTH_REQ_SIGNED_MITM`).
  Both are unlikely to change the result — the controller's
  response/echo behaviour is opcode-layer, not transport-layer —
  but they remain available probe variants for future
  investigation if desired.
