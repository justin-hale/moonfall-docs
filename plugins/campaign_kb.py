#!/usr/bin/env python3
"""
Shared parsing utilities for the campaign knowledge base (data/campaign-kb.md).

Used by:
- plugins/transcript_cleaner_ai_optimized.py (canonicalizing transcripts)
- scripts/lint_session.py (deterministic note linting)
- scripts/verify_session.py / scripts/update_kb.py (entity lists)
"""

import re
from pathlib import Path


def parse_aliases_field(aliases_field: str):
    """
    Parse a markdown table "Transcript Aliases" cell like:
    - "Silus", "Cyrus"
    into: ["Silus", "Cyrus"]
    """
    aliases_field = (aliases_field or "").strip()
    if not aliases_field:
        return []
    # Remove surrounding quotes for easier splitting.
    aliases_field = aliases_field.replace('"', '')
    return [a.strip() for a in aliases_field.split(',') if a.strip()]


def _table_rows(lines, start_heading, end_heading_prefix):
    """
    Parse a simple markdown table after a heading, until another heading starts.
    Returns the data rows split into cell lists (header + separator skipped).
    """
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == start_heading:
            start_idx = i
            break
    if start_idx is None:
        return []

    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith(end_heading_prefix):
            end_idx = j
            break

    rows = []
    seen_separator = False
    for ln in lines[start_idx:end_idx]:
        if not ln.strip().startswith("|"):
            continue
        if "---" in ln:
            seen_separator = True
            continue
        if not seen_separator:
            continue  # header row
        rows.append([p.strip() for p in ln.strip().strip("|").split("|")])
    return rows


def load_campaign_kb_mappings(kb_path: Path):
    """
    Returns:
      alias_to_canonical: maps transcript speaker/name aliases -> canonical character/NPC name
      known_transcription_replacements: maps common mis-transcriptions -> canonical spelling
    """
    if not kb_path.exists():
        return {}, {}

    kb_text = kb_path.read_text(encoding="utf-8")
    lines = kb_text.splitlines()

    alias_to_canonical = {}
    known_transcription_replacements = {}

    # --- DM mapping (e.g. "Christopher "Topher" Hooper" + Google Meet name) ---
    dm_start = None
    dm_end = len(lines)
    for i, line in enumerate(lines):
        if line.strip() == "### DM":
            dm_start = i
            break
    if dm_start is not None:
        for j in range(dm_start + 1, len(lines)):
            if lines[j].startswith("### Player Characters"):
                dm_end = j
                break
        dm_block = "\n".join(lines[dm_start:dm_end])
        dm_short = None
        dm_google_meet = None
        m_short = re.search(r'"([^"]+)"', dm_block)
        if m_short:
            dm_short = m_short.group(1).strip()
        m_meet = re.search(r"Google Meet:\s*([^)]+)\)", dm_block)
        if m_meet:
            dm_google_meet = m_meet.group(1).strip()

        if dm_short and dm_google_meet:
            alias_to_canonical[dm_google_meet] = dm_short
            # Also accept the plain short name.
            alias_to_canonical[dm_short] = dm_short

    # --- Player roster mapping (Active players) ---
    roster_rows = _table_rows(
        lines,
        start_heading="### Player Characters (Active)",
        end_heading_prefix="### Player Characters (Departed/Inactive)",
    )
    for parts in roster_rows:
        if len(parts) < 6:
            continue
        character = parts[0]
        player_name = parts[1]
        google_meet_name = parts[2]
        transcript_aliases_field = parts[3]

        # Map Google Meet name + player name + transcript aliases.
        if google_meet_name:
            alias_to_canonical[google_meet_name] = character
        if player_name:
            alias_to_canonical[player_name] = character
        for alias in parse_aliases_field(transcript_aliases_field):
            alias_to_canonical[alias] = character

    # --- Known transcription errors mapping ---
    errors_rows = _table_rows(
        lines,
        start_heading="## Known Transcription Errors",
        end_heading_prefix="## Active Plot Threads",
    )
    for parts in errors_rows:
        if len(parts) < 3:
            continue
        transcript_says = parts[0]
        should_be = parts[1]
        if transcript_says and should_be:
            known_transcription_replacements[transcript_says] = should_be

    return alias_to_canonical, known_transcription_replacements


