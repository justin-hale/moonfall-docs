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
---

***Date***

## Players Present
- **Player** as **Character** — Class

## Plot Events
### Section Title
Narrative content...

---
```

## Commands
- `npm run build` - Build the Docusaurus site
- `npm run start` - Start dev server
- `python scripts/automate_session.py` - Generate session notes from transcript
