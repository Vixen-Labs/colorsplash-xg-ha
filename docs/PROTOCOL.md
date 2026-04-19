# ColorSplash XG BLE protocol (v0.2)

**Status:** v0.2 — derived from four HCI snoop captures on 2026-04-19 from
a Samsung Galaxy Tab S9 Ultra. The BLE topology and framing pattern are
confirmed. The byte-to-effect mapping is **not yet solved** — a calibration
capture with systematic tile tapping revealed that the single-byte values
appearing on handle `0x000f` during sessions do **not** correspond 1:1 to
user taps. See [The mapping problem](#the-mapping-problem) below.

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

The full set of one-byte values seen on handle `0x000f` across the four
captures is:

```
0x00  0x01  0x02  0x03  0x04  0x05  0x06  0x07
0x08  0x09  0x0a  0x0b  0x0c  0x0d  0x0e
```

That's **15 distinct bytes**, which matches the **15 interactable UI
elements** (5 solid colors + 7 shows + Lock + Return + Standby) — strong
evidence that one byte = one UI element, even though the mapping itself
is not solved.

## The mapping problem

The byte-to-effect mapping cannot be recovered from HCI snoop alone.
Three observations establish this:

1. **Every session's in-window writes produce the same ordered byte
   sequence**: `08, 0a, 0b, 0c, 09, 07, 0d, 0e, 00` (9 bytes),
   regardless of which tiles the user actually tapped. Session 1 had
   the user tapping colors; session 2 had the user tapping shows; the
   calibration session had the user tapping all 15 UI elements in a
   deliberate order. All three produced the same 9-byte sequence in the
   same order. A byte sequence that does not vary with input cannot be
   the identity of the input.
2. **The remaining bytes `0x01-0x06` only appear in post-session
   autonomous activity.** After a capture session ends, the app
   continues to reconnect and send writes periodically over the
   following hours, cycling through the full byte range. The user
   confirms none of this activity was driven by intentional taps.
3. **There is no other BLE endpoint carrying commands.** Writes occur
   only to handles `0x000f` (commands) and `0x0010` (CCCD subscribe).
   No other characteristic receives traffic during a session. If user
   taps caused BLE writes, those writes would have to appear on
   `0x000f` — and they'd have to be distinguishable from the
   autonomous sequence, which they are not.

### Two plausible explanations

**(a) The app writes an identical sync / init sequence on every connect,
and our captures happen to end before real user-tap writes get sent.**
The handshake sequence would explain the invariance across sessions.
This is weakened by the calibration session spanning 4 minutes with 15
deliberate taps — enough time for tap-driven writes to appear if they
exist at the rate one per tap.

**(b) User taps do not produce one-byte writes. The app uses some other
mechanism to communicate taps — possibly ATT Prepare Write /
Execute Write (long writes) the filter is missing, possibly a different
characteristic not yet discovered, or possibly the controller itself is
driving state changes based on something other than the user's phone.**
This is weakened by the observed 60 ms write-to-indication echo pattern,
which looks exactly like a command-response protocol should look.

Both hypotheses are consistent with the captured data. Distinguishing
them requires looking at the Android APK (PLAN.md Phase 1 issue #2) to
see what the app actually sends when a tile is tapped. The BLE
service/characteristic classes the app uses, the packet builders, and
any framing constants will resolve this unambiguously.

## What the HCI data _does_ pin down

Independent of the mapping problem, these structural claims are
supported by the captures:

- Handle `0x000f` is the command + state characteristic. All commands
  and all state-indications flow through this one characteristic.
- Write framing is a single value byte, no opcode header, no length
  prefix, no checksum, no sequence counter.
- The controller confirms each write with a Handle Value Indication
  echoing the same value byte back ~60 ms later — a strict ping-pong
  transaction per command.
- The byte space `0x00-0x0e` covers exactly the number of UI
  interactable elements, suggesting the encoding is a flat index across
  all of them.

## Observed behaviors (from SWEEP_LOG narratives)

These observations come from the user's in-session narrations and
visual observation of the physical fixture. They do not depend on the
unresolved byte mapping.

### Return

User-visible behavior: tapping Return after a show or color reverts the
light to the most recently saved solid color — i.e. Return is a "revert
to locked state" operation, not a navigation primitive.

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

The user's interpretation — "like the app has no idea what's displaying"
— is consistent with an app-side state bug: the phone's UI tracks a
"last applied state" and refuses to issue a Standby until it has one.
Independent of the byte mapping, the bug is observable at the UI level
on every cold launch.

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

1. **APK decompile (PLAN.md Phase 1 issue #2) is now the critical path.**
   Running `jadx` over the ColorSplash XG APK will expose the BLE
   service class, the specific bytes the app writes on each tile tap,
   and any framing / state logic that explains why the HCI capture looks
   the way it does. This is likely to resolve the mapping in an afternoon.
2. **Fresh pairing capture.** With the controller power-cycled and the
   phone set to forget the device, one capture documents the SMP bonding
   handshake. Orthogonal to the mapping problem but still on #5's list.
3. **Show-transition capture.** Start a long show (e.g. Peruvian
   Paradise), leave it running for 30 seconds, and look for any
   controller-emitted indications on `0x000f` in the idle period. If the
   controller autonomously reports show-frame transitions, PLAN.md
   Phase 4b (show-scrub) gets a clean timing source.
