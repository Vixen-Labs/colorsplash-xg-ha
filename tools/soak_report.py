#!/usr/bin/env python3
"""Produce a markdown soak-test report from an ``esphome logs`` capture.

Consumes the plaintext (or gzip-compressed) log written by
``esphome logs colorsplash-xg.yaml --device colorsplash-xg.local
> captures/soak-YYYY-MM-DD.log`` and summarises the run against
the #13 acceptance criteria.

Usage:
    python tools/soak_report.py captures/soak-2026-04-20.log
    python tools/soak_report.py captures/soak.log.gz

Reads from stdin if no path given.

The report goes to stdout; paste it into ``docs/SOAK_TEST.md``'s
results section for the PR.
"""

from __future__ import annotations

import argparse
import gzip
import io
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


# Log lines are prefixed with ``[HH:MM:SS.mmm]`` when streamed by
# ``esphome logs``. The date doesn't appear in the line itself — we
# infer date rollovers by watching the clock run backwards.
_TS_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]")

# Event markers we care about.
_FOUND_RE = re.compile(
    r"found ColorSplash XG controller at ([0-9A-F:]+) "
    r"\(rssi=(-?\d+)\)"
)
_READY_RE = re.compile(r"indications enabled")
_FAILURE_RE = re.compile(
    r"BLE failure #(\d+): (.+?) — backing off (\d+) ms"
)
_REBOOT_RE = re.compile(r"BLE wedged after \d+ consecutive failures")
_SENT_RE = re.compile(r"sent byte 0x([0-9a-f]{2}) \(([^)]+)\)")
_ECHO_RE = re.compile(r"indication echo 0x([0-9a-f]{2})")
_DISCONNECT_RE = re.compile(r"ESP_GATTC_DISCONNECT_EVT|early disconnect")


@dataclass
class ReconnectEvent:
    found_at: datetime
    ready_at: datetime | None = None
    rssi_dbm: int | None = None

    @property
    def latency_s(self) -> float | None:
        if self.ready_at is None:
            return None
        return (self.ready_at - self.found_at).total_seconds()


@dataclass
class SoakStats:
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    reconnects: list[ReconnectEvent] = field(default_factory=list)
    failures: int = 0
    reboots: int = 0
    sent_count: int = 0
    sent_by_byte: dict[int, int] = field(default_factory=dict)
    echo_count: int = 0
    disconnects: int = 0

    @property
    def wall_time(self) -> timedelta | None:
        if self.first_event_at is None or self.last_event_at is None:
            return None
        return self.last_event_at - self.first_event_at

    def ready_latencies(self) -> list[float]:
        return [
            e.latency_s for e in self.reconnects
            if e.latency_s is not None
        ]


def _open_maybe_gz(path: str | Path):
    p = Path(path)
    if p.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(p, "rb"), encoding="utf-8")
    return open(p, "r", encoding="utf-8")


def _parse_ts(line: str, date_cursor: datetime) -> datetime | None:
    m = _TS_RE.match(line)
    if not m:
        return None
    h, mi, s, ms = (int(g) for g in m.groups())
    return date_cursor.replace(
        hour=h, minute=mi, second=s, microsecond=ms * 1000,
    )


_FILENAME_DATE_RE = re.compile(r"soak-(\d{4}-\d{2}-\d{2})\.log")


def _infer_start_date(path: str | Path | None) -> datetime:
    """Pick a plausible absolute date to anchor the log's clock-only
    timestamps. Falls back to today when the hint sources yield nothing
    useful."""
    if path is not None:
        p = Path(path)
        m = _FILENAME_DATE_RE.search(p.name)
        if m:
            return datetime.strptime(m.group(1), "%Y-%m-%d")
        if p.exists():
            # mtime is the last write — earlier events happened at or
            # before this date, so use it as an upper bound anchor.
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            return mtime.replace(hour=0, minute=0, second=0, microsecond=0)
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def parse(stream, start_date: datetime | None = None) -> SoakStats:
    stats = SoakStats()
    open_recon: ReconnectEvent | None = None
    # The log doesn't carry dates, only clock time. We track a
    # cursor date and bump it by one day whenever we see the clock
    # roll backwards. Caller gets to anchor the date; filename or
    # today's date works for live-tail captures.
    date_cursor = start_date or datetime.now().replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    last_ts: datetime | None = None
    for line in stream:
        ts = _parse_ts(line, date_cursor)
        if ts is None:
            continue
        if last_ts is not None and ts < last_ts - timedelta(hours=1):
            date_cursor += timedelta(days=1)
            ts = _parse_ts(line, date_cursor)
            assert ts is not None
        last_ts = ts
        if stats.first_event_at is None:
            stats.first_event_at = ts
        stats.last_event_at = ts

        if m := _FOUND_RE.search(line):
            open_recon = ReconnectEvent(
                found_at=ts,
                rssi_dbm=int(m.group(2)),
            )
            stats.reconnects.append(open_recon)
        elif _READY_RE.search(line):
            if open_recon is not None and open_recon.ready_at is None:
                open_recon.ready_at = ts
        elif _FAILURE_RE.search(line):
            stats.failures += 1
        elif _REBOOT_RE.search(line):
            stats.reboots += 1
        elif m := _SENT_RE.search(line):
            stats.sent_count += 1
            byte = int(m.group(1), 16)
            stats.sent_by_byte[byte] = stats.sent_by_byte.get(byte, 0) + 1
        elif _ECHO_RE.search(line):
            stats.echo_count += 1
        elif _DISCONNECT_RE.search(line):
            stats.disconnects += 1
    return stats


