#!/usr/bin/env python3
"""Decode a capture session's btsnoop_hci.log and correlate ATT writes with
SWEEP_LOG.md actions.

Usage:
    tools/decode_sweep.py <session-dir> [--window SECONDS]

Runs Wireshark's bundled `tshark` (default path:
`/Applications/Wireshark.app/Contents/MacOS/tshark`) over the session's
`btsnoop_hci.log`, extracts outbound ATT Write Requests (opcode 0x12) and
Write Commands (opcode 0x52), reads `SWEEP_LOG.md`, and prints a markdown
report grouping each write under the nearest preceding action within
`--window` seconds (default 2.0).

Override the tshark path with TSHARK env var.

Stdlib only.
"""

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


DEFAULT_TSHARK = "/Applications/Wireshark.app/Contents/MacOS/tshark"
DEFAULT_WINDOW_S = 15.0  # wide enough to absorb app-to-BLE-write latency
AUTO_SKEW_THRESHOLD_S = 30.0  # apply auto-skew if observed offset exceeds this

ATT_OP_WRITE_REQUEST = 0x12
ATT_OP_WRITE_COMMAND = 0x52


@dataclass(frozen=True)
class Action:
    timestamp: datetime
    label: str


@dataclass(frozen=True)
class Write:
    timestamp: datetime
    handle: int
    value: bytes
    opcode: int

    @property
    def opcode_name(self) -> str:
        return {
            ATT_OP_WRITE_REQUEST: "Write Request",
            ATT_OP_WRITE_COMMAND: "Write Command",
        }.get(self.opcode, f"0x{self.opcode:02x}")


def parse_sweep_log(text: str) -> list[Action]:
    """Parse SWEEP_LOG.md text into Action records.

    Lines starting with `session_start:` are headers and skipped. Blank
    lines are ignored. Every other line is expected to start with a UTC
    ISO-millisecond timestamp followed by whitespace and an action label.
    Labels are preserved verbatim (typos and parenthetical narration
    included) because downstream code may want to report them as-is.
    """
    actions: list[Action] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("session_start"):
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        ts_str, label = parts
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
        actions.append(Action(timestamp=ts, label=label.rstrip("\\").rstrip()))
    return actions


def correlate(
    writes: list[Write],
    actions: list[Action],
    window_s: float = DEFAULT_WINDOW_S,
) -> tuple[list[tuple[Action, list[Write]]], list[Write]]:
    """Group each write under the nearest preceding action within window_s.

    Returns (grouped, orphans):
      - grouped: one (Action, [Write...]) pair per input action, preserving
        input order; an action with zero correlated writes gets an empty
        list.
      - orphans: writes that happened before any action, or more than
        window_s after the last preceding action.
    """
    grouped: list[tuple[Action, list[Write]]] = [(a, []) for a in actions]
    orphans: list[Write] = []

    for write in writes:
        # Find the last action whose timestamp <= write.timestamp.
        # Preserve input order for ties: iterate in reverse, pick first hit.
        match_idx: int | None = None
        for i in range(len(actions) - 1, -1, -1):
            if actions[i].timestamp <= write.timestamp:
                match_idx = i
                break

        if match_idx is None:
            orphans.append(write)
            continue

        delta = (write.timestamp - actions[match_idx].timestamp).total_seconds()
        if delta > window_s:
            orphans.append(write)
            continue

        grouped[match_idx][1].append(write)

    return grouped, orphans


def _tshark_path() -> str:
    env = os.environ.get("TSHARK")
    if env:
        return env
    if Path(DEFAULT_TSHARK).exists():
        return DEFAULT_TSHARK
    found = shutil.which("tshark")
    if found:
        return found
    raise RuntimeError(
        "tshark not found. Install Wireshark or set TSHARK=/path/to/tshark"
    )


def extract_writes(btsnoop_path: Path) -> list[Write]:
    """Run tshark against btsnoop_path and return outbound ATT writes.

    Uses `-T ek` (JSONL) which is stream-friendly for large captures.
    Filters to `btatt` in the display filter; we post-filter for the
    two Write opcodes and for host-originated frames only.
    """
    tshark = _tshark_path()
    cmd = [
        tshark,
        "-r", str(btsnoop_path),
        "-T", "ek",
        "-Y", "btatt",
        # Request the fields we need; -T ek emits layer-scoped field names.
        "-e", "frame.time_epoch",
        "-e", "btatt.opcode",
        "-e", "btatt.handle",
        "-e", "btatt.value",
        "-e", "bthci_acl.src.role",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"tshark failed (exit {e.returncode}): {e.stderr[:500]}"
        ) from e

    writes: list[Write] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        # -T ek emits alternating index/data lines; skip index envelopes.
        layers = doc.get("layers") if isinstance(doc, dict) else None
        if not isinstance(layers, dict):
            continue

        opcodes = layers.get("btatt_opcode")
        if not opcodes:
            continue
        opcode_raw = opcodes[0] if isinstance(opcodes, list) else opcodes
        try:
            opcode = int(opcode_raw, 0) if isinstance(opcode_raw, str) else int(opcode_raw)
        except (TypeError, ValueError):
            continue
        if opcode not in (ATT_OP_WRITE_REQUEST, ATT_OP_WRITE_COMMAND):
            continue

        time_epoch = layers.get("frame_time_epoch")
        handle = layers.get("btatt_handle")
        value = layers.get("btatt_value")
        if not time_epoch or not handle:
            continue
        t_raw = time_epoch[0] if isinstance(time_epoch, list) else time_epoch
        h_raw = handle[0] if isinstance(handle, list) else handle
        v_raw = value[0] if isinstance(value, list) else (value or "")
        try:
            ts = datetime.fromtimestamp(float(t_raw), tz=timezone.utc)
            h = int(h_raw, 0) if isinstance(h_raw, str) else int(h_raw)
        except (TypeError, ValueError):
            continue
        # tshark emits btatt.value as colon-separated hex or plain hex;
        # normalize both forms.
        hex_str = v_raw.replace(":", "") if isinstance(v_raw, str) else ""
        try:
            vb = bytes.fromhex(hex_str) if hex_str else b""
        except ValueError:
            vb = b""

        writes.append(Write(timestamp=ts, handle=h, value=vb, opcode=opcode))

    return writes