def apply_replacements(text: str, replacements: dict, case_sensitive: bool = False):
    """Apply robust whole-token replacements.

    case_sensitive=True is required when rewriting prose: the KB maps
    "Brew" -> "Bru", and a case-insensitive pass would also corrupt
    ordinary words like "brew some coffee".
    """
    if not replacements:
        return text
    out = text
    flags = 0 if case_sensitive else re.IGNORECASE
    for says, should_be in replacements.items():
        if not says or says == should_be:
            continue
        # Replace whole word occurrences to avoid turning parts of longer strings.
        # This is intentionally conservative for names/aliases.
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(says) + r"(?![A-Za-z0-9_])"
        out = re.sub(pattern, should_be, out, flags=flags)
    return out


def load_kb_entities(kb_path: Path):
    """
    Parse the KB into entity lists for lint/verification.

    Returns a dict:
      canonical_names: set of character + NPC canonical names (first word forms too)
      aliases_by_canonical: {canonical: set(aliases)} incl. transcription-error forms
      locations: set of location names (and their aliases)
      player_names: set of real player names
      google_meet_names: set of Google Meet display names
      transcription_errors: {says: should_be} (identity rows skipped)
    """
    result = {
        "canonical_names": set(),
        "aliases_by_canonical": {},
        "locations": set(),
        "player_names": set(),
        "google_meet_names": set(),
        "transcription_errors": {},
    }
    if not kb_path.exists():
        return result

    lines = kb_path.read_text(encoding="utf-8").splitlines()

    def add_alias(canonical, alias):
        if not alias or alias == canonical:
            return
        result["aliases_by_canonical"].setdefault(canonical, set()).add(alias)

    def add_name_forms(raw_name):
        """Register a name plus any parenthetical alternate, e.g.
        'Lady Viper (Elizandra Legrand)' or 'Bru (Felonias Bru)'."""
        raw_name = raw_name.strip()
        if not raw_name:
            return None
        m = re.match(r"(.+?)\s*\(([^)]+)\)\s*$", raw_name)
        if m:
            primary = m.group(1).strip()
            secondary = m.group(2).strip()
            result["canonical_names"].add(primary)
            add_alias(primary, secondary)
            return primary
        result["canonical_names"].add(raw_name)
        return raw_name

    # DM
    dm_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "### DM":
            dm_idx = i
            break
    if dm_idx is not None:
        dm_end = len(lines)
        for j in range(dm_idx + 1, len(lines)):
            if lines[j].startswith("### Player Characters"):
                dm_end = j
                break
        dm_block = "\n".join(lines[dm_idx:dm_end])
        m_short = re.search(r'"([^"]+)"', dm_block)
        m_meet = re.search(r"Google Meet:\s*([^)]+)\)", dm_block)
        if m_short:
            result["canonical_names"].add(m_short.group(1).strip())
        if m_meet:
            result["google_meet_names"].add(m_meet.group(1).strip())

    # Active player characters
    for parts in _table_rows(lines, "### Player Characters (Active)",
                             "### Player Characters (Departed/Inactive)"):
        if len(parts) < 6:
            continue
        canonical = add_name_forms(parts[0])
        if not canonical:
            continue
        if parts[1]:
            result["player_names"].add(parts[1])
        if parts[2]:
            result["google_meet_names"].add(parts[2])
        for alias in parse_aliases_field(parts[3]):
            add_alias(canonical, alias)

    # Departed / inactive player characters
    for parts in _table_rows(lines, "### Player Characters (Departed/Inactive)",
                             "### NPCs"):
        if len(parts) < 2:
            continue
        add_name_forms(parts[0])

    # NPCs
    for parts in _table_rows(lines, "### NPCs (Recurring)", "## Locations"):
        if len(parts) < 2:
            continue
        canonical = add_name_forms(parts[0])
        if not canonical:
            continue
        if len(parts) >= 4:
            for alias in parse_aliases_field(parts[3]):
                add_alias(canonical, alias)

    # Locations
    for parts in _table_rows(lines, "## Locations", "## Known Transcription Errors"):
        if len(parts) < 2:
            continue
        name = parts[0].strip()
        if name:
            result["locations"].add(name)
        for alias in parse_aliases_field(parts[2] if len(parts) >= 3 else ""):
            result["locations"].add(alias)

    # Known transcription errors (skip identity rows like Scarlet -> Scarlet)
    for parts in _table_rows(lines, "## Known Transcription Errors",
                             "## Active Plot Threads"):
        if len(parts) < 2:
            continue
        says, should_be = parts[0], parts[1]
        if says and should_be and says != should_be:
            result["transcription_errors"][says] = should_be

    return result
