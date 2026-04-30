# Capturing BLE traffic from the ColorSplash XG Android app

Phase 1 of this project reverse-engineers the BLE protocol the official ColorSplash XG app uses to talk to the LPL-XG-CTRL-1 controller. This document is the step-by-step for producing a usable `btsnoop_hci.log` on Android — start to finish, no prior experience assumed.

For link-layer questions (connection interval updates, channel hops, timing questions) that HCI snoop cannot answer, see §8 for the over-the-air capture path using the Adafruit Bluefruit LE Sniffer.

See [`docs/PLAN.md`](PLAN.md#phase-1--reverse-engineering-7-issues) for where this fits in the broader plan, and the [action inventory in #5](#appendix--action-inventory) for what to do during the session.

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

- **Android phone**, Android 8.0 (Oreo) or newer. Older Androids work but the log location and behavior varies — see the [troubleshooting](#troubleshooting) table
- **USB cable** that supports data (not charge-only) and can reach your computer
- **`adb`** from Android SDK platform-tools. `brew install --cask android-platform-tools` on macOS
- **ColorSplash XG Android app** installed on the phone
- **LPL-XG-CTRL-1 controller**, powered, within BLE range (~5 m with line-of-sight; less through walls)
- **No other BLE central connected to the controller.** Only one client at a time — if the ESP32 bridge is already running, disable it for the duration of the capture
- _(Optional but recommended)_ **Wireshark 4.x** to open the resulting `btsnoop_hci.log`

## 1. Enable Bluetooth HCI snoop logging

### 1.1 Unlock Developer Options

On the phone:

1. **Settings → About phone** (exact name varies by OEM; on Samsung it may be **Settings → About phone → Software information**).
2. Tap **Build number** seven times. You should see a countdown toast and then "You are now a developer!"
3. Back up one level. **Developer options** is now visible (usually under **System** or directly under **Settings**).

### 1.2 Enable the logger

1. **Settings → Developer options → Bluetooth HCI snoop log → On** (some OEMs label it "Enable Bluetooth HCI snoop log").
2. **Cycle Bluetooth: turn it OFF, wait two seconds, turn it ON.**

   > **This is the single most common mistake.** The logger only
   > attaches when the Bluetooth stack initializes. If you enable the
   > setting while BT is already running, the current session is not
   > logged. Always toggle BT after changing the setting.

3. Verify the logger is active — pull an immediate empty-session log with `adb bugreport` (see §4) and confirm a `btsnoop_hci.log` is present inside. You don't have to analyze it, just confirm it exists.

   > Before `adb bugreport` will work, **USB debugging** must be enabled
   > (Settings → Developer options → USB debugging) and the phone must
   > be connected via a data-capable USB cable with the host fingerprint
   > accepted. If `adb` hangs on `- waiting for device -`, see §4.3.

### 1.3 On some OEMs: also enable "Always log everything"

Samsung and some Xiaomi builds add an extra "Disable absolute volume" and "Enable Gabeldorsche" set of toggles; leave those alone. The only required toggle is **Bluetooth HCI snoop log**.

## 2. Pre-session setup

### 2.1 First-time-connection capture (do this first)

The pairing exchange only happens when the phone and controller don't already share a bond. If the phone has previously paired with the controller, subsequent connects reuse the cached bond and the handshake bytes will **not** appear in the log.

To get a clean first-time capture:

1. On the phone: **Settings → Bluetooth → (the XG device) → ⓘ → Forget device**. Repeat for any "XG", "LPL", or "ColorSplash" entry.
2. On the controller: power-cycle it (flip breaker / unplug 120 VAC mains for ~10 s). The controller has no reset button; power cycling is how you force it back to un-bonded advertising state. Verify by confirming the app is prompted to "Connect to XG controller" on the device-select sheet again.
3. Proceed to §3 for a full first-time sweep.

### 2.2 Steady-state capture

After the first-time sweep, you can do a second, shorter pass without forgetting the device, to record what a normal "already bonded" reconnect looks like. Label it clearly in `SWEEP_LOG.md`.

### 2.3 One client at a time

Only one BLE central can hold the controller. Before starting:

- Close the app on any other phone that might have previously connected
- Power down the ESP32 bridge (unplug or disable the `ble_client` component) if it is already deployed

If another client is already connected, the Android app will either fail to see the device or see it but fail to connect.

## 3. Running the capture session

### 3.0 Scripted path: `tools/capture-session`

[`tools/capture-session`](../tools/capture-session) automates everything in §3.1–§3.3 and the §4.1 pull: it creates the session directory, writes `session_start` at the top of `SWEEP_LOG.md`, prompts for each action with the remaining time shown, timestamps every entry in the required UTC millisecond format, and runs `adb bugreport` + extracts `btsnoop_hci.log` when you end the session.

```sh
cd captures
../tools/capture-session                 # default suffix: first-pair
../tools/capture-session steady-state    # second pass, already-bonded
```

End the session by pressing Enter on an empty prompt, pressing Ctrl-D, or letting the 5-minute timer expire. The script then pulls the log automatically — make sure the phone is connected with USB debugging authorized before you start (see §1.2 and §4.3).

If you prefer to drive the steps by hand, the manual procedure is in §3.1 onward.

### 3.1 Set up the companion log

Create a session directory and a sweep log:

```sh
mkdir -p "captures/$(date +%F)-first-pair"
$EDITOR "captures/$(date +%F)-first-pair/SWEEP_LOG.md"
```

`captures/` is gitignored except for `captures/README.md` (see [captures/README.md](../captures/README.md)), so nothing you put there is at risk of being committed.

Record the session start timestamp in UTC:

```sh
date -u +%Y-%m-%dT%H:%M:%S.%3NZ
```

Paste that at the top of `SWEEP_LOG.md` as `session_start`. Record a timestamp on every action line as you go.

### 3.2 Follow the action inventory

Work through the full action sweep from issue [#5](#appendix--action-inventory). Keep sessions under 5 minutes per run — Android OEMs cap the ring-buffered `btsnoop_hci.log` (4–16 MB is typical) and older entries drop off the front silently.

For each action, record a line like:

```
2026-04-18T16:23:10.412Z  tap "Nova" effect tile
2026-04-18T16:23:24.018Z  tap Lock (bottom bar), color held cyan
2026-04-18T16:23:38.902Z  tap Return
```

Be specific. "Tapped Return" isn't enough if the preceding state matters. `#5`'s acceptance requires Return behavior to be documented across multiple contexts — capture enough context for that.

### 3.3 Wait between actions

Leave 2–5 seconds between UI actions. It makes the HCI log dramatically easier to read afterward — each action ends up as a visually distinct burst rather than a wall of interleaved packets.

### 3.4 When to start a new session

Start a fresh session (new `SWEEP_LOG.md`, new log pull) whenever:

- You cross the ~5-minute mark
- You change from first-time-pair to steady-state mode
- You see any unexpected disconnect in the app
- You change phones or change Android versions

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

`adb bugreport` takes 30–120 s and produces a large zip. You only need the one file inside it.

### 4.2 Fallback paths

Some OEMs expose the snoop log outside the bug report. If the primary path finds nothing, try each of these in turn:

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

`adb pull` on `/data/...` paths requires a rooted phone on most modern builds — if it fails with "Permission denied," use the bug-report path from §4.1.

### 4.3 If `adb` refuses to connect

- `adb devices` shows the phone as `unauthorized`: unlock the phone, accept the "Allow USB debugging?" prompt, re-run
- `adb devices` shows nothing: USB cable is charge-only (swap it) or USB debugging is disabled (**Developer options → USB debugging**)
- `adb devices` shows the phone as `offline`: `adb kill-server && adb start-server`

## 5. Sanity-check the capture in Wireshark

Open the `btsnoop_hci.log` in Wireshark 4.x (File → Open → select the file; Wireshark auto-detects the btsnoop format).

Apply this display filter:

```
btle || bthci_acl || bthci_evt
```

You want to see:

- **Advertising packets** from the controller (periodic `ADV_IND` / `ADV_SCAN_IND`) — proves the phone was receiving the device before the connect
- **`HCI_LE_Create_Connection`** command followed by **`HCI_LE_Connection_Complete`** event — proves the connect happened
- **GATT Write Request** or **Write Command** packets during each action — these are the bytes we're going to decode into [`docs/PROTOCOL.md`](PROTOCOL.md)
- **(First-time only)** `SMP Pairing Request` / `Pairing Response` packets — proves the bonding handshake was captured

If the log is empty or only contains events for other BT devices (your earbuds, a fitness tracker), re-check §1.2 — the BT off/on cycle is almost always the cause.

### 5.1 Align Wireshark timestamps with `SWEEP_LOG.md`

**View → Time Display Format → Date and Time of Day**. Packet timestamps now show wall-clock, which lines up with the timestamps you wrote in `SWEEP_LOG.md`. Expect 0.5–2 s of skew between the phone clock and your laptop clock — not a problem, just don't be alarmed.

## 6. Storage and privacy

- `captures/` and `*.log` are gitignored; see [`.gitignore`](../.gitignore) and [`captures/README.md`](../captures/README.md). Nothing from a capture should end up in a commit
- A `btsnoop_hci.log` may include:
  - The controller's MAC address (or its resolvable private address)
  - The Long-Term Key (LTK) from the pairing exchange. If redistributed, anyone with a nearby nRF sniffer could decrypt your traffic
  - The phone's MAC address
- **Do not paste raw bytes into an issue or PR without redacting.** If you need to share a sample, excerpt the relevant GATT write only (post-pairing, post-encryption) and scrub identifiers

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

Android HCI snoop captures everything above the HCI boundary — commands, events, ACL traffic, SMP pairing messages — but not the raw link-layer PDUs (LL control, data channel selection, connection parameter updates as they appear on-air). If Phase 1 protocol decode turns up a question that requires LL-level visibility, reach for the over-the-air sniffer covered in §8 below. Don't chase LL answers in the HCI log; they're not there.

## 8. Over-the-air capture with the Adafruit Bluefruit LE Sniffer

The project's on-hand over-the-air sniffer is an **Adafruit Bluefruit LE Sniffer v2.0** (`nRF51822`-based, FT232R USB-UART bridge). It ships pre-flashed with Nordic's legacy nRF Sniffer for Bluetooth LE v2 firmware. Do not reflash — the device doesn't enumerate over USB DFU and reflashing the nRF51 requires a J-Link.

### 8.1 What this adds over HCI

Most protocol decode for Phase 1 was completed from HCI captures (§1–§7) plus the APK decompile. The OTA sniffer complements both with:

- **Link-layer visibility** HCI can't expose: `LL_CONNECT_IND` timing, connection interval updates, channel map changes, data channel hops
- **A vendor-neutral reference** that bypasses the Samsung Tab S9 Ultra's localtime-as-UTC timestamp quirk (§7 troubleshooting / clock skew)
- **A starting point for Phase 4b show-scrub timing** if we need to measure when the controller transitions between colors mid-show

### 8.2 One-time setup

The v2 firmware predates Wireshark's extcap architecture, so there's no Nordic plugin for it in modern Wireshark. Use Adafruit's Python sniffer client directly; it writes a pcap that Wireshark opens after the capture ends.

```sh
# 1. Clone the Adafruit client (keep outside this repo)
mkdir -p ~/dev/nrf-sniffer-tools && cd ~/dev/nrf-sniffer-tools
git clone https://github.com/adafruit/Adafruit_BLESniffer_Python.git

# 2. Create a venv and install deps
python3 -m venv venv
./venv/bin/pip install -r Adafruit_BLESniffer_Python/requirements.txt
```

The client was written for Python 2.7. Four small Python 3 fixes are required before it will run on modern macOS:

| File | Fix |
|---|---|
| `SnifferAPI/Logger.py` | Change `except AttributeError:` (line 24) to `except (AttributeError, TypeError):` — on macOS, `os.getenv('appdata')` returns `None` rather than raising, so the join now raises `TypeError` instead. |
| `SnifferAPI/Packet.py` `setup()` (≈line 94) | Replace the bare `self.uart.ser.open` reference with a conditional `if not self.uart.ser.is_open: self.uart.ser.open()`. The missing parens were a silent no-op under Python 2. |
| `SnifferAPI/UART.py` | In `read()` and `writeList()`, add `if not self.ser.is_open: self.ser.open()` before the I/O call — covers the case where `setup()`'s close/reopen dance leaves the port transiently closed. |
| `SnifferAPI/SnifferCollector.py` `_continuouslyPipe()` | Handle `None` packets and widen the `except` list to include `UARTPacketError`. Without this, a single malformed SLIP frame crashes the whole reader thread and no further packets are written to the pcap. |

After the patches:

```sh
./venv/bin/python -u Adafruit_BLESniffer_Python/sniffer.py /dev/cu.usbserial-10
```

Should print `Scanning for BLE devices (5s) ...` and enumerate nearby devices, including **`BGScripr`** when the controller is advertising.

### 8.3 Running an OTA capture session

The client's `sniffer.py` is interactive (scan → pick device → follow). For scripted captures, a small wrapper that auto-selects by name is convenient but not checked into this repo because it needs to live next to the Adafruit client. The wrapper does three things:

1. `Sniffer.Sniffer('/dev/cu.usbserial-10')` + `.start()` + sleep 6 s for firmware boot.
2. `.scan()` for ~8 s, iterate `sniffer.getDevices().asList()`, find the entry whose `name` contains `BGScripr`, record its address.
3. `.follow(dev)` and then `time.sleep(capture_duration)` while you drive the app. Copy `Adafruit_BLESniffer_Python/logs/capture.pcap` to `captures/YYYY-MM-DD-nrf-<suffix>/session.pcap` at the end.

Important prerequisites:

- **Close any terminal holding `/dev/cu.usbserial-10`** — only one process can open the serial port
- **Start the capture with the phone _disconnected_ from the controller.** The follow command locks on when the sniffer sees an `LL_CONNECT_IND` packet. If the phone is already connected, the sniffer will only see periodic advertisements and won't follow into the connection
- **The client writes pcap to a CWD-relative `logs/capture.pcap`.** Run from the Adafruit dir or `os.chdir()` into it from your wrapper, otherwise writes silently fail

### 8.4 Reading the pcap

The capture file is `DLT_USER_10` (Nordic's proprietary pseudo-header format). Wireshark needs its built-in "Nordic BLE Sniffer" dissector routed to that link-layer type:

1. Open the pcap in Wireshark.
2. Edit → Preferences → Protocols → DLT_USER → Encapsulations Table → Add row: DLT = `USER 10`, Payload protocol = `nordic_ble`.
3. Apply; Wireshark will now decode the packets as BLE. The standard `btle || btatt` filter then works exactly as it does for HCI captures.

For cross-reference with v1.1 PROTOCOL.md: ATT Write Requests to handle `0x000f` carry a one-byte value in the range `0x00-0x0e`. Every value maps to a UI element per the opcode table.

### 8.5 Known limitations

- **Follow-mode reliability (2026-04-19).** Even after the Python 3 patches above, the client sometimes fails to capture the post-`LL_CONNECT_IND` connection traffic — the scan-phase captures work, but the transition to connected-mode capture needs more debugging than this project has budgeted. Worked around by keeping the phone disconnected at capture start and reconnecting during the window; if that doesn't track, the scan-only capture is still useful for studying the controller's advertising behavior
- **Wireshark cannot auto-dissect `DLT_USER_10`** without the per-session DLT table entry described in §8.4. Wireshark remembers the setting across restarts once configured
- **nRF51 is BLE 4.x-only** (1 Mbps PHY). Fine for this controller — which only uses 1M — but would not help capture BLE 5 2M / Coded PHY peripherals
- **Encryption.** If the link were encrypted (this controller's isn't) the sniffer would need the Long-Term Key extracted from an HCI capture of the pairing to decrypt. `docs/CAPTURING.md` §6 privacy notes apply to pcap files equally

## 9. iOS capture via Apple PacketLogger

To cross-check the Android-derived protocol against the iOS XG app (issue #6), use Apple's **PacketLogger**. It attaches to a USB-connected iPhone/iPad that has the **Bluetooth Debug Profile** installed, and writes a btsnoop-format capture that `tshark` and [`tools/decode_sweep.py`](../tools/decode_sweep.py) can read directly.

### 9.1 What this adds over the Android HCI capture

- **Ground-truth comparison** against the Android protocol findings — confirms or refutes any platform-specific behavior
- A path to capture from an **iOS device that can't run `adb`**. The same btsnoop format drops right into the existing decoder

### 9.2 One-time setup

1. **Install PacketLogger.** Sign in at [developer.apple.com/download/all/](https://developer.apple.com/download/all/) with your Apple ID (free developer account works), download **"Additional Tools for Xcode"** matching your installed Xcode version, mount the DMG, and drag `Hardware/PacketLogger.app` into `/Applications`. Launch once to clear macOS Gatekeeper.
2. **Install the Bluetooth Debug Profile on the iOS device.** As of late 2025 / early 2026 this profile lives on Apple's Feedback Assistant profiles page: [developer.apple.com/feedback-assistant/profiles-and-logs/](https://developer.apple.com/feedback-assistant/profiles-and-logs/). Download the `.mobileconfig` to the phone (AirDrop or Safari on device), install via Settings → General → VPN & Device Management, and **reboot the phone** for the profile to take effect.
3. **Connect the phone to the Mac via USB.** Unlock the phone, approve the "Trust This Computer?" prompt if it appears. Verify the phone enumerates with `xcrun xctrace list devices`.

### 9.3 Running an iOS capture session

Modern PacketLogger (Xcode 26+) auto-opens a live capture against the connected iOS device when you launch the app — the window title shows `Untitled [Live] - <device name>`.

1. Make sure the XG app is disconnected from the controller (app closed or on the "Select device" sheet).
2. In PacketLogger: ⌘K (Edit → Clear All) to flush the startup buffer.
3. On the iPhone: open the XG app, Connect → Connect to XG Controller, then tap a deliberate sweep (e.g. one color, one show, Lock, Return, Standby) with 3–5 second pauses to make correlation trivial.
4. In PacketLogger: click **Pause** or close the live window to stop.
5. **File → Save As** → `captures/YYYY-MM-DD-ios-<suffix>/session.pklg` (PacketLogger's native format).
6. **File → Export** — recent PacketLogger emits a `session.pcap.log` that is actually a **btsnoop v1** file (same encapsulation as Android's `btsnoop_hci.log`). That's the file you analyze with `tshark`.

### 9.4 Reading the pcap

```sh
# Extract all ATT Write Requests to handle 0x000f
/Applications/Wireshark.app/Contents/MacOS/tshark \
  -r captures/YYYY-MM-DD-ios-<suffix>/session.pcap.log \
  -Y 'btatt.opcode == 0x12 and btatt.handle == 0x000f' \
  -T fields -e frame.time_epoch -e btatt.value
```

Each write row is `<epoch>\t<byte-hex>` and maps to the opcode table in [`docs/PROTOCOL.md`](PROTOCOL.md). Because the file is btsnoop format, `tools/decode_sweep.py` also works on it directly — point the tool at the session directory and it correlates writes against a SWEEP_LOG.md the same way as for Android captures.

### 9.5 Notes

- The `.pklg` PacketLogger-native file is kept alongside the btsnoop export for future reference (Apple has their own dissector). Both are gitignored (`captures/*` plus `*.pklg` in `.gitignore`)
- Clock skew of the Samsung tablet (§8's quirk) does **not** apply to iOS — PacketLogger timestamps are genuine UTC. `decode_sweep.py`'s auto-skew will see ~0 s offset and skip correction
- No SMP pairing is observed on iOS either, matching Android and the app decompile's finding of no bonding code

## Appendix — action inventory

The exact list of actions a capture session must exercise lives in issue [#5 — Phase 1: Structured capture sweep of every app action](https://github.com/swizzlevixen/colorsplash-xg-ha/issues/5). That issue is the source of truth; a brief summary here so you don't have to context-switch:

1. App cold-launch with controller unpaired / factory-new (capture the pairing exchange).
2. Tap **Status** card → **Select device** sheet → **Connect to XG controller**.
3. **Standby** toggle on → off → on, in three different prior states (solid color, running show, Lock-held mid-show).
4. Each of the 5 solid colors: Parisian Blue, Brazilian Red, Arctic White, Miami Pink, New Zealand Green.
5. Each of the 7 shows: Nova, Super Nova, Northern Lights, Tidal Wave, Patriot Dream, Desert Skies, Peruvian Paradise.
6. **Lock** in three contexts: on a solid color, mid-show, in standby.
7. **Return** after several sequences — document actual behavior.
8. **Disconnect**.
9. Reconnect, verify controller state is preserved.

Acceptance criteria for the capture session itself live on #5, not on this document.
