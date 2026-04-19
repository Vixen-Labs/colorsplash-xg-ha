"""Unit tests for decode_sweep pure-logic helpers.

Run:
    python3 -m unittest discover -s tests

No external dependencies; stdlib only.
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from decode_sweep import Action, Write, parse_sweep_log, correlate  # noqa: E402


def ts(s: str) -> datetime:
    """Parse an ISO-ms UTC timestamp like '2026-04-19T14:54:12.930Z'."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def w(t: str, handle: int = 0x0010, value: bytes = b"\x00", opcode: int = 0x52) -> Write:
    return Write(timestamp=ts(t), handle=handle, value=value, opcode=opcode)


class ParseSweepLogTests(unittest.TestCase):
    def test_parses_header_and_actions(self):
        text = (
            "session_start: 2026-04-19T14:54:12.930Z\n"
            "\n"
            "2026-04-19T14:54:27.328Z  tap Connect\n"
            "2026-04-19T14:54:44.764Z  tap Connect to XG Controller\n"
        )
        actions = parse_sweep_log(text)
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0].timestamp, ts("2026-04-19T14:54:27.328Z"))
        self.assertEqual(actions[0].label, "tap Connect")
        self.assertEqual(actions[1].label, "tap Connect to XG Controller")

    def test_ignores_blank_and_header_lines(self):
        text = (
            "session_start: 2026-04-19T15:00:00.000Z\n"
            "\n"
            "\n"
            "2026-04-19T15:00:10.000Z  first\n"
            "\n"
            "2026-04-19T15:00:20.000Z  second\n"
        )
        actions = parse_sweep_log(text)
        self.assertEqual([a.label for a in actions], ["first", "second"])

    def test_preserves_verbatim_labels_including_typos(self):
        text = (
            "session_start: 2026-04-19T15:00:00.000Z\n"
            "2026-04-19T15:00:10.000Z  tap retun (returns to locked Cyan)\n"
            "2026-04-19T15:00:20.000Z  tap standy\n"
            "2026-04-19T15:00:30.000Z  tap Lock to cssave a cyan color\n"
        )
        actions = parse_sweep_log(text)
        self.assertEqual(actions[0].label, "tap retun (returns to locked Cyan)")
        self.assertEqual(actions[1].label, "tap standy")
        self.assertEqual(actions[2].label, "tap Lock to cssave a cyan color")

    def test_tolerates_trailing_backslash(self):
        text = (
            "session_start: 2026-04-19T14:54:12.930Z\n"
            "2026-04-19T14:57:55.728Z  tap Return (reverts to green)\\\n"
        )
        actions = parse_sweep_log(text)
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0].label.startswith("tap Return"))

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(parse_sweep_log(""), [])
        self.assertEqual(parse_sweep_log("\n\n\n"), [])

    def test_ignores_parenthetical_narration_lines(self):
        # Lines where the "label" is wholly a parenthetical observation are
        # still actions (they have timestamps) — user narrated them
        # deliberately. Keep them; decode consumer can filter if needed.
        text = (
            "session_start: 2026-04-19T15:00:00.000Z\n"
            "2026-04-19T15:00:10.000Z  tap standby\n"
            "2026-04-19T15:00:54.000Z  (standby now on)\n"
        )
        actions = parse_sweep_log(text)
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[1].label, "(standby now on)")


class CorrelateTests(unittest.TestCase):
    def test_single_write_after_single_action(self):
        actions = [Action(ts("2026-04-19T15:00:00.000Z"), "tap blue")]
        writes = [w("2026-04-19T15:00:00.500Z")]
        grouped, orphans = correlate(writes, actions, window_s=2.0)
        self.assertEqual(orphans, [])
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0][0].label, "tap blue")
        self.assertEqual(grouped[0][1], writes)

    def test_write_before_any_action_is_orphan(self):
        actions = [Action(ts("2026-04-19T15:00:10.000Z"), "tap blue")]
        writes = [w("2026-04-19T15:00:00.000Z")]  # pre-session traffic
        grouped, orphans = correlate(writes, actions, window_s=2.0)
        self.assertEqual(orphans, writes)
        self.assertEqual(grouped[0][1], [])

    def test_write_beyond_window_is_orphan(self):
        actions = [Action(ts("2026-04-19T15:00:00.000Z"), "tap blue")]
        writes = [w("2026-04-19T15:00:05.000Z")]  # 5 s after, window is 2 s
        _, orphans = correlate(writes, actions, window_s=2.0)
        self.assertEqual(orphans, writes)

    def test_multiple_writes_in_one_action_window(self):
        actions = [Action(ts("2026-04-19T15:00:00.000Z"), "tap blue")]
        writes = [
            w("2026-04-19T15:00:00.100Z"),
            w("2026-04-19T15:00:00.900Z"),
            w("2026-04-19T15:00:01.400Z"),
        ]
        grouped, orphans = correlate(writes, actions, window_s=2.0)
        self.assertEqual(orphans, [])
        self.assertEqual(len(grouped[0][1]), 3)

    def test_two_actions_writes_go_to_nearest_preceding(self):
        actions = [
            Action(ts("2026-04-19T15:00:00.000Z"), "tap blue"),
            Action(ts("2026-04-19T15:00:05.000Z"), "tap red"),
        ]
        writes = [
            w("2026-04-19T15:00:00.200Z"),  # → blue
            w("2026-04-19T15:00:05.300Z"),  # → red
        ]
        grouped, orphans = correlate(writes, actions, window_s=2.0)
        self.assertEqual(orphans, [])
        self.assertEqual(grouped[0][0].label, "tap blue")
        self.assertEqual(grouped[0][1], [writes[0]])
        self.assertEqual(grouped[1][0].label, "tap red")
        self.assertEqual(grouped[1][1], [writes[1]])

    def test_empty_inputs(self):
        grouped, orphans = correlate([], [], window_s=2.0)
        self.assertEqual(grouped, [])
        self.assertEqual(orphans, [])

    def test_empty_writes_with_actions(self):
        actions = [Action(ts("2026-04-19T15:00:00.000Z"), "tap blue")]
        grouped, orphans = correlate([], actions, window_s=2.0)
        self.assertEqual(orphans, [])
        self.assertEqual(grouped[0][0].label, "tap blue")
        self.assertEqual(grouped[0][1], [])

    def test_writes_with_no_actions_all_orphan(self):
        writes = [w("2026-04-19T15:00:00.000Z"), w("2026-04-19T15:00:05.000Z")]
        grouped, orphans = correlate(writes, [], window_s=2.0)
        self.assertEqual(grouped, [])
        self.assertEqual(orphans, writes)

    def test_actions_preserve_input_order_with_duplicate_timestamps(self):
        t = ts("2026-04-19T15:00:00.000Z")
        actions = [Action(t, "first"), Action(t, "second")]
        writes = [w("2026-04-19T15:00:00.500Z")]
        grouped, _ = correlate(writes, actions, window_s=2.0)
        # Both actions listed; the write attaches to the last preceding,
        # which is "second" (the latter of two at the same timestamp).
        self.assertEqual([g[0].label for g in grouped], ["first", "second"])
        self.assertEqual(grouped[0][1], [])
        self.assertEqual(grouped[1][1], writes)


if __name__ == "__main__":
    unittest.main()
