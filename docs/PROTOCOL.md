# ColorSplash XG BLE protocol (v1.4)

**Status:** v1.4 — adds a client-implementation requirement that
v1.3's audit missed: the BLE connection must stay open through the
fixture's visual transition window, not just long enough to receive
the indication echo. Discovered during issue #8's bleak reference
client work. Also incorporates Device Information Service findings
from the first Python connection: the controller exposes Manufacturer
("Silicon Labs") and Model ("BT121") strings but has no Firmware
Revision characteristic — closing the v1.3 Known unknown in the
negative.

Prior cross-verification sources stand: (a) four Android HCI snoop
captures on 2026-04-19 from a Samsung Galaxy Tab S9 Ultra (with a
deliberate 5-second-gap calibration sweep), (b) the Hermes-bytecode
sources of `com.jandjelectronics.colorsplashxgcontroller` decompiled
with `jadx` + `hermes-dec`, (c) an iOS capture from an iPhone running
the official XG app via Apple's PacketLogger, and now (d) a working
Python reference client (`tools/cli.py` via `bleak`) validated against
the real controller.

See [`docs/CAPTURING.md`](CAPTURING.md) for how to produce inputs,
[`tools/decode_sweep.py`](../tools/decode_sweep.py) for the decoder, and
[`docs/PLAN.md`](PLAN.md#phase-1--reverse-engineering-7-issues) for the
broader Phase 1 context.

## Controller hardware

- Advertised local name: **`BGScripr`** (Silicon Labs BGScript runtime).
- DIS Manufacturer: **`Silicon Labs`**.
- DIS Model: **`BT121`** — a Silicon Labs Bluetooth Smart module
  running BGScript firmware. BLE 4.2, 1 Mbps PHY only.
- BD_ADDR OUI prefix: The unit we tested advertises with OUI
  `84:BA:20` (not the Silicon Labs `00:0B:57` prefix shown in
  decompile / SIG registry data). The J&J board likely programs
  a custom BD_ADDR. Treat the local name — not the MAC — as the
  canonical "is this a ColorSplash controller?" test.
- The controller accepts exactly one central at a time (per
  `docs/CAPTURING.md` §2.3).
- **BT status LED**: a green LED labeled `BT` on the enclosure
  **blinks** while no central is connected (advertising state) and
  goes **solid** when a central establishes a GATT connection.
  Useful as an eyeball-level "am I connected?" check at the
  equipment pad without needing to open HA or read logs.

## Android client

The official app (`com.jandjelectronics.colorsplashxgcontroller`) is a
**React Native** application using **Hermes bytecode** and the
[`react-native-ble-manager`](https://github.com/innoveit/react-native-ble-manager)
library. All protocol logic lives in `assets/index.android.bundle`
inside the APK; the Java side is React Native's standard bridge. Tile
taps call `BleManager.write(peripheralId, serviceUUID, characteristicUUID, [buttonNumber])`
which maps to `BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT` and
issues an ATT Write Request (opcode `0x12`) — matching what the HCI
capture shows.

## BLE topology

| Handle | UUID | App name | Role |
|---|---|---|---|
| `0x000d` (service) | `5d5f4714-57e5-11e5-885d-feff819cdc9f` | `Main` | Vendor command service |
| `0x000e` (decl) | `0x2803` | — | Characteristic declaration |
| `0x000f` (value) | `4cabed4d-3f58-4429-b29c-f9a26205f28e` | `ButtonNumber` | **Command + state characteristic** (Write, Indicate) |
| `0x0010` (CCCD) | `0x2902` | — | Client Characteristic Configuration for `0x000f` |

Both vendor UUIDs are 128-bit and match the app's source exactly. The
app refers to the service as `Main` and the characteristic as
`ButtonNumber` — the latter is a strong design hint: the byte value on
the wire is the index of the tile (button) pressed. Standard Bluetooth
SIG services (Generic Access `0x1800`, Device Information `0x180a`) are
present on the controller but the app never reads them.

_Historical note:_ v1.0 of this document listed the service UUID in
its wire little-endian form (`9fdc9c81-fffe-5d88-e511-e55714475f5d`).
v1.1 corrects it to the canonical form used by the app and Bluetooth
SIG conventions. Both strings encode the same 128 bits.

## Framing

On every connect the central:

1. Discovers services (handles `0x0001…0xffff`).
2. Writes **`0x0002`** to CCCD `0x0010` to enable **indications** for the
   command characteristic. No notifications are used.
3. Issues **`ATT Write Request`** (opcode `0x12`) packets to handle
   `0x000f`, each carrying a **single-byte value**.
4. The controller replies to each write with:
   - `ATT Write Response` (opcode `0x13`) — standard ATT ack.
   - `ATT Handle Value Indication` (opcode `0x1d`) on the same handle
     `0x000f`, echoing back the same one-byte value — the controller's
     state-change confirmation. The central ACKs it with
     `Handle Value Confirmation` (opcode `0x1e`).

No length prefix, checksum, or sequence counter. Every wire message is
a strict single-byte request / single-byte echo confirmation.

Exact wire format for a tile tap (13 bytes total including HCI ACL +
L2CAP framing):

```
02 02 00 08 00 04 00 04 00 12 0f 00 XX
                          │  │  │  └── ATT value (1 byte: the opcode)
                          │  │  └─┴─── ATT handle 0x000f (little-endian)
                          │  └─────── ATT opcode 0x12 (Write Request)
                          └ L2CAP CID 0x0004 (ATT)
```

## Reference client recipe

This is the minimum sequence a fresh client implementation must
execute. Every step is backed by the sections below and by the
captures cited in §Sources of evidence.

1. **Scan** for a peripheral advertising the local name `BGScripr`.
   The advertising payload also carries the 128-bit service UUID
   listed in the BLE topology table, so a service-UUID filter works
   as well — see §BLE topology.
2. **Connect** to it. No pairing / bonding is required; see
   §Authentication / bonding.
3. **Discover services** and locate the command characteristic at
   UUID `4cabed4d-3f58-4429-b29c-f9a26205f28e`. Its properties are
   Write + Indicate; see §BLE topology for handle numbers.
4. **Subscribe to indications** by writing `0x0002` to that
   characteristic's CCCD descriptor.
5. **Send commands** by issuing `ATT Write Request` (opcode `0x12`)
   with a **single-byte** payload drawn from the table in §Effect
   opcode table. The controller responds with `ATT Write Response`
   (opcode `0x13`, standard ack) and, shortly after, a
   `Handle Value Indication` echoing the same byte back on the
   command characteristic. Treat the **indication echo** as the
   authoritative "state applied" signal (that's what the official
   app does — see §Controller-to-central indications). ACK the
   indication with `Handle Value Confirmation` (opcode `0x1e`).
6. **Hold the connection open ≥ 8 seconds after the write** before
   disconnecting. The controller echoes its indication in ~60 ms but
   the fixture's visible transition requires the BLE link to stay
   alive for the full window or the transition aborts. See
   §The BLE link must stay open through the visual transition.
7. **Disconnect** when done. Reconnecting preserves the controller's
   last locked state, so the client does not need to re-apply state
   on reconnect; see §Reconnect preserves state.

No multi-byte payloads, no length prefix, no checksum, no sequence
counter, no encryption, no MTU negotiation requirement — a single
byte on a single characteristic does everything.

A working Python implementation of this recipe lives in
[`tools/cli.py`](../tools/cli.py) (`bleak`-based).

## Effect opcode table

Complete — all 15 UI elements have confirmed opcodes from the
2026-04-19 calibration sweep. Every mapping below was verified with
sub-200 ms tap-to-write delta, with the sole exception of New Zealand
Green (see note).

### Solid colors

| Byte | Tile name | Tap→write Δ |
|---|---|---|
| `0x08` | Parisian Blue | 140 ms |
| `0x0a` | Brazilian Red | 142 ms |
| `0x0b` | Arctic White | 95 ms |
| `0x0c` | Miami Pink | 135 ms |
| `0x09` | New Zealand Green | 6.1 s (see note) |

_Note on Green:_ the `0x09` write for "color green" arrived 6.1 s after
the tap, plus four repeated `0x09` writes at ~200 ms intervals
afterward. This burst pattern looks like an ATT retry (controller did
not acknowledge promptly, phone retransmitted). The byte value is still
unambiguous — every retransmit carried the same payload.

### Shows

| Byte | Tile name | Tap→write Δ |
|---|---|---|
| `0x07` | Nova | 207 ms |
| `0x02` | Super Nova | 184 ms |
| `0x03` | Northern Lights | 188 ms |
| `0x04` | Tidal Wave | 129 ms |
| `0x05` | Patriot Dream | 166 ms |
| `0x06` | Desert Skies | 119 ms |
| `0x01` | Peruvian Paradise | 182 ms |

### Controls

| Byte | Control | Tap→write Δ |
|---|---|---|
| `0x0d` | Lock | 106 ms |
| `0x0e` | Return | 30 ms |
| `0x00` | Standby | write ≈400 ms _before_ SWEEP_LOG entry (user tapped, then typed the label) |

## iOS cross-check (2026-04-19)

The opcode table above was originally derived from Android HCI captures
and cross-checked against the decompiled Android app. To rule out
any platform-gated divergence — e.g. an iOS-only framing byte, a
different characteristic UUID, or a platform-specific pairing
sequence — we captured the same sweep from an iPhone running the
iOS version of the XG app, using Apple's PacketLogger (see
[`docs/CAPTURING.md`](CAPTURING.md) §9).

**Result: identical protocol.** Five taps in the order
Parisian Blue → Nova → Lock → Return → Standby produced exactly five
`ATT Write Request` packets to handle `0x000f`:

| Expected (v1.1 table) | iOS captured |
|---|---|
| `0x08` Parisian Blue | `0x08` |
| `0x07` Nova | `0x07` |
| `0x0d` Lock | `0x0d` |
| `0x0e` Return | `0x0e` |
| `0x00` Standby | `0x00` |

Same two 128-bit UUIDs
(`5d5f4714-57e5-11e5-885d-feff819cdc9f` service,
`4cabed4d-3f58-4429-b29c-f9a26205f28e` characteristic). Same
Write Request opcode (`0x12`). Same 1-byte value framing. Same
`Handle Value Indication` echo confirmation pattern.

One small incidental observation: iOS-side MTU exchange settles at
**23 bytes** (BLE minimum). That is a _controller-side_ cap — iOS
CoreBluetooth's request for a larger MTU is refused by the firmware.
Android HCI captures show the same cap. Neither platform needs a
higher MTU since every command fits in a single byte of ATT value.

No platform-gated behaviors were observed; the iOS app is a React
Native / Hermes build of the same JS codebase confirmed in the #3
decompile. Identical wire protocol is the expected outcome and is
now empirically confirmed.

## Authentication / bonding

**None.** The decompiled app contains no pairing or bonding logic —
no `BluetoothDevice.createBond`, no SMP passkey entry, no Just Works
confirmation UI. The app discovers, connects, and immediately begins
GATT operations. Any bonding that happens is transparently handled by
the Android BT stack using Just-Works / no authentication, and is
optional: the controller will accept ATT writes whether or not a bond
exists.

The user's empirical observation that "the Connect flow has no password
or confirmation" is confirmed at the code level.

## Controller-to-central indications

The app subscribes to indications on `0x000f` during `onServicesDiscovered`
and implements a handler (`BleManagerDidUpdateValueForCharacteristic`)
that reads the first byte of each indication value. The handler
treats:

- `14` (= `0x0e`, `Return`) as an "effect rolled back" event — updates
  UI to un-highlight Lock/Return toggles.
- `13` (= `0x0d`, `Lock`) as a "locked" event — highlights Lock on the UI.
- Anything else (a tile byte) as a "new effect active" event — highlights
  that tile and un-highlights Lock/Return.

This explains why every write is echoed back by the controller — the
echo is the **authoritative UI-state signal** from the controller. The
app does not assume its own write succeeded until it receives the
echo. This is important for a reference implementation: treat the
indication as the ack, not the ATT Write Response.

### Unsolicited indications on reconnect (2026-04-20)

During the Phase 2 #12 watchdog test (10 power-cycle trials of the
controller), the ESP32 saw a `0x0e` (Return) indication arriving
~13-18 seconds **after** each successful reconnect, with no
preceding central-side write. The central had neither sent `0x0e`
nor any other byte in that window — it's the controller itself
emitting an unsolicited Return indication on a schedule after a
fresh connection comes up.

