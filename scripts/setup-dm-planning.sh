#!/usr/bin/env bash
# Sets up the local dm-planning folder (gitignored, never pushed).
# Re-run safely — won't overwrite existing files.

set -euo pipefail
cd "$(dirname "$0")/.."

DIR="dm-planning"
ADV="$DIR/adventures"

mkdir -p "$ADV"

# ── README ──────────────────────────────────────────────────────────────────

if [ ! -f "$DIR/README.md" ]; then
cat > "$DIR/README.md" << 'EOF'
# DM Planning

This folder is **gitignored** — nothing here is committed or pushed. Justin can't see it.

## Usage

Create a new adventure:

```
cp _adventure.md adventures/my-adventure-name.md
```

Fill in the sections. Each adventure should cover ~2–3 sessions and fit on one page.

Cross-reference published docs with relative paths, e.g. `../docs/npcs/helja-ungar.md`
or use site links like `/npcs/helja-ungar`.
EOF
fi

# ── Adventure template ──────────────────────────────────────────────────────

if [ ! -f "$DIR/_adventure.md" ]; then
cat > "$DIR/_adventure.md" << 'TEMPLATE'
# Adventure Name

**Sessions**: ~2–3 | **Level**: X | **Location**: [link]

## Strong Start

The opening scene that pulls players in immediately.

## Scenes

- Scene or situation (not a sequence — players choose the order)
- Scene or situation
- Scene or situation

## Secrets & Clues

- Discovery (tied to any scene, not a specific one)
- Discovery
- Discovery

## Key NPCs

- **Name** — Want. Will do X if players don't intervene. ([npc doc link])
- **Name** — Want. Reaction to players.

## Locations

- **Place** — One-line description, what makes it interesting. ([location doc link])

## Combat

Daggerheart-style: DM and players alternate actions. No initiative.

### Enemies

> *Stat block format is a starting point — refine as we playtest.*

| Name | HP | AC | Attack | Special |
|------|---:|---:|--------|---------|
| Enemy | 12 | 14 | Slash +5 (1d8+3) | On kill: explodes |

### Environment

- **Hazard or feature** — what it does, who can use it
- **Shift** — something that changes mid-fight (reinforcements, collapse, fire spreads)

### DM Moves (on failed player rolls or when tension needs to rise)

- Move to use when players fail
- Move to use when pacing slows

## Treasure & Rewards

- Item, gold, favor, or story reward

## Campaign Hooks

- **Thread name** — how this adventure connects to or advances it
- **New thread** — what this adventure sets up for later
TEMPLATE
fi

echo "dm-planning/ is ready. Start with: cp $DIR/_adventure.md $ADV/your-adventure.md"
