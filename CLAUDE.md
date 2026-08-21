# Moonfall Sessions - D&D Campaign Documentation Site

## Project Overview
This is a Docusaurus site (v3.9.2) serving as the documentation site for a D&D campaign called "Moonfall Sessions," hosted at moonfallsessions.com.

## Key Directories
- `docs/sessions/` - Session recaps (session-N.md, interlude-N.md)
- `docs/transcripts/` - Cleaned transcripts (.md and .json)
- `docs/npcs/` - NPC character pages
- `docs/locations/` - Location pages
- `data/campaign-kb.md` - Campaign knowledge base (canonical names, errors, plot threads)
- `data/campaign-state.md` - Auto-updating running memory of all sessions
- `data/publication-arc.json` - Publication meta-narrative config (writer personas, storyline beats)
- `scripts/` - Automation scripts (Python)
- `plugins/` - Transcript processing scripts

## Session Recap Generation
When creating or editing session recaps, always:
- Reference `data/campaign-kb.md` for correct character names, locations, and spelling
- Reference `data/campaign-state.md` for callbacks to previous sessions
- Follow the format and style of existing sessions in `docs/sessions/`
- Use the character roster in `data/campaign-kb.md` to map player names to character names

## Character Name Rules (CRITICAL)
- Bru is ALWAYS "Bru", NEVER "Brew"
- Elspeth is ALWAYS "Elspeth", NEVER "Ellsworth" or "Elizabeth"
- Leliana is ALWAYS "Leliana", NEVER "Liliana"
- Eldoran is ALWAYS "Eldoran", NEVER "Elderan"
- Greyport is ALWAYS "Greyport", NEVER "Grayport"
- Astro is ALWAYS "Astro", NEVER "Astra"

## Session File Format
```yaml
---
title: "N: Title"
date: YYYY-MM-DD
description: "One paragraph summary"
summary: "One paragraph summary"
podcastlink: ""
author: "Persona Name"        # sessions 58+ only, stamped by the generator
beat: "beat-id"               # sessions 58+ only, stamped by the generator
---

***Date***

*Byline line (sessions 58+, e.g. "Compiled by Vellum, Archival Construct of the Moonfall Chronicle")*

## Players Present
- **Player** as **Character** — Class

## Plot Events
### Section Title
Narrative content...

---
```

## Publication Meta-Narrative (sessions 58+)
The session notes are framed as an in-world publication, *The Moonfall Chronicle*, with fictional staff writers whose storyline unfolds across recaps. `data/publication-arc.json` is the single source of truth for personas, storyline beats, and per-beat voice directives — beats auto-advance by session number, and the generator (`scripts/automate_session.py`) stamps `author:`/`beat:` frontmatter and the byline deterministically.
- Editorial notes are italic blockquotes between narrative sections, signed with the writer's sigil (e.g. `— V.`, `— P.A.`). They comment on the writing, never contradict recorded events.
- Manual edits and `/fix-notes` corrections must preserve bylines and editorial notes.
- NEVER retroactively add personas, bylines, or editorial notes to sessions before 58.
- `data/campaign-state.md` and `data/campaign-kb.md` stay persona-neutral: record only in-world campaign events, never publication-meta content.
- The writers' conflict NEVER resolves on its own — only the DM flipping `finale.active` in `data/publication-arc.json` (after the party resolves it in-game) ends it.

## Correcting Published Notes
Run `/fix-notes <page URL or session number> — <what is wrong>` (`.claude/commands/fix-notes.md`). Paste the link straight from the live site — the last path segment is the filename stem, so `https://moonfallsessions.com/sessions/session-59/` resolves to `docs/sessions/session-59.md`. The workflow is: verify against the transcript (the only source of truth), fix every place the error landed, print a signed correction notice in the recap's own persona voice, and propagate to `data/campaign-state.md` and `data/campaign-kb.md`.
- The transcript decides. Never correct a detail you could not confirm in `docs/transcripts/` — ask instead.
- A session's correction is issued by the persona in ITS `author:` frontmatter, not whoever holds the masthead now. Sessions with no `author:` predate the arc and are corrected silently.
- Correction conventions (heading, placement, per-persona voice) live in the `corrections` block of `data/publication-arc.json`.
- Every correction gets an entry in the Session Correction Log in `data/campaign-kb.md`, plus new rows in the NPC and transcription-error tables where applicable.
- Corrections are never retracted or edited away — the amendment is part of the record.

## Commands
- `/fix-notes <page URL or session number> — <what is wrong>` - Correct a published recap (see above)
- `npm run build` - Build the Docusaurus site
- `npm run start` - Start dev server
- `python scripts/automate_session.py` - Generate session notes from transcript (also updates session stats)
- `python scripts/extract_session_stats.py --all` - Rebuild `data/session-stats.json` + `static/data/session-stats.csv` (deterministic, no API)
- `python scripts/analyze_session_personality.py --all [--local]` - Score player personalities per session via Claude Haiku (cached in `data/personality-cache/`)

## Session Stats
- `data/session-stats.json`, `data/session-stat-blocks.json` (slim slice for recap-page stat blocks), and `static/data/session-stats.csv` are GENERATED - never hand-edit; rerun the extractor instead
- The stats dashboard lives at `/stats` (`src/pages/stats.tsx`); per-session stat blocks are auto-injected on recap pages via `src/theme/DocItem/Content`
- The personality rubric in `analyze_session_personality.py` is frozen - changing it requires rescoring all sessions with `--force`