The interpretation fits the app's Return handler: "effect rolled
back." The controller appears to be asserting "I'm at my last
locked state now" after a reconnect sequence finishes stabilising.

Implication for clients: an incoming indication on `0x000f` is NOT
always an echo of a recent write. Treat it as a pure state-change
signal and ignore the "do I have a matching outbound write?" check.
This also partially resolves the v1.4 Known-unknown about
proactive state indications — the controller does emit at least
one unsolicited indication (Return) on its own cadence.

## Observed behaviors

### Return is a dedicated opcode (`0x0e`)

Return is a first-class command with its own opcode, not an app-side
re-issue of the last saved byte (the v0.1 document claimed the latter;
v0.1 was wrong, based on a miscorrected clock skew). The "reverts to
last locked solid color" semantics are implemented on the **controller**
side: the controller stores a "last locked" effect and Return tells it
to replay that effect. The central sends exactly `0x0e` every time,
regardless of what the last locked state was.

### Standby (`0x00`) behavior on cold launch

The user observed in two independent sessions that tapping Standby
immediately after app cold-launch does not turn the light off until
another color or show has been tapped:

> _SWEEP_LOG `-first-pair`_: `standby tapped, but does not seem to work
> until another color or show is tapped`
>
> _SWEEP_LOG `-steady-state2`_: `(does not seem to work until we have
> tapped another color or show, like the app has no idea what's
> displaying)`

