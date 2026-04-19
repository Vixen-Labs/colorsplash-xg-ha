# Capturing BLE traffic from the ColorSplash XG Android app

Phase 1 of this project reverse-engineers the BLE protocol the official
ColorSplash XG app uses to talk to the LPL-XG-CTRL-1 controller. This
document is the step-by-step for producing a usable `btsnoop_hci.log` on
Android — start to finish, no prior experience assumed.

See [`docs/PLAN.md`](PLAN.md#phase-1--reverse-engineering-7-issues) for
where this fits in the broader plan, and the [action inventory in
#5](#appendix--action-inventory) for what to do during the session.

## TL;DR (for returning contributors)

```sh
# 1. enable in phone Developer Options → "Bluetooth HCI snoop log"
# 2. toggle Bluetooth OFF then ON (the logger only attaches on fresh BT init)
# 3. on phone: Settings → Bluetooth → forget any paired XG device
# 4. power-cycle the controller if you want a clean first-time-pair capture
# 5. run the session, recording clock time + action in SWEEP_LOG.md
date -u +%Y-%m-%dT%H:%M:%S.%3NZ   # note the start time
# 6. pull the log (modern Android)
adb bugreport bugreport.zip
unzip -j bugreport.zip 'FS/data/misc/bluetooth/logs/btsnoop_hci.log' \
  -d "captures/$(date +%F)-sweep"
# 7. verify in Wireshark: filter `btle || bthci_acl || bthci_evt`
```

If any step is unfamiliar, keep reading.

## What you need

- **Android phone**, Android 8.0 (Oreo) or newer. Older Androids work but
  the log location and behavior varies — see the
  [troubleshooting](#troubleshooting) table.
- **USB cable** that supports data (not charge-only) and can reach your
  computer.
- **`adb`** from Android SDK platform-tools.
  `brew install --cask android-platform-tools` on macOS.
- **ColorSplash XG Android app** installed on the phone.
- **LPL-XG-CTRL-1 controller**, powered, within BLE range (~5 m with
  line-of-sight; less through walls).
- **No other BLE central connected to the controller.** Only one client
  at a time — if the ESP32 bridge is already running, disable it for the
  duration of the capture.
- _(Optional but recommended)_ **Wireshark 4.x** to open the resulting
  `btsnoop_hci.log`.

## 1. Enable Bluetooth HCI snoop logging

### 1.1 Unlock Developer Options

On the phone:

1. **Settings → About phone** (exact name varies by OEM; on Samsung it
   may be **Settings → About phone → Software information**).
2. Tap **Build number** seven times. You should see a countdown toast
   and then "You are now a developer!"
3. Back up one level. **Developer options** is now visible (usually
   under **System** or directly under **Settings**).

### 1.2 Enable the logger

1. **Settings → Developer options → Bluetooth HCI snoop log → On**
   (some OEMs label it "Enable Bluetooth HCI snoop log").
2. **Cycle Bluetooth: turn it OFF, wait two seconds, turn it ON.**

   > **This is the single most common mistake.** The logger only
   > attaches when the Bluetooth stack initializes. If you enable the
   > setting while BT is already running, the current session is not
   > logged. Always toggle BT after changing the setting.

3. Verify the logger is active — pull an immediate empty-session log
   with `adb bugreport` (see §4) and confirm a `btsnoop_hci.log` is
   present inside. You don't have to analyze it, just confirm it exists.

### 1.3 On some OEMs: also enable "Always log everything"

Samsung and some Xiaomi builds add an extra "Disable absolute volume"
and "Enable Gabeldorsche" set of toggles; leave those alone. The only
required toggle is **Bluetooth HCI snoop log**.

## 2. Pre-session setup

### 2.1 First-time-connection capture (do this first)

The pairing exchange only happens when the phone and controller don't
already share a bond. If the phone has previously paired with the
controller, subsequent connects reuse the cached bond and the handshake
bytes will **not** appear in the log.

To get a clean first-time capture:

1. On the phone: **Settings → Bluetooth → (the XG device) → ⓘ → Forget
   device**. Repeat for any "XG", "LPL", or "ColorSplash" entry.
2. On the controller: power-cycle it (flip breaker / unplug 120 VAC
   mains for ~10 s). The controller has no reset button; power cycling
   is how you force it back to un-bonded advertising state. Verify by
   confirming the app is prompted to "Connect to XG controller" on the
   device-select sheet again.
3. Proceed to §3 for a full first-time sweep.

### 2.2 Steady-state capture

After the first-time sweep, you can do a second, shorter pass without
forgetting the device, to record what a normal "already bonded"
reconnect looks like. Label it clearly in `SWEEP_LOG.md`.

### 2.3 One client at a time

Only one BLE central can hold the controller. Before starting:

- Close the app on any other phone that might have previously connected.
- Power down the ESP32 bridge (unplug or disable the `ble_client`
  component) if it is already deployed.

If another client is already connected, the Android app will either
fail to see the device or see it but fail to connect.

## 3. Running the capture session

### 3.1 Set up the companion log

Create a session directory and a sweep log:

```sh
mkdir -p "captures/$(date +%F)-first-pair"
$EDITOR "captures/$(date +%F)-first-pair/SWEEP_LOG.md"
```

`captures/` is gitignored except for `captures/README.md`
(see [captures/README.md](../captures/README.md)), so nothing you put
there is at risk of being committed.

Record the session start timestamp in UTC:

```sh
date -u +%Y-%m-%dT%H:%M:%S.%3NZ
```

Paste that at the top of `SWEEP_LOG.md` as `session_start`. Record a
timestamp on every action line as you go.

### 3.2 Follow the action inventory

Work through the full action sweep from issue
[#5](#appendix--action-inventory). Keep sessions under 5 minutes per
run — Android OEMs cap the ring-buffered `btsnoop_hci.log` (4–16 MB is
typical) and older entries drop off the front silently.

For each action, record a line like:

```
2026-04-18T16:23:10.412Z  tap "Nova" effect tile
2026-04-18T16:23:24.018Z  tap Lock (bottom bar), color held cyan
2026-04-18T16:23:38.902Z  tap Return
```

Be specific. "Tapped Return" isn't enough if the preceding state
matters. `#5`'s acceptance requires Return behavior to be documented
across multiple contexts — capture enough context for that.

### 3.3 Wait between actions

Leave 2–5 seconds between UI actions. It makes the HCI log dramatically
easier to read afterward — each action ends up as a visually distinct
burst rather than a wall of interleaved packets.

### 3.4 When to start a new session

Start a fresh session (new `SWEEP_LOG.md`, new log pull) whenever:

- You cross the ~5-minute mark.
- You change from first-time-pair to steady-state mode.
- You see any unexpected disconnect in the app.
- You change phones or change Android versions.

## 4. Pull the log via ADB

### 4.1 Primary path (Android 8+)

On recent Android, `btsnoop_hci.log` lives inside a bug report:

```sh
# on the phone: Settings → Developer options → USB debugging = on
# connect via USB, accept the "allow this computer" prompt

adb devices                                # confirm the phone is listed
adb bugreport "captures/$(date +%F)-first-pair/bugreport.zip"

# Extract just the snoop log
unzip -j "captures/$(date +%F)-first-pair/bugreport.zip" \
  'FS/data/misc/bluetooth/logs/btsnoop_hci.log' \
  -d "captures/$(date +%F)-first-pair"
```

`adb bugreport` takes 30–120 s and produces a large zip. You only need
the one file inside it.

### 4.2 Fallback paths

Some OEMs expose the snoop log outside the bug report. If the primary
path finds nothing, try each of these in turn:

```sh
# Pixel / AOSP:
adb pull /data/misc/bluetooth/logs/btsnoop_hci.log .

# Older stock Android (pre-8) or some MediaTek devices:
adb pull /sdcard/btsnoop_hci.log .

# Some Samsung / Qualcomm builds:
adb pull /data/log/bt/btsnoop_hci.log .

# Xiaomi / MIUI:
adb pull /sdcard/MIUI/debug_log/common/btsnoop_hci.log .
```

`adb pull` on `/data/...` paths requires a rooted phone on most modern
builds — if it fails with "Permission denied," use the bug-report path
from §4.1.

### 4.3 If `adb` refuses to connect

- `adb devices` shows the phone as `unauthorized`: unlock the phone,
  accept the "Allow USB debugging?" prompt, re-run.
- `adb devices` shows nothing: USB cable is charge-only (swap it) or
  USB debugging is disabled (**Developer options → USB debugging**).
- `adb devices` shows the phone as `offline`: `adb kill-server &&
  adb start-server`.

## 5. Sanity-check the capture in Wireshark

Open the `btsnoop_hci.log` in Wireshark 4.x
(File → Open → select the file; Wireshark auto-detects the btsnoop
format).

Apply this display filter:

```
btle || bthci_acl || bthci_evt
```

You want to see:

- **Advertising packets** from the controller (periodic
  `ADV_IND` / `ADV_SCAN_IND`) — proves the phone was receiving the
  device before the connect.
- **`HCI_LE_Create_Connection`** command followed by
  **`HCI_LE_Connection_Complete`** event — proves the connect happened.
- **GATT Write Request** or **Write Command** packets during each
  action — these are the bytes we're going to decode into
  [`docs/PROTOCOL.md`](PROTOCOL.md).
- **(First-time only)** `SMP Pairing Request` / `Pairing Response`
  packets — proves the bonding handshake was captured.

If the log is empty or only contains events for other BT devices (your
earbuds, a fitness tracker), re-check §1.2 — the BT off/on cycle is
almost always the cause.

### 5.1 Align Wireshark timestamps with `SWEEP_LOG.md`

**View → Time Display Format → Date and Time of Day**. Packet
timestamps now show wall-clock, which lines up with the timestamps you
wrote in `SWEEP_LOG.md`. Expect 0.5–2 s of skew between the phone clock
and your laptop clock — not a problem, just don't be alarmed.

## 6. Storage and privacy

- `captures/` and `*.log` are gitignored; see
  [`.gitignore`](../.gitignore) and
  [`captures/README.md`](../captures/README.md). Nothing from a capture
  should end up in a commit.
- A `btsnoop_hci.log` may include:
  - The controller's MAC address (or its resolvable private address).
  - The Long-Term Key (LTK) from the pairing exchange. If redistributed,
    anyone with a nearby nRF sniffer could decrypt your traffic.
  - The phone's MAC address.
- **Do not paste raw bytes into an issue or PR without redacting.** If
  you need to share a sample, excerpt the relevant GATT write only
  (post-pairing, post-encryption) and scrub identifiers.

## 7. Troubleshooting

| Symptom                                                        | Likely cause                                                                                  | Fix                                                                                                  |
| -------------------------------------------------------------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `btsnoop_hci.log` is missing from bug report                   | Logger wasn't active when the BT stack started                                                | Toggle BT off/on after enabling the logger; repeat the capture (§1.2)                                |
| Log exists but has no packets for your target device           | Scanning/discovery disabled, or another central is holding the controller                     | Verify no other phone / the ESP32 bridge is connected; power-cycle the controller                    |
| Log has traffic but **no pairing packets** for a first-time    | Phone still has a cached bond                                                                 | Settings → Bluetooth → forget the XG device, power-cycle the controller, retry (§2.1)                |
| Controller MAC appears to change mid-session                   | LE Privacy — the controller uses a resolvable private address (RPA) that rotates every ~15 min | Expected; protocol decode handles this. Note the rotation in `SWEEP_LOG.md`                          |
| Log is far shorter than the session                            | Vendor cap on snoop log size (commonly 4 MB). Oldest entries dropped                          | Keep sessions short (<5 min) and pull the log immediately; split into multiple sessions              |
| `adb pull` on `/data/misc/bluetooth/logs/...` → Permission denied | Non-rooted phone on Android 8+                                                                | Use `adb bugreport` instead (§4.1). The bug report contains the same file with proper permissions    |
| `adb devices` shows `unauthorized`                             | You haven't accepted the host fingerprint on the phone                                        | Unlock the phone, accept the prompt, re-run                                                          |
| Wireshark shows the file but no packets decode as BLE          | File isn't actually btsnoop (wrong file extracted from bug report)                            | Verify you extracted `FS/data/misc/bluetooth/logs/btsnoop_hci.log` specifically, not some other file |

### Scope limit: HCI vs. link layer

Android HCI snoop captures everything above the HCI boundary —
commands, events, ACL traffic, SMP pairing messages — but not the raw
link-layer PDUs (LL control, data channel selection, connection
parameter updates as they appear on-air). If Phase 1 protocol decode
turns up a question that requires LL-level visibility (e.g., "exactly
when does the connection interval update fire?"), reach for the
nRF52840 sniffer — that's the subject of its own Phase 1 issue. Don't
chase LL answers in the HCI log; they're not there.

## Appendix — action inventory

The exact list of actions a capture session must exercise lives in
issue [#5 — Phase 1: Structured capture sweep of every app
action](https://github.com/swizzlevixen/colorsplash-xg-ha/issues/5).
That issue is the source of truth; a brief summary here so you don't
have to context-switch:

1. App cold-launch with controller unpaired / factory-new (capture the
   pairing exchange).
2. Tap **Status** card → **Select device** sheet → **Connect to XG
   controller**.
3. **Standby** toggle on → off → on, in three different prior states
   (solid color, running show, Lock-held mid-show).
4. Each of the 5 solid colors: Parisian Blue, Brazilian Red, Arctic
   White, Miami Pink, New Zealand Green.
5. Each of the 7 shows: Nova, Super Nova, Northern Lights, Tidal Wave,
   Patriot Dream, Desert Skies, Peruvian Paradise.
6. **Lock** in three contexts: on a solid color, mid-show, in standby.
7. **Return** after several sequences — document actual behavior.
8. **Disconnect**.
9. Reconnect, verify controller state is preserved.

Acceptance criteria for the capture session itself live on #5, not on
this document.