def _fmt_seconds(s: float) -> str:
    if s < 60:
        return f"{s:.1f} s"
    if s < 3600:
        return f"{s / 60:.1f} min"
    return f"{s / 3600:.2f} h"


def _fmt_td(td: timedelta) -> str:
    total = td.total_seconds()
    h, rem = divmod(int(total), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


def _percentile(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    xs_sorted = sorted(xs)
    idx = min(len(xs_sorted) - 1, int(len(xs_sorted) * p))
    return xs_sorted[idx]


def format_report(stats: SoakStats) -> str:
    buf: list[str] = []
    wall = stats.wall_time

    buf.append("## Soak test results\n")
    if wall:
        buf.append(f"- **Wall time covered:** {_fmt_td(wall)}")
        buf.append(
            f"- **First event:** "
            f"{stats.first_event_at:%Y-%m-%d %H:%M:%S}"
        )
        buf.append(
            f"- **Last event:** "
            f"{stats.last_event_at:%Y-%m-%d %H:%M:%S}"
        )
    buf.append("")

    buf.append("### Connectivity")
    buf.append(f"- Disconnect events observed: **{stats.disconnects}**")
    buf.append(f"- Reconnect events observed: **{len(stats.reconnects)}**")
    buf.append(
        f"- Failed connect attempts (backoff-counted): "
        f"**{stats.failures}**"
    )
    buf.append(f"- Watchdog-triggered reboots: **{stats.reboots}**")

    latencies = stats.ready_latencies()
    if latencies:
        buf.append("")
        buf.append("#### Reconnect latency (seen-ad → indications-armed)")
        buf.append(f"- n = {len(latencies)}")
        buf.append(f"- min: {min(latencies):.2f} s")
        buf.append(f"- median: {statistics.median(latencies):.2f} s")
        buf.append(f"- p95: {_percentile(latencies, 0.95):.2f} s")
        buf.append(f"- max: {max(latencies):.2f} s")
    buf.append("")

    if wall and latencies:
        # Approximate: each reconnect window has the controller
        # effectively "down" from whenever we saw the disconnect
        # until READY. Without disconnect timestamps in logs we use
        # reconnect latency as a lower bound on downtime per event.
        total_down_s = sum(latencies)
        uptime_frac = 1.0 - (total_down_s / wall.total_seconds())
        buf.append(
            f"- **Approx uptime:** {uptime_frac * 100:.3f}% "
            f"(lower bound — counts only reconnect-window seconds)"
        )
    elif wall and stats.disconnects == 0 and not stats.reconnects:
        # No disconnects observed for the entire run — uptime is
        # 100% within the measurement resolution (1 s).
        uptime_frac = 1.0
        buf.append(
            "- **Uptime:** 100.000% "
            "(no disconnects observed across the run)"
        )
    else:
        uptime_frac = None
    buf.append("")

    if stats.sent_count or stats.echo_count:
        buf.append("### Command activity")
        buf.append(f"- Bytes sent: **{stats.sent_count}**")
        buf.append(f"- Indication echoes received: **{stats.echo_count}**")
        if stats.sent_by_byte:
            buf.append("")
            buf.append("| Byte | Count |")
            buf.append("|---:|---:|")
            for b in sorted(stats.sent_by_byte):
                buf.append(f"| 0x{b:02x} | {stats.sent_by_byte[b]} |")
        buf.append("")

    if stats.reconnects:
        rssis = [
            r.rssi_dbm for r in stats.reconnects
            if r.rssi_dbm is not None
        ]
        if rssis:
            buf.append("### RSSI at reconnect")
            buf.append(f"- min (worst): {min(rssis)} dBm")
            buf.append(f"- median: {int(statistics.median(rssis))} dBm")
            buf.append(f"- max (best): {max(rssis)} dBm")
        buf.append("")

    # Acceptance check
    buf.append("### Acceptance check (#13)")
    if wall and wall.total_seconds() >= 72 * 3600 - 60:
        buf.append("- [x] ≥72 h wall-time coverage")
    else:
        buf.append(
            "- [ ] ≥72 h wall-time coverage — this run is shorter; "
            "extend or rerun."
        )
    if stats.reboots == 0:
        buf.append("- [x] No watchdog reboots")
    else:
        buf.append(f"- [ ] No watchdog reboots (saw {stats.reboots})")
    if uptime_frac is not None:
        if uptime_frac >= 0.99:
            buf.append("- [x] ≥99% connectivity uptime")
        else:
            buf.append(
                f"- [ ] ≥99% connectivity uptime — measured "
                f"{uptime_frac * 100:.2f}%"
            )

    return "\n".join(buf) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "log",
        nargs="?",
        help="Path to esphome logs capture (.log or .log.gz). "
        "Reads stdin when omitted.",
    )
    args = p.parse_args(argv)

    if args.log:
        start = _infer_start_date(args.log)
        with _open_maybe_gz(args.log) as f:
            stats = parse(f, start_date=start)
    else:
        stats = parse(sys.stdin, start_date=_infer_start_date(None))

    if stats.first_event_at is None:
        print("no timestamped log lines found", file=sys.stderr)
        return 1
    sys.stdout.write(format_report(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
