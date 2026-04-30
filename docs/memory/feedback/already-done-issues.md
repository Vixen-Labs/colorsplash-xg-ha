---
name: Handling already-complete issues in /ghfix description: When an issue targeted by /ghfix is already done, offer close-only path before running the workflow type: feedback
---

When `/ghfix N` targets an issue whose acceptance criteria are already met (e.g., issue body has checked boxes or says "Closing as completed by commit X"), do **not** enter the full branch/test/PR workflow. Instead, present the user a short numbered menu:

1. Just close it — post a comment citing the completing commit(s), then `gh issue close N`.
2. Pick a different issue.
3. Proceed anyway (not recommended).

**Why:** validated with issue #1 on `colorsplash-xg-ha` on 2026-04-18 — user picked option 1 ("just close"). Running the full workflow against a completed issue produces an empty branch and a churn PR.

**How to apply:** after `gh issue view N`, scan the body for a terminal note like "Closing as completed by commit …" or all-checked acceptance boxes. If present, cross-check repo state (files exist, commits are on main) then offer the menu above. Only skip to the full workflow if the user explicitly picks option 3 or there is real outstanding work.