The user's interpretation — "like the app has no idea what's
displaying" — is consistent with an app-side state bug: the phone's UI
appears to suppress the Standby write until it has a known last-applied
state to persist. Independent of the wire protocol, the bug is
observable at the UI level on every cold launch.

### Lock (`0x0d`) captures instantaneous display state

Lock tapped mid-show saves the color the fixture is currently
displaying at that instant — including interpolated intermediate colors
during a show transition. The user demonstrated this in
`-steady-state` by tapping Lock mid-Northern Lights when the fixture
arrived at cyan; subsequent Return (`0x0e`) taps then took the fixture
back to that cyan even across disconnect/reconnect boundaries.

### Reconnect preserves state

Between capture sessions 2 and 3 the user disconnected and reconnected
via the app. The controller retained its Locked state (cyan) across the
reconnect without any state-transfer writes from the central. Locked
state is persistent on the controller, not merely cached on the phone.

### The BLE link must stay open through the visual transition

**This is the single most important behavioral constraint for a
client implementation** and is _not_ inferrable from HCI captures of
the official apps, because those apps stay continuously connected for
the entire user session and therefore never exercise the edge case.

Discovered during #8's bleak client work: if the central writes a
command byte and disconnects promptly (say, within 1 second), the
controller accepts the write and echoes the Handle Value Indication
in the usual ~60 ms — but the fixture's visible transition is
aborted. The fixture goes dark at the start of the transition and
stays dark; no new color illuminates. Subsequent connect+write pairs
can compound this: the controller ends up in a partially-resolved
state that may or may not honor the next command visually, and when
the client finally keeps the connection open long enough, the fixture
may land on a byte value from an earlier confused write rather than
the latest one.

