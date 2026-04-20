#!/usr/bin/env python3
"""Reference BLE client for the ColorSplash XG pool-light controller.

Usage:
    python tools/cli.py --effect <name>           drive one tile
    python tools/cli.py --raw <hex>               send one arbitrary byte
    python tools/cli.py --info                    read the controller's DIS strings
    python tools/cli.py --sweep                   cycle all 12 tile effects, then Standby

Global options:
    --address <MAC>        skip scan, connect directly
    --timeout <seconds>    scan timeout, default 8 s
    --ack-timeout <sec>    wait for indication echo, default 2 s
    --inter-cmd <sec>      --sweep delay between commands, default 5 s
    -v / --verbose         extra timing and bleak logs

See docs/PROTOCOL.md for the protocol this client implements.
"""

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass

# bleak is imported lazily so the pure-logic helpers (parse_effect,
# parse_raw, EFFECT_TABLE) can be unit-tested without the dep installed.
try:
    from bleak import BleakClient, BleakScanner
    from bleak.backends.characteristic import BleakGATTCharacteristic
    _BLEAK_OK = True
    _BLEAK_ERR: Exception | None = None
except ImportError as _imp_err:
    BleakClient = None  # type: ignore[assignment,misc]
    BleakScanner = None  # type: ignore[assignment,misc]
    BleakGATTCharacteristic = None  # type: ignore[assignment,misc]
    _BLEAK_OK = False
    _BLEAK_ERR = _imp_err


def _require_bleak() -> None:
    if not _BLEAK_OK:
        print(
            "bleak is not installed. Run:\n"
            "    python3 -m venv .venv && source .venv/bin/activate && "
            "pip install -r requirements.txt\n"
            f"(underlying error: {_BLEAK_ERR})",
            file=sys.stderr,
        )
        sys.exit(2)


# UUIDs from docs/PROTOCOL.md v1.3.
SERVICE_UUID = "5d5f4714-57e5-11e5-885d-feff819cdc9f"
COMMAND_CHAR_UUID = "4cabed4d-3f58-4429-b29c-f9a26205f28e"

# Bluetooth SIG standard Device Information Service characteristics.
DIS_FIRMWARE_REV_UUID = "00002a26-0000-1000-8000-00805f9b34fb"
DIS_MANUFACTURER_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
DIS_MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
DIS_SERIAL_NUMBER_UUID = "00002a25-0000-1000-8000-00805f9b34fb"
DIS_HARDWARE_REV_UUID = "00002a27-0000-1000-8000-00805f9b34fb"

DEVICE_LOCAL_NAME = "BGScripr"

# Canonical effect names → command bytes. Keep in sync with
# docs/PROTOCOL.md §Effect opcode table.
EFFECT_TABLE: dict[str, int] = {
    # Solid colors
    "parisian blue": 0x08,
    "brazilian red": 0x0A,
    "arctic white": 0x0B,
    "miami pink": 0x0C,
    "new zealand green": 0x09,
    # Shows
    "nova": 0x07,
    "super nova": 0x02,
    "northern lights": 0x03,
    "tidal wave": 0x04,
    "patriot dream": 0x05,
    "desert skies": 0x06,
    "peruvian paradise": 0x01,
    # Controls
    "lock": 0x0D,
    "return": 0x0E,
    "standby": 0x00,
}

# Short / convenient aliases. All map into the canonical table.
EFFECT_ALIASES: dict[str, str] = {
    "blue": "parisian blue",
    "red": "brazilian red",
    "white": "arctic white",
    "pink": "miami pink",
    "green": "new zealand green",
    "supernova": "super nova",
    "northern": "northern lights",
    "tidal": "tidal wave",
    "patriot": "patriot dream",
    "desert": "desert skies",
    "peruvian": "peruvian paradise",
    "off": "standby",
}

# Sweep order: colors then shows then controls. Excludes Standby
# (added as the sweep-ending action) and Return/Lock (which would
# interact with state in a way that confuses a pure "show everything"
# cycle).
SWEEP_EFFECTS: list[str] = [
    "parisian blue",
    "brazilian red",
    "arctic white",
    "miami pink",
    "new zealand green",
    "nova",
    "super nova",
    "northern lights",
    "tidal wave",
    "patriot dream",
    "desert skies",
    "peruvian paradise",
]


def parse_effect(name: str) -> int:
    """Resolve a human-typed effect name to a command byte.

    Accepts canonical names ('Parisian Blue'), aliases ('blue'),
    hyphens ('parisian-blue'), any case.
    """
    if not name or not name.strip():
        raise ValueError("empty effect name")
    normalized = name.strip().lower().replace("-", " ")
    # Collapse internal whitespace.
    normalized = " ".join(normalized.split())
    if normalized in EFFECT_ALIASES:
        normalized = EFFECT_ALIASES[normalized]
    if normalized in EFFECT_TABLE:
        return EFFECT_TABLE[normalized]
    raise ValueError(f"unknown effect: {name!r}")