def apply_skew(writes: list[Write], skew_s: float) -> list[Write]:
    """Return writes with timestamp shifted by -skew_s.

    `skew_s` is the number of seconds the phone clock is ahead of the
    laptop clock. Positive: phone is ahead (subtract to align).
    Negative: phone is behind (adding effectively shifts writes forward).
    """
    if skew_s == 0.0:
        return writes
    from datetime import timedelta
    return [
        Write(
            timestamp=w.timestamp - timedelta(seconds=skew_s),
            handle=w.handle,
            value=w.value,
            opcode=w.opcode,
        )
        for w in writes
    ]


def compute_auto_skew(writes: list[Write], actions: list[Action]) -> float:
    """Estimate clock skew by aligning the first write with the first action.

    Returns 0.0 if either list is empty.
    """
    if not writes or not actions:
        return 0.0
    return (writes[0].timestamp - actions[0].timestamp).total_seconds()


def format_report(
    session_dir: Path,
    actions: list[Action],
    writes: list[Write],
    grouped: list[tuple[Action, list[Write]]],
    orphans: list[Write],
    skew_s: float = 0.0,
) -> str:
    lines: list[str] = []
    lines.append(f"# decode-sweep report: {session_dir.name}")
    lines.append("")
    lines.append(f"- Actions in SWEEP_LOG: **{len(actions)}**")
    lines.append(f"- Outbound ATT writes (opcodes 0x12, 0x52): **{len(writes)}**")
    lines.append(f"- Writes correlated to actions: **{sum(len(w) for _, w in grouped)}**")
    lines.append(f"- Orphan writes (outside any action window): **{len(orphans)}**")
    if skew_s:
        direction = "ahead of" if skew_s > 0 else "behind"
        lines.append(
            f"- Applied clock skew: **{skew_s:+.3f} s** "
            f"(phone BT stack is {abs(skew_s):.0f}s {direction} laptop)"
        )
    lines.append("")

    if orphans:
        lines.append("## Orphan writes (pre-session / post-window)")
        lines.append("")
        lines.append("| UTC time | Handle | Opcode | Value (hex) |")
        lines.append("|---|---|---|---|")
        for w in orphans[:30]:
            lines.append(_write_row(w))
        if len(orphans) > 30:
            lines.append(f"| … | | | ({len(orphans) - 30} more omitted) |")
        lines.append("")

    lines.append("## Actions and writes")
    lines.append("")
    for action, ws in grouped:
        ts_str = action.timestamp.strftime("%H:%M:%S.%f")[:-3]
        lines.append(f"### {ts_str}  {action.label}")
        lines.append("")
        if not ws:
            lines.append("_no correlated ATT writes_")
            lines.append("")
            continue
        lines.append("| Δt (ms) | Handle | Opcode | Value (hex) |")
        lines.append("|---|---|---|---|")
        for w in ws:
            dt_ms = int((w.timestamp - action.timestamp).total_seconds() * 1000)
            lines.append(
                f"| {dt_ms:>4} | 0x{w.handle:04x} | {w.opcode_name} | "
                f"`{w.value.hex()}` |"
            )
        lines.append("")

    return "\n".join(lines)


def _write_row(w: Write) -> str:
    ts_str = w.timestamp.strftime("%H:%M:%S.%f")[:-3]
    return (
        f"| {ts_str} | 0x{w.handle:04x} | {w.opcode_name} "
        f"| `{w.value.hex()}` |"
    )


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    session_dir = Path(argv[0])
    window_s = DEFAULT_WINDOW_S
    skew_override: float | None = None
    auto_skew = True

    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--window" and i + 1 < len(argv):
            window_s = float(argv[i + 1])
            i += 2
        elif arg == "--skew" and i + 1 < len(argv):
            skew_override = float(argv[i + 1])
            i += 2
        elif arg == "--no-skew":
            auto_skew = False
            skew_override = 0.0
            i += 1
        else:
            print(f"Unexpected arg: {arg}", file=sys.stderr)
            return 2

    btsnoop = session_dir / "btsnoop_hci.log"
    sweep = session_dir / "SWEEP_LOG.md"
    if not btsnoop.exists():
        print(f"{btsnoop} not found", file=sys.stderr)
        return 1
    if not sweep.exists():
        print(f"{sweep} not found", file=sys.stderr)
        return 1

    actions = parse_sweep_log(sweep.read_text())
    writes = extract_writes(btsnoop)

    if skew_override is not None:
        skew_s = skew_override
    elif auto_skew:
        observed = compute_auto_skew(writes, actions)
        skew_s = observed if abs(observed) > AUTO_SKEW_THRESHOLD_S else 0.0
    else:
        skew_s = 0.0

    adjusted_writes = apply_skew(writes, skew_s)
    grouped, orphans = correlate(adjusted_writes, actions, window_s=window_s)
    print(format_report(session_dir, actions, adjusted_writes, grouped, orphans, skew_s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