Empirical fix: hold the BLE connection open for **at least 8 seconds
after the write** (covering the §Visual transition latency upper
bound). The `tools/cli.py` reference client defaults `--hold 8` and
that reliably produces the correct visual state change.

Implications for implementors:

- **Fire-and-disconnect patterns don't work.** Don't write and
  immediately call `disconnect()`.
- **Long-lived sessions are the happy path.** An ESPHome `ble_client`
  that keeps the connection open indefinitely (reconnecting on drop)
  matches the official apps' model and avoids this entirely.
- **If you're building a CLI or script that reconnects per-command,
  add at least an 8-second post-write hold.** The Python reference
  client does this by default.

### Visual transition latency (controller-side, not BLE)

The wire protocol is fast: the controller's Handle Value Indication
echoes a write's byte back in ~60 ms (§Controller-to-central
indications). The **physical fixture's response is not**. After any
effect-change command, the pool light goes **dark** for ≤0.5 s, stays
dim for several seconds, and then re-illuminates at the new state.

**Measured values** (2026-04-19, camera-based timing via
`tools/measure_latency_live.py`, N=13 transitions in a single sweep):

| Transition type | Total (s), mean | Total (s), range |
|---|---:|---:|
| Solid color → solid color (4 samples) | 8.53 | 7.64 – 9.25 |
| Solid → show start (first stable brightness) | ~4–10 | 3.46 – 10.59 |
| Any → Standby | — | <1 (fixture simply stops illuminating) |

