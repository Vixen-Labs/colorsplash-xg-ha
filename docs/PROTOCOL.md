# ColorSplash XG BLE protocol (v1.0)

**Status:** v1.0 — effect opcode mapping is complete. Derived from four
HCI snoop captures on 2026-04-19 from a Samsung Galaxy Tab S9 Ultra,
with the fourth being a deliberate 5-second-gap calibration sweep whose
every action correlated to exactly one ATT Write with sub-200 ms delta.

See [`docs/CAPTURING.md`](CAPTURING.md) for how to produce inputs,
[`tools/decode_sweep.py`](../tools/decode_sweep.py) for the decoder, and
[`docs/PLAN.md`](PLAN.md#phase-1--reverse-engineering-7-issues) for the
broader Phase 1 context.

## Controller hardware

- Advertised local name: **`BGScripr`** (Silicon Labs BGScript runtime —
  the same engine used in Silicon Labs' EFR32/BGM reference BLE stacks).
- BD_ADDR OUI prefix: **SiliconLabor (`00:0b:57`)** — public identity
  address block assigned to Silicon Laboratories.
- The controller accepts exactly one central at a time (per
  `docs/CAPTURING.md` §2.3).

## BLE topology

| Handle | UUID | Role |
|---|---|---|
| `0x000d` (service) | `9fdc9c81-fffe-5d88-e511-e55714475f5d` | Vendor command service |
| `0x000e` (decl) | `0x2803` | Characteristic declaration |
| `0x000f` (value) | `4cabed4d-3f58-4429-b29c-f9a26205f28e` | **Command + state characteristic** |
| `0x0010` (CCCD) | `0x2902` | Client Characteristic Configuration for `0x000f` |

Both UUIDs are 128-bit vendor UUIDs. Standard Bluetooth SIG services
(Generic Access `0x1800`, Device Information `0x180a`) are also present
but carry no project-specific information.

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

## Known unknowns (deferred to later phases)

- **Pairing / bonding handshake bytes.** No SMP exchange was captured —
  the phone was already bonded in every session. A fresh
  "forget device → power-cycle controller → re-pair" capture would
  expose it. Not required for the ESPHome client.
- **Brightness / speed parameters.** Not observed. The XG app UI does
  not expose sliders on this firmware; whether the controller
  nevertheless accepts parameterized writes on `0x000f` (or another
  handle) is a PLAN.md Phase 4a probe target.
- **Controller-emitted state telemetry during shows.** CCCD is
  subscribed to indications, but whether the controller proactively
  emits state updates during a show cycle (beyond the per-write echo)
  is not yet tested. It would unlock the show-scrub timing approach in
  PLAN.md Phase 4b.
