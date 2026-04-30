# Repo-committed memory

This tree is the **source of truth** for durable Claude/MemPalace memories about `colorsplash-xg-ha`. Everything here travels with the repo so another machine (or another contributor) can rebuild the local MemPalace wing from a fresh clone.

## Layout

```
docs/memory/
  feedback/           # how Claude should behave in this repo (ghfix adaptations, PR format, ...)
  issue-phase-map.md  # project facts — issue ↔ phase mapping
```

Each `.md` file has YAML frontmatter (`name`, `description`, `type`) followed by the memory body. Frontmatter matches the shape used by Claude Code's built-in memory system, so the same files work in either place.

## Rebuilding the MemPalace wing on a new machine

```sh
pip install mempalace             # if not already installed
mempalace mine /path/to/colorsplash-xg-ha
```

The wing name (`colorsplash_xg_ha`) and the room-to-directory routing are defined in `mempalace.yaml` at the repo root. Files under `docs/memory/feedback/` land in the `feedback` room; the rest of `docs/memory/` lands in `documentation`.

## Editing

- Edit the `.md` file here, commit, push
- On any machine that has a checkout, re-run `mempalace mine` to refresh the local palace
- If you want to author a new memory directly in the palace (via `mempalace_add_drawer`), remember to also write a file here or it will not survive on another machine

## What does **not** live here

- The MemPalace **knowledge graph** (`mempalace_kg_add` triples) and **agent diary** entries are palace-local only — they do not round-trip through this directory
- Ephemeral session state, task lists, plans, and per-conversation scratch
- Anything already documented in `docs/PLAN.md`, `docs/CAPTURING.md`, or the repo `README.md` — do not duplicate
