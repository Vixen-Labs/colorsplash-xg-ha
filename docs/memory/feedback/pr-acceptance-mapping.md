---
name: PR body format for partial-completion issues
description: When a PR closes some but not all acceptance criteria, mirror the criteria as a checklist in the PR body and call out deferred items
type: feedback
---

For PRs in `colorsplash-xg-ha` that address a GitHub issue with a checkbox acceptance list, the PR body should:

1. Mirror the issue's acceptance criteria as a checkbox list under an **Acceptance criteria (#N)** heading.
2. Tick only the criteria this PR actually satisfies.
3. For deferred criteria, keep the box unchecked and add a bold **deferred:** note explaining what is required to satisfy it (usually physical hardware, a live capture, or another issue landing first).
4. Include a **Test plan** section that is a walk-through checklist a human can tick as they validate, not a list of automated tests (this repo has none).

**Why:** issue #2's criterion 4 requires a real `btsnoop_hci.log` capture against the physical LPL-XG-CTRL-1 controller — not something I can satisfy from the agent side. Using the PR body to make this split unambiguous prevents an "all boxes checked, nothing verified" merge.

**How to apply:** reuse this pattern on every Phase 1–4 PR in `colorsplash-xg-ha`. Many phases require a physical capture, controller, or pool fixture at test time; the agent can produce the doc/code but cannot self-verify. Make the hand-off explicit in the PR, not implicit.