Onset (write → first brightness drop): **consistently < 0.5 s**,
confirming the controller acts on the write almost immediately. The
5-10 s is entirely the fixture's own transition envelope.

Show transitions are noisier: because shows cycle their brightness
internally, the "stable" detection catches transient plateaus during
the cycle rather than a single settled value. Treat show timings as
a lower bound on "how long until the show is clearly running."

Standby looks artificially fast (0.39 s) because it's the BLE write
latency itself — the fixture had already dimmed at the time it hit
nadir, so there's no visible "re-illuminate" phase.

The measured values agree with the earlier user-observed range
(7-9 s for solid-to-solid transitions) and replace v1.3's "5-8 s
estimate." Raw video + log under `captures/2026-04-19-latency/`
(gitignored).

Implications for implementors:

- **Do not treat visual darkness as a failure.** The BLE indication
  echo is the authoritative "command accepted" signal. If the client
  retries based on "the light went out," it will double-send.
- **Expect a wall-clock-to-visible-state lag.** Anything that wants
  to confirm a state applied _in the physical world_ (HA automations,
  a user's eyes) must tolerate at least 8 seconds of settling time.
- **Phase 4b show-scrub implications.** Any Hold / Lock issued during
  the blackout window will miss the intended color — the fixture
  isn't showing a color during the dark period. Scrub timing must
  fire **after** the new effect has re-illuminated, not at t=0 from
  the start-show command.
- **Bleak reference client test plan.** Automated tests should wait
  at least 8 s between commands before asserting visible state, or
  gate on the indication echo and not attempt visual verification
  from software at all.

## Clock skew — a capture gotcha

The Samsung Tab S9 Ultra's BT snoop subsystem records timestamps as if
the phone's local time were UTC. For a phone in PDT (UTC-7) during
daylight saving, that means every btsnoop timestamp is
**7 hours behind** the true UTC wall clock. The SWEEP_LOG timestamps,
captured by Python on the laptop via `datetime.now(timezone.utc)`, are
genuinely UTC. To align the two, apply `--skew -25200` to
`decode_sweep.py` on captures from this tablet.

Additional caveats observed:
- The phone's BT clock can drift a few seconds to a few minutes
  between sessions. If `--skew -25200` gives correlation deltas of tens
  of seconds, try small adjustments around that value.
- The HCI snoop ring buffer typically holds several hours of BT
  activity, not just the current session. `decode_sweep.py`'s orphan
  filter excludes pre-session and post-session writes based on the
  action timestamps in `SWEEP_LOG.md`.

## Show color gradients (bonus from the decompile)

The app ships the exact RGB gradient each show cycles through,
embedded as hex color arrays alongside the tile's `id` and `name`.
This is a gift to PLAN.md Phase 4b (show-scrub color picker) — the
target color sequence per show is known without needing to
characterize each show on video first.

| Show | Byte | Gradient hex (from app source) |
|---|---|---|
| Nova | `0x07` | `#FEEA00 #71CD2E #02ADF9 #1649D5 #DC0BB3 #FFBF1C #17B63F #00B2E1 #205ADB #CB00A9` |
| Super Nova | `0x02` | same as Nova |
| Northern Lights | `0x03` | `#FD3000 #FFC000 #54CD00 #01C2F4 #0E65F7 #FD01AE` |
| Tidal Wave | `0x04` | 12-step blue-to-cyan gradient `#00A351 … #0675AB` |
| Patriot Dream | `0x05` | `#E32139 #FFFFFF #398CC6 #E32139 #FFFFFF #398CC6` (red/white/blue, 2× loop) |
| Desert Skies | `0x06` | 23-step amber → magenta gradient |
| Peruvian Paradise | `0x01` | 33-step white → magenta → teal gradient |

These are the app's reference colors — what the fixture actually emits
during playback may differ slightly depending on the controller's DAC
and the pool light's LED spectrum, but the sequence / relative timing
is now known. The hex lists are intentionally not reproduced in full
here to keep this document focused; they live verbatim inside
`assets/index.android.bundle` of the app.

### Empirical observations: Nova / Super Nova relationship

The "same as Nova" annotation on Super Nova has been verified end-to-end via the linearized
sRGB capture pipeline (see `docs/RGB_EXPERIMENT.md` §Calibration) and a 3-replay determinism
test in `tools/show_colors_replay_Nova.json`:

- **Nova plays a deterministic 16-color sequence**, ~1.93 s per color, ~31 s loop. Three
  independent Nova starts produced identical color sequences with cross-run mean RGB
  drift of just 1-2 channels (camera-noise floor) and max 7.5.
- **Super Nova plays the same 16-color sequence at ~5.36× the rate** (median hold ~367 ms
  vs Nova's ~1966 ms). First-16 hold colors line up segment-for-segment between the two
  shows; palette histograms have Jaccard overlap 0.45 with identical top-10 percentages
  (next-highest cross-show pair is 0.32).
- **Nova's gradient is NOT a smooth blend.** Each color is held as a solid step, with a
  brief AC-interrupt-driven blackout (~30 ms) between steps. The 10-color hex list above
  is a stylized representation for the app's button gradient, not the actual emission
  sequence — the real fixture script visits ~16 distinct colors per cycle (more than the
  10 hex stops, with several reds/blues at slightly different intensities).

**Implications for the picker LUT:**
- Nova is stored in the LUT as a **discrete-step table** (one entry per color hold,
  `t_ms` placed at the hold's midpoint so the Lock byte fires inside the steady color,
  not during a transition).
- Super Nova is **excluded from the LUT entirely**. The two shows visit the same colors,
  but Nova's slower holds give the BLE Lock byte a much wider window (~2 s) to land on
  the intended color than Super Nova's ~370 ms. The "Super Nova" effect remains
  available through HA's effect dropdown — only the color-pick → Lock targeting path
  excludes it.

See `tools/generate_show_lut.py:DISCRETE_STEP_SHOWS` and `LUT_EXCLUDE_SHOWS`.

## Sources of evidence

Each claim in this document is supported by at least one of the
following captures or reverse-engineering artifacts. All of them are
reproducible with the procedures in
[`docs/CAPTURING.md`](CAPTURING.md).

- **Android HCI snoop captures** (Samsung Galaxy Tab S9 Ultra,
  2026-04-19) under `captures/2026-04-19-first-pair/`,
  `-steady-state/`, `-steady-state2/`, and `-steady-state3/`
  (calibration). Source of the opcode table mapping, the
  observed behaviors section, the clock-skew gotcha, and every
  Android-side claim. Decoded with
  [`tools/decode_sweep.py`](../tools/decode_sweep.py).
- **Android APK decompile** of
  `com.jandjelectronics.colorsplashxgcontroller` (React Native /
  Hermes) via `jadx` + `hermes-dec`. Source of the characteristic's
  app-side identifier `ButtonNumber`, the service UUID in its
  canonical form, the authoritative opcode-to-tile mapping
  (`{id, name}` pairs in the `LIGHTS` array), the absence of
  pairing code, and the embedded show color gradients. Per
  issue #3, the APK and decompiled source are _not_ committed to
  this repo.
- **iOS PacketLogger capture** (iPhone, 2026-04-19) under
  `captures/2026-04-19-ios-calibration/session.pcap.log` (btsnoop
  v1 format despite the `.pcap.log` suffix). Source of the iOS
  cross-check section — confirmed byte-for-byte identical protocol.
- **nRF52 over-the-air sniffer capture** (2026-04-19) under
  `captures/2026-04-19-nrf-validation/session.pcap`. Source of the
  link-layer confirmation that the phone's ATT Write Requests
  appear on-air as expected. See `docs/CAPTURING.md` §8 for its
  packet-loss caveats.

`captures/` is gitignored; these paths are pointers, not commits.
Each directory contains the raw capture file plus a `SWEEP_LOG.md`
narrating the user-side action sequence, which is how the behavioral
claims in §Observed behaviors are correlated to on-wire bytes.

## Known unknowns (deferred to later phases)

- **First-command-after-idle from an unbonded central triggers a
  default effect instead of the requested byte** (investigated in #33;
  verified reproducer). After an extended idle (≥~1 min), the first
  tile command sent over a fresh BLE connection from a central that
  is not bonded to the controller causes the fixture to enter some
  effect that's not what we wrote — **Nova most often, occasionally
  Patriot Dream or another show**. The BLE indication echoes carry
  the byte we wrote, so the controller receives the intended command
  at the wire level; the fixture's interpretation is what diverges.
  Subsequent writes on the same already-warm connection land
  correctly.

  **Why the official apps don't hit this:** iOS / Android bond to the
  controller automatically on first connect (Just Works pairing, no
  user prompt because the BT121 doesn't demand a pin). Bonded
  centrals don't trigger the default-effect behavior. The official
  apps are _always_ bonded after their very first successful
  connection.

  **Why our bleak reference client on macOS can't fix this:** bleak's
  explicit `client.pair()` returns `"Pairing is not available in Core
  Bluetooth"`. macOS CoreBluetooth exposes **no public API for
  initiating bonding** — it only bonds reactively when the peripheral
  demands an encrypted link. The XG controller never demands
  encryption, so macOS never bonds with it, and there's no
  bleak-level knob that changes this. We tried `BleakClient(pair=True)`
  (silent no-op), `client.pair()` (explicit failure), post-connect
  settle delays 0.9-5 s (inconsistent), post-subscribe delays 0-5 s
  (inconsistent: 2 s worked once out of ~8 attempts across values),
  `--no-subscribe` (failed), `--read-first` (failed), targeted
  service discovery (failed), and double-write with 250 ms gap
  (both writes absorbed by the same quirk — failed).

  **Why ESPHome won't hit this:** ESP-IDF exposes a full bonding API
  and `esphome ble_client` bonds on first connect, storing the bond
  in NVS. Phase 2 runs one bonded connection for the device's
  lifetime. This quirk is therefore a **bleak-on-macOS-only**
  limitation, not a protocol issue or a Phase 2 blocker.

  **Workaround for `tools/cli.py` users:** if the first command after
  a fresh connect produces the wrong effect, re-run the command.
  The second invocation's connection will still be fresh-unbonded
  (each CLI invocation is a new connection), so this doesn't fully
  escape the quirk, but a re-run often lands differently because the
  controller's internal timing/state has shifted. For reliable
  command execution, keep one long-lived connection open across
  many commands (which is what ESPHome does natively).
- **Controller firmware revision string.** _Resolved 2026-04-19_:
  the controller **does not expose** a Firmware Revision String
  characteristic (UUID `0x2a26`) at all. The bleak client in #8 reads
  its Device Information Service and finds only:
  - Manufacturer Name String (`0x2a29`): `"Silicon Labs"`
  - Model Number String (`0x2a24`): `"BT121"`
  Serial Number, Hardware Revision, Firmware Revision chars are all
  absent. BT121 is a Silicon Labs Bluetooth Smart module running a
  BGScript application, which matches the advertised `"BGScripr"`
  local name. No firmware version is surfaced over BLE; identifying
  a specific firmware build would require asking J&J Electronics
  directly or physically accessing the module's debug interface.
- **Brightness / speed parameters.** Not observed in HCI traffic and
  not emitted by the app's `setPressedButton` path. The XG app UI does
  not expose sliders on this firmware; whether the controller
  nevertheless accepts parameterized writes on `0x000f` (or another
  handle) is a PLAN.md Phase 4a probe target. The decompile rules out
  any _app-side_ such code path, so Phase 4a will be genuine firmware
  probing, not just UI bypass.
- **Show-transition indications.** CCCD is subscribed but the only
  inbound indications observed are the per-write echoes. Whether the
  controller proactively emits state updates _during_ a show cycle
  (e.g. at each color transition) is still not tested. It would
  unlock the show-scrub timing approach in PLAN.md Phase 4b —
  preferable to the naive wall-clock timing now that we know the
  color sequences.
- **Pairing handshake.** The app issues no pairing and the controller
  accepts unbonded writes. A fresh "forget device → power-cycle
  controller" HCI capture would prove whether the controller
  initiates SMP under any circumstance. Not required for the ESPHome
  client, which can mirror the app's no-auth behavior.