def parse_raw(text: str) -> int:
    """Parse a hex-byte string like '08', '0x08', or '0X8' into 0..255."""
    if text is None:
        raise ValueError("empty raw byte")
    s = text.strip()
    if not s:
        raise ValueError("empty raw byte")
    if s.startswith(("0x", "0X")):
        body = s[2:]
    else:
        body = s
    if not body or any(c not in "0123456789abcdefABCDEF" for c in body):
        raise ValueError(f"not a hex byte: {text!r}")
    value = int(body, 16)
    if not 0 <= value <= 0xFF:
        raise ValueError(f"out of range 0x00..0xff: {text!r}")
    return value


def effect_name_for_byte(byte: int) -> str:
    for name, b in EFFECT_TABLE.items():
        if b == byte:
            return name.title()
    return f"0x{byte:02x} (undefined in spec)"


@dataclass
class WriteResult:
    byte: int
    name: str
    write_ms: float  # time to return from write_gatt_char
    echo_ms: float | None  # time from write send to matching indication, or None


# ---------------------------------------------------------------------
# Logging — compact, structured-ish.
# ---------------------------------------------------------------------


class _CompactFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = time.strftime("%H:%M:%S", time.localtime(record.created))
        ms = int((record.created - int(record.created)) * 1000)
        extras = getattr(record, "extras", {})
        extras_str = " ".join(f"{k}={v}" for k, v in extras.items())
        head = f"[{ts}.{ms:03d} {record.levelname} {record.name}]"
        return f"{head} {record.getMessage()}" + (f" {extras_str}" if extras_str else "")


def _setup_logging(verbose: bool) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_CompactFormatter())
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    # bleak is verbose at DEBUG; only enable it in --verbose.
    logging.getLogger("bleak").setLevel(logging.INFO if verbose else logging.WARNING)


def _log(event: str, **kv) -> None:
    logger = logging.getLogger(event)
    msg = " ".join(f"{k}={v}" for k, v in kv.items())
    logger.info(msg, extra={"extras": {}})


# ---------------------------------------------------------------------
# BLE flow
# ---------------------------------------------------------------------


async def _scan_for_controller(timeout: float) -> str:
    """Scan for the BGScripr peripheral and return its address."""
    _log("ble.scan.start", name=DEVICE_LOCAL_NAME, timeout_s=timeout)
    t0 = time.monotonic()
    device = await BleakScanner.find_device_by_name(DEVICE_LOCAL_NAME, timeout=timeout)
    if device is None:
        raise RuntimeError(
            f"No peripheral named {DEVICE_LOCAL_NAME!r} found within {timeout:.0f} s. "
            "Check the controller is powered, in range, and not connected to another central."
        )
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    _log("ble.scan.found", name=DEVICE_LOCAL_NAME, addr=device.address, elapsed_ms=elapsed_ms)
    return device.address


async def _write_and_wait_echo(
    client: BleakClient,
    byte: int,
    ack_timeout: float,
    queue: "asyncio.Queue[int]",
) -> WriteResult:
    """Send one command byte; wait for the controller's indication echo."""
    name = effect_name_for_byte(byte)
    # Drain any stale queued bytes so we match only our echo.
    while not queue.empty():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break

    t_send = time.monotonic()
    await client.write_gatt_char(COMMAND_CHAR_UUID, bytes([byte]), response=True)
    t_written = time.monotonic()
    write_ms = (t_written - t_send) * 1000

    echo_ms: float | None = None
    t_deadline = t_written + ack_timeout
    while time.monotonic() < t_deadline:
        remaining = t_deadline - time.monotonic()
        try:
            echoed = await asyncio.wait_for(queue.get(), timeout=remaining)
        except asyncio.TimeoutError:
            break
        if echoed == byte:
            echo_ms = (time.monotonic() - t_send) * 1000
            break
        else:
            # Not our byte; log and keep waiting.
            _log("ble.indication.other", byte=f"0x{echoed:02x}")

    if echo_ms is None:
        _log(
            "ble.indication.timeout",
            byte=f"0x{byte:02x}",
            name=f'"{name}"',
            ack_timeout_s=ack_timeout,
        )
    else:
        _log(
            "ble.indication.echo",
            byte=f"0x{byte:02x}",
            name=f'"{name}"',
            write_ms=f"{write_ms:.0f}",
            echo_ms=f"{echo_ms:.0f}",
        )
    return WriteResult(byte=byte, name=name, write_ms=write_ms, echo_ms=echo_ms)


async def _read_dis(client: BleakClient) -> None:
    """Read + print the standard Device Information Service strings."""
    targets = [
        ("Manufacturer", DIS_MANUFACTURER_UUID),
        ("Model", DIS_MODEL_NUMBER_UUID),
        ("Serial", DIS_SERIAL_NUMBER_UUID),
        ("Hardware Rev", DIS_HARDWARE_REV_UUID),
        ("Firmware Rev", DIS_FIRMWARE_REV_UUID),
    ]
    print("Device Information Service:")
    for label, uuid in targets:
        try:
            raw = await client.read_gatt_char(uuid)
            text = raw.decode("utf-8", errors="replace").rstrip("\x00").strip()
            print(f"  {label:<14} {text!r}  (raw: {raw.hex()})")
        except Exception as exc:
            print(f"  {label:<14} (read failed: {exc})")


