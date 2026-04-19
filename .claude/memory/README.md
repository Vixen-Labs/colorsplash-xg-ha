# Claude Code memory — portable copy

These Markdown files are the **durable memories** Claude Code has
accumulated while working on this repo. They live here (checked into
git) so they travel across machines. The canonical runtime location
Claude Code reads from is **not** this directory — it is:

```
~/.claude/projects/<slug>/memory/
```

where `<slug>` is the absolute path of the repo working tree with
slashes replaced by dashes and a leading dash added.

Example slugs:

- `/Volumes/Junebug/mboszko/dev/colorsplash-xg-ha`
  → `-Volumes-Junebug-mboszko-dev-colorsplash-xg-ha`
- `/Users/mboszko/dev/colorsplash-xg-ha`
  → `-Users-mboszko-dev-colorsplash-xg-ha`

Because the slug encodes the absolute path, the memory directory has a
different name on every machine.

## Sync to a new Mac

After cloning the repo on a new machine:

```sh
# from the repo root
SLUG="-$(pwd | sed 's|/|-|g')"
DEST="$HOME/.claude/projects/$SLUG/memory"
mkdir -p "$DEST"
cp .claude/memory/*.md "$DEST/"
```

## Sync back to this repo (to capture new memories)

After a session where Claude Code added or updated memories:

```sh
# from the repo root
SLUG="-$(pwd | sed 's|/|-|g')"
SRC="$HOME/.claude/projects/$SLUG/memory"
cp "$SRC"/*.md .claude/memory/
git add .claude/memory
git diff --cached --stat .claude/memory   # review before committing
```

## What NOT to commit

`.claude/settings.local.json` is gitignored. It's a per-user permission
allow-list — pre-approvals for specific `Bash(...)` commands during a
session — and is not meaningful on another machine or for another
person.
