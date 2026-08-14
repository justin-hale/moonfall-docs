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

## Commands
- `npm run build` - Build the Docusaurus site
- `npm run start` - Start dev server
- `python scripts/automate_session.py` - Generate session notes from transcript