def _make_indication_queue() -> "asyncio.Queue[int]":
    return asyncio.Queue(maxsize=32)


async def _connect(
    address: str | None,
    scan_timeout: float,
) -> tuple[BleakClient, str]:
    addr = address if address else await _scan_for_controller(scan_timeout)
    _log("ble.connect.start", addr=addr)
    t0 = time.monotonic()
    client = BleakClient(addr)
    await client.connect()
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    _log("ble.connect.ok", addr=addr, elapsed_ms=elapsed_ms)
    return client, addr


async def _subscribe(client: BleakClient) -> "asyncio.Queue[int]":
    queue = _make_indication_queue()

    def cb(_char: BleakGATTCharacteristic, data: bytearray) -> None:
        if not data:
            return
        try:
            queue.put_nowait(int(data[0]))
        except asyncio.QueueFull:
            pass  # drop oldest-first if we're overrun; unlikely

    await client.start_notify(COMMAND_CHAR_UUID, cb)
    return queue


async def _cmd_effect(args: argparse.Namespace) -> int:
    byte = args._resolved_byte
    client, addr = await _connect(args.address, args.timeout)
    try:
        queue = await _subscribe(client)
        await _write_and_wait_echo(client, byte, args.ack_timeout, queue)
    finally:
        await client.disconnect()
    return 0


async def _cmd_info(args: argparse.Namespace) -> int:
    client, addr = await _connect(args.address, args.timeout)
    try:
        await _read_dis(client)
    finally:
        await client.disconnect()
    return 0


async def _cmd_sweep(args: argparse.Namespace) -> int:
    client, addr = await _connect(args.address, args.timeout)
    results: list[WriteResult] = []
    try:
        queue = await _subscribe(client)
        _log("sweep.start", n_effects=len(SWEEP_EFFECTS) + 1, inter_cmd_s=args.inter_cmd)
        for name in SWEEP_EFFECTS:
            byte = EFFECT_TABLE[name]
            r = await _write_and_wait_echo(client, byte, args.ack_timeout, queue)
            results.append(r)
            await asyncio.sleep(args.inter_cmd)
        # Tail: Standby so the fixture ends in a known off state.
        r = await _write_and_wait_echo(client, EFFECT_TABLE["standby"], args.ack_timeout, queue)
        results.append(r)
        _log("sweep.done", n_written=len(results))
    finally:
        await client.disconnect()

    # Summary table
    print("\nsweep summary:")
    print(f"  {'byte':<6} {'name':<22} {'write_ms':>9} {'echo_ms':>9}")
    for r in results:
        echo = f"{r.echo_ms:.0f}" if r.echo_ms is not None else "-"
        print(f"  0x{r.byte:02x}    {r.name:<22} {r.write_ms:>8.0f}  {echo:>8}")
    return 0


# ---------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cli.py",
        description="ColorSplash XG bleak reference client",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--effect", help="effect name (e.g. blue, nova, lock, return, standby)")
    mode.add_argument("--raw", help="raw command byte in hex (e.g. 08 or 0x08)")
    mode.add_argument("--info", action="store_true", help="read Device Information Service")
    mode.add_argument(
        "--sweep", action="store_true",
        help="cycle all 12 tile effects, then Standby",
    )

    p.add_argument("--address", help="skip scan, connect to this BT address")
    p.add_argument("--timeout", type=float, default=8.0, help="scan/connect timeout (default: 8)")
    p.add_argument("--ack-timeout", type=float, default=2.0,
                   help="indication-echo wait (default: 2)")
    p.add_argument("--inter-cmd", type=float, default=5.0,
                   help="--sweep inter-command delay (default: 5 s — leave \u22655s for fixture transition)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    _require_bleak()

    if args.effect is not None:
        try:
            args._resolved_byte = parse_effect(args.effect)
        except ValueError as e:
            print(f"--effect: {e}", file=sys.stderr)
            return 2
        return asyncio.run(_cmd_effect(args))

    if args.raw is not None:
        try:
            args._resolved_byte = parse_raw(args.raw)
        except ValueError as e:
            print(f"--raw: {e}", file=sys.stderr)
            return 2
        if args._resolved_byte > 0x0E:
            _log("warn.undefined", byte=f"0x{args._resolved_byte:02x}",
                 note="not in PROTOCOL.md v1.3 opcode table")
        return asyncio.run(_cmd_effect(args))

    if args.info:
        return asyncio.run(_cmd_info(args))

    if args.sweep:
        return asyncio.run(_cmd_sweep(args))

    # Should be unreachable because the group is required.
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(_main())
