---
name: colorsplash-xg-ha issue / phase map
description: How this repo's 24 GitHub issues map onto the 6-phase plan
type: project
---

`colorsplash-xg-ha` has **24 open issues mapped one-to-one onto the phased plan in docs/PLAN.md**, numbered roughly in phase order:

- Issue #1 — Phase 0 scaffolding (closed 2026-04-18, completed by `aaa3045` / merged via `194d93b`)
- Issues #2–#8 — Phase 1 (reverse engineering: capture procedure, APK decompile, nRF sniffer, sweep, iOS cross-check, protocol decode, bleak CLI)
- Issues #9–#13 — Phase 2 (ESPHome bridge, headless)
- Issues #14–#17 — Phase 3 (LVGL touchscreen UI)
- Issues #18, #23, #24 — Phase 4 (RGB experiment — 4a direct probe, 4b show-scrub fallback, 4c photodiode contingency)
- Issues #19–#21 — Phase 5 (reliability, automations, hardware docs)
- Issue #22 — Phase 6 (v0.1.0 release)

**Why:** the user runs `/ghfix <n>` against these issues in numerical order. Knowing what phase `n` lives in avoids re-reading PLAN.md every time.

**How to apply:** when the user invokes `/ghfix <n>` on this repo, look up the phase here first. Phase 1 issues (#2–#8) are docs + protocol capture — the `/ghfix` workflow needs the non-iOS adaptation noted in `feedback_ghfix_non_ios_repo.md`. Verify against the actual issue body with `gh issue view` — labels and this map can drift as issues are reordered.
