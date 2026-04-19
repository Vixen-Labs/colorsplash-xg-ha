# ColorSplash XG BLE protocol (v0.1)

**Status:** v0.1 — derived from three HCI snoop captures on 2026-04-19 from
a Samsung Galaxy Tab S9 Ultra. The BLE topology and framing pattern are
confirmed; the byte-to-effect command table is partially confirmed and has
at least one cross-session ambiguity that will be resolved by a deliberate
calibration capture (see [Next steps](#next-steps)).

See [`docs/CAPTURING.md`](CAPTURING.md) for how to produce the inputs, and
[`docs/PLAN.md`](PLAN.md#phase-1--reverse-engineering-7-issues) for where
this document fits in the broader plan.

## Controller hardware

- Advertised local name: **`BGScripr`** (Silicon Labs BGScript runtime —
  the same engine used in Silicon Labs' EFR32/BGM reference BLE stacks).
- BD_ADDR OUI prefix: **SiliconLabor (`00:0b:57`)** — public identity
  address block assigned to Silicon Laboratories, confirming the chip
  family.
- The controller accepts exactly one central at a time (per
  `docs/CAPTURING.md` §2.3).

## BLE topology

| Handle | UUID | Role |
|---|---|---|
| `0x000d` (service) | `9fdc9c81-fffe-5d88-e511-e55714475f5d` | Vendor command service |
| `0x000e` (decl) | `0x2803` | Characteristic declaration |
| `0x000f` (value) | `4cabed4d-3f58-4429-b29c-f9a26205f28e` | **Command + state characteristic** |
| `0x0010` (CCCD) | `0x2902` | Client Characteristic Configuration for `0x000f` |

Both UUIDs are 128-bit vendor UUIDs (not Bluetooth SIG assigned). The
phone discovers these via standard service/characteristic discovery
(`Read By Group Type Request`, `Find Information Request`) on every
connect.

Standard Bluetooth SIG services are also present (Generic Access `0x1800`,
Device Information `0x180a`) but carry no project-specific information.

## Framing

On every connect the central:

1. Discovers services (handles `0x0001…0xffff`).
2. Writes **`0x0002`** to CCCD `0x0010` to enable **indications** for the
   command characteristic. This is the only CCCD write observed; no
   notifications are used.
3. Issues **`ATT Write Request`** (opcode `0x12`) packets to handle
   `0x000f`, each carrying a **single-byte value**.
4. The controller replies to each write with:
   - `ATT Write Response` (opcode `0x13`) — standard ATT ack.
   - `ATT Handle Value Indication` (opcode `0x1d`) on the same handle
     `0x000f`, echoing back the same one-byte value the central just
     wrote. This is the controller's state-change confirmation; the
     central ACKs it with `Handle Value Confirmation` (opcode `0x1e`).

No multi-byte payloads, no length prefix, no checksum, no sequence
counter observed. The entire command set is encoded in a single byte.

## Command / state bytes observed

Across the three sessions the following single-byte values appear on
handle `0x000f` (both outbound writes and inbound indication echoes):

```
0x00  0x07  0x08  0x09  0x0a  0x0b  0x0c  0x0d  0x0e
```

That's **9 distinct bytes** for **15 interactable UI elements** the app
exposes (5 colors + 7 shows + Lock + Return + Standby). Either some UI
elements do not produce writes (e.g. Return may be client-side only,
reflecting the last saved state without telling the controller), or the
byte range extends beyond what these captures exercised.

### Tentative mapping (NOT confirmed)

The table below is derived by correlating write timestamps with
`SWEEP_LOG.md` action lines. Deltas in the single-digit seconds indicate
a confident match; double-digit deltas mean the correlation drifted and
the mapping may be off by one action in either direction.

| Byte | Best-guess effect | Source session | Tap→write Δ | Confidence |
|---|---|---|---|---|
| `0x0b` | Patriot Dream (show) | `-steady-state` | 0.9 s | **High** |
| `0x0c` | Desert Skies (show) | `-steady-state` | 0.7 s | **High** |
| `0x0a` | Lock (on a solid color) | `-steady-state` | 5.9 s | Medium |
| `0x0d` | Standby | `-steady-state` | 4.0 s | Medium |
| `0x09` | Peruvian Paradise (show) | `-steady-state` | 8.5 s | Low |
| `0x08` | Northern Lights (show) | `-steady-state` | 12.0 s | Low |
| `0x07` | Return | `-steady-state` | 12.2 s | Low |
| `0x00` | Return (second / third invocation) | `-steady-state` | 2.2 s | Medium, but ambiguous (Return writing a variable byte is surprising) |
| `0x0e` | Return (another context) | `-first-pair` | 10.1 s | Low |

#### The cross-session conflict

In `-first-pair` the byte `0x0b` correlates to "tap color blue" with a
3.2 s delta, and in `-steady-state` the same byte correlates to "tap
Patriot Dream" with a 0.9 s delta. The 0.9 s delta is much more credible
than 3.2 s, so **either** (a) `0x0b` legitimately means two different
things in two contexts (unlikely for a single-byte command protocol),
**or** (b) the `-first-pair` correlation is drifting by one action and
blue's real opcode is a different byte. The calibration session below
will distinguish these.

## Observed behaviors (from SWEEP_LOG narratives + capture timing)

### Return

Return does **not** send a fixed opcode. In three distinct Return taps
across the captures, different bytes went out on the wire (`0x07`, `0x0e`,
`0x00`). This matches the user's observation that Return reverts to "the
last held solid color" — i.e. Return appears to re-issue the most
recently saved effect byte, not an opcode that literally means "return".

> _SWEEP_LOG `-first-pair`_: `tap Return (reverts to green)`
>
> _SWEEP_LOG `-steady-state`_: `tap retun (returns to locked Cyan)`

### Standby

Standby tapped immediately after app cold-launch does **not** turn the
light off. The user captured this in two independent sessions:

> _SWEEP_LOG `-first-pair`_: `standby tapped, but does not seem to work
> until another color or show is tapped`
>
> _SWEEP_LOG `-steady-state2`_: `(does not seem to work until we have
> tapped another color or show, like the app has no idea what's
> displaying)`

HCI-layer interpretation: in both sessions, the orphan Standby tap has
zero correlated writes within any reasonable window — the app simply
does not transmit anything when the user taps Standby without a known
last-state. Once the user taps a color or show, the app has a state to
persist, and subsequent Standby taps produce writes. **This is an
app-side bug, not a controller-side bug** — the HCI log is silent on the
orphan tap.

### Lock

Lock, tapped on a solid color, appears to "save" the displayed color so
that a subsequent Return or Standby→wake restores it. In `-steady-state`
the user tapped Lock while the controller was cycling Northern Lights
(arriving at cyan in the show), and then subsequent Return taps returned
the light to that cyan — strong evidence that Lock captures the
_current_ display state (including mid-show instantaneous color), not
just the active effect ID.

### Reconnect state preservation

Between sessions 2 and 3 the user disconnected and reconnected via the
app. The controller retained its Locked state (cyan) across the
reconnect — the first Return tap after reconnect returned to cyan
without requiring any state transfer from the central.

## Tools

- [`tools/capture-session`](../tools/capture-session) produces a capture
  session directory and the accompanying `SWEEP_LOG.md`.
- [`tools/decode_sweep.py`](../tools/decode_sweep.py) runs Wireshark's
  bundled `tshark` over the session's `btsnoop_hci.log`, filters for
  outbound ATT Write Requests to handle `0x000f`, auto-corrects the
  Samsung-tablet clock-skew quirk, and emits a markdown report that
  pairs each write with the nearest preceding `SWEEP_LOG` action.

## Known unknowns

- **Pairing bytes.** No SMP pairing exchange is in these captures — the
  phone was already bonded before any session started. A fresh
  "forget device + power-cycle the controller + re-pair" capture will
  expose the handshake.
- **Opcode → effect byte assignment** for 4 of 5 solid colors and
  several shows (see the Tentative Mapping table above).
- **Full value range.** Only bytes `0x00, 0x07-0x0e` have been observed.
  Whether `0x01-0x06` are valid effect bytes (presumably colors, since
  there are 5 of them plus a null/standby state) is not yet established.
- **Brightness / speed commands.** Not observed; the XG app does not
  appear to expose sliders on this firmware. PLAN.md Phase 4a
  contemplates probing this.
- **Controller-emitted state notifications during shows.** CCCD is
  subscribed to indications, but whether the controller proactively
  emits state updates _during_ a show (e.g., at color transitions) is
  not yet tested — it would unlock the show-scrub timing approach in
  PLAN.md Phase 4b.

## Next steps

1. **Calibration sweep.** A single ~2 minute session with deliberate 5
   second gaps between each tap: cold connect, each color in the issue's
   list order, each show in order, then Lock / Return / Standby. The 5
   second gaps eliminate the tap-to-write latency ambiguity so every
   byte pins down exactly. Planned as a follow-up capture for this
   phase.
2. **Fresh pairing capture.** With the controller power-cycled and the
   phone set to forget the device, one capture documents the bonding
   handshake.
3. **Show-transition capture.** Start a long show (e.g. Peruvian
   Paradise), leave it running for 30 seconds, and look for any
   controller-emitted indications on `0x000f` in the idle period.
