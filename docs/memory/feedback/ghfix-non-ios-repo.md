---
name: /ghfix adaptation for non-iOS repos description: How to run the /ghfix skill in repos other than arrivals2 (Swift/Xcode) type: feedback
---

When `/ghfix` runs in a repo that is not `arrivals2`, adapt the workflow rather than mechanically following every step. Skip or substitute the arrivals2-specific steps:

- **Failing tests (Step 3)** — skip for pure docs issues; keep for code issues if the repo has a test harness
- **xcodegen / project.yml (Step 4)** — only applies to Xcode projects
- **Simulator / Animation Tests / simulator log tool (Step 4/6)** — iOS-only
- **`flipProgressSubSteps` check (Step 5)** — arrivals2-specific test

Keep: plan → MacDown review + beep → branch + plan comment on issue → implement with incremental commits → PR referencing the issue → confirm-then-merge wrap-up.

**Why:** the skill text is written against the arrivals2 iOS app, but the user invokes it in other repos too (e.g. `colorsplash-xg-ha`). Mechanical adherence produces nonsense steps like "run the simulator" in a Python/ESPHome/docs repo.

**How to apply:** in Step 2 of the plan, explicitly enumerate which skill steps apply and which don't, in a short table, so the user can see the adaptation up front and correct it if wrong.
