#!/usr/bin/env python3
"""
Session Stats Extractor for the Moonfall campaign site.

Deterministic (no API calls) extraction of per-session statistics from:
  - docs/transcripts/*.json  (rich: per-block speaker + start_seconds)
  - docs/transcripts/*.md    (older format: **Speaker:** blocks + 10-min markers)
  - docs/sessions/*.md       (recap frontmatter + "Players Present" lists)
  - data/campaign-kb.md      (canonical names + aliases for entity matching)
  - data/personality-cache/  (optional LLM results from analyze_session_personality.py)

Outputs:
  - data/session-stats.json        (canonical dataset consumed by the site)
  - static/data/session-stats.csv  (flat per-session export)

Usage:
    python3 scripts/extract_session_stats.py --all
    python3 scripts/extract_session_stats.py --date 2026-07-17

Both forms rebuild the full dataset (extraction is cheap and idempotent);
--date exists so the automation pipeline can pass the session it just
processed and fail loudly if that date produced no stats.

The generated files should never be hand-edited — rerun this script instead.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "plugins"))

from transcript_cleaner_ai_optimized import (  # noqa: E402
    apply_replacements,
    load_campaign_kb_mappings,
    parse_aliases_field,
)

SCHEMA_VERSION = "1.0"

TRANSCRIPTS_DIR = PROJECT_ROOT / "docs" / "transcripts"
SESSIONS_DIR = PROJECT_ROOT / "docs" / "sessions"
KB_PATH = PROJECT_ROOT / "data" / "campaign-kb.md"
PERSONALITY_CACHE_DIR = PROJECT_ROOT / "data" / "personality-cache"
OUTPUT_JSON = PROJECT_ROOT / "data" / "session-stats.json"
OUTPUT_CSV = PROJECT_ROOT / "static" / "data" / "session-stats.csv"

# Names that are also ordinary English words must match case-sensitively,
# otherwise "the red door" counts as a mention of Red.
CASE_SENSITIVE_TERMS = {"Red", "Lark", "Scarlet", "Victor"}

# Speaker attribution overrides for sessions before a character change that
# campaign-kb.md (which only tracks the *current* roster) can't express.
# Leliana emerged from Helisanna in Session 34 (2025-09-26); before that,
# Luke's speaker blocks belong to Helisanna.
DATED_SPEAKER_OVERRIDES = [
    # (google_meet_name, before_date_exclusive, canonical_character)
    ("Luke Neverisky", "2025-09-26", "Helisanna Doomfall"),
]

# When a block's start gap to the next block exceeds this, assume the speaker
# wasn't talking the whole time (scene pause, DM monologue elsewhere, etc.).
TALK_GAP_CAP_SECONDS = 60
LAST_BLOCK_TALK_SECONDS = 15

FORBIDDEN_SPELLINGS = ["Brew", "Grayport", "Elderan", "Liliana", "Astra", "Ellsworth"]

NAT20_RE = re.compile(r"\bnat(?:ural)?\s*(?:20|twenty)\b", re.IGNORECASE)
NAT1_RE = re.compile(r"\bnat(?:ural)?\s*(?:1|one)\b(?!\d)", re.IGNORECASE)

MD_BLOCK_RE = re.compile(r"^\*\*(.+?):\*\* ?(.*)$")
MD_MARKER_RE = re.compile(r"^### \[(\d{2}):(\d{2}):(\d{2})\]")
FRONTMATTER_KV_RE = re.compile(r"^([A-Za-z_]+):\s*(.*)$")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")


# --------------------------------------------------------------------------- #
#  Campaign KB parsing (roster, NPCs, locations)                               #
# --------------------------------------------------------------------------- #

def parse_kb_table(kb_lines, start_heading, end_heading_prefix):
    """Return the data rows (list of cell lists) of a markdown table that
    follows *start_heading*, stopping at the next heading with the prefix."""
    start_idx = None
    for i, line in enumerate(kb_lines):
        if line.strip() == start_heading:
            start_idx = i
            break
    if start_idx is None:
        return []
    end_idx = len(kb_lines)
    for j in range(start_idx + 1, len(kb_lines)):
        if kb_lines[j].startswith(end_heading_prefix):
            end_idx = j
            break
    rows = []
    for ln in kb_lines[start_idx:end_idx]:
        ln = ln.strip()
        if not ln.startswith("|") or "---" in ln:
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        rows.append(cells)
    return rows[1:] if rows else []  # drop header row


def display_name(canonical):
    """'Bru (Felonias Bru)' -> 'Bru'; 'Silas Fairbanks' -> 'Silas'."""
    base = re.sub(r"\s*\(.*\)$", "", canonical).strip()
    return base.split()[0] if base else canonical


def load_campaign_entities():
    """Build the roster and the entity-mention index from campaign-kb.md."""
    kb_lines = KB_PATH.read_text(encoding="utf-8").splitlines()

    roster = {}  # canonical -> {display, player, role}
    roster["Topher"] = {"display": "Topher", "player": "Topher", "role": "dm"}

    for cells in parse_kb_table(kb_lines, "### Player Characters (Active)",
                                "### Player Characters (Departed/Inactive)"):
        if len(cells) < 6:
            continue
        canonical, player = cells[0], cells[1]
        roster[canonical] = {
            "display": display_name(canonical),
            "player": player,
            "role": "pc",
        }

    for cells in parse_kb_table(kb_lines, "### Player Characters (Departed/Inactive)",
                                "### NPCs (Recurring)"):
        if len(cells) < 4:
            continue
        canonical = cells[0]
        roster[canonical] = {
            "display": display_name(canonical),
            "player": None,
            "role": "pc",
        }

    def build_terms(name_cell, aliases_cell):
        """Mention-match terms for one entity: outer name, parenthetical
        inner name, and each transcript alias."""
        terms = []
        outer = re.sub(r"\s*\(.*\)$", "", name_cell).strip()
        if outer:
            terms.append(outer)
        inner = re.search(r"\(([^)]+)\)", name_cell)
        if inner:
            terms.append(inner.group(1).strip())
        terms.extend(parse_aliases_field(aliases_cell))
        return terms

    npc_terms = {}  # display -> [terms]
    for cells in parse_kb_table(kb_lines, "### NPCs (Recurring)", "## Locations"):
        if len(cells) < 4:
            continue
        label = re.sub(r"\s*\(.*\)$", "", cells[0]).strip()
        npc_terms[label] = build_terms(cells[0], cells[3])

    location_terms = {}
    for cells in parse_kb_table(kb_lines, "## Locations", "## Known Transcription Errors"):
        if len(cells) < 3:
            continue
        label = cells[1] or cells[0]
        location_terms[label] = build_terms(cells[0], cells[2])

    pc_terms = {}
    for canonical, info in roster.items():
        if info["role"] == "dm":
            continue
        pc_terms[info["display"]] = build_terms(canonical, "")

    return roster, npc_terms, location_terms, pc_terms


def compile_mention_patterns(terms_by_label):
    compiled = {}
    for label, terms in terms_by_label.items():
        patterns = []
        for term in dict.fromkeys(t for t in terms if t):
            flags = 0 if term in CASE_SENSITIVE_TERMS else re.IGNORECASE
            patterns.append(re.compile(
                r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])", flags))
        compiled[label] = patterns
    return compiled


def count_mentions(text, compiled_by_label):
    counts = {}
    for label, patterns in compiled_by_label.items():
        n = sum(len(p.findall(text)) for p in patterns)
        if n:
            counts[label] = n
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


# --------------------------------------------------------------------------- #
#  Transcript parsing                                                          #
# --------------------------------------------------------------------------- #

def resolve_speaker(speaker_raw, date, alias_to_canonical, replacements):
    """Map a raw transcript speaker label to a canonical roster name."""
    for meet_name, before_date, canonical in DATED_SPEAKER_OVERRIDES:
        if speaker_raw == meet_name and date < before_date:
            return canonical
    normalized = apply_replacements(speaker_raw, replacements)
    return alias_to_canonical.get(normalized) or alias_to_canonical.get(speaker_raw)


def parse_json_transcript(path, date, alias_to_canonical, replacements):
    data = json.loads(path.read_text(encoding="utf-8"))
    blocks = []
    for b in data.get("blocks", []):
        canonical = b.get("speaker_canonical") or resolve_speaker(
            b.get("speaker_raw", ""), date, alias_to_canonical, replacements)
        for meet_name, before_date, override in DATED_SPEAKER_OVERRIDES:
            if b.get("speaker_raw") == meet_name and date < before_date:
                canonical = override
        blocks.append({
            "start_seconds": b.get("start_seconds", 0),
            "canonical": canonical or b.get("speaker_normalized") or b.get("speaker_raw"),
            "text": b.get("text", ""),
        })
    duration = blocks[-1]["start_seconds"] if blocks else 0
    return blocks, duration, "exact"


def parse_md_transcript(path, date, alias_to_canonical, replacements):
    blocks = []
    last_marker_seconds = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        marker = MD_MARKER_RE.match(line)
        if marker:
            h, m, s = map(int, marker.groups())
            last_marker_seconds = h * 3600 + m * 60 + s
            continue
        block = MD_BLOCK_RE.match(line)
        if block:
            speaker_raw, text = block.group(1).strip(), block.group(2).strip()
            canonical = resolve_speaker(speaker_raw, date, alias_to_canonical, replacements)
            blocks.append({
                "start_seconds": None,
                "canonical": canonical or speaker_raw,
                "text": apply_replacements(text, replacements),
            })
    # Content continues past the last 10-minute marker for up to 10 more
    # minutes; split the difference for the estimate.
    duration = (last_marker_seconds + 300) if last_marker_seconds else None
    return blocks, duration, "approx"


def summarize_speakers(blocks, roster, timing_quality):
    """Per-speaker block/word/talk-time totals from parsed blocks."""
    per = {}
    order = []
    for i, b in enumerate(blocks):
        key = b["canonical"]
        if key not in per:
            per[key] = {"blocks": 0, "words": 0, "talk_seconds": 0}
            order.append(key)
        per[key]["blocks"] += 1
        per[key]["words"] += len(b["text"].split())
        if timing_quality == "exact" and b["start_seconds"] is not None:
            if i + 1 < len(blocks) and blocks[i + 1]["start_seconds"] is not None:
                gap = blocks[i + 1]["start_seconds"] - b["start_seconds"]
                per[key]["talk_seconds"] += max(0, min(gap, TALK_GAP_CAP_SECONDS))
            else:
                per[key]["talk_seconds"] += LAST_BLOCK_TALK_SECONDS

    total_words = sum(v["words"] for v in per.values()) or 1
    speakers = []
    for key in order:
        info = roster.get(key)
        speakers.append({
            "name": info["display"] if info else key,
            "canonical": key,
            "role": info["role"] if info else "guest",
            "player": info["player"] if info else None,
            "blocks": per[key]["blocks"],
            "words": per[key]["words"],
            "talk_seconds_est": per[key]["talk_seconds"] if timing_quality == "exact" else None,
            "word_share": round(per[key]["words"] / total_words, 4),
        })
    speakers.sort(key=lambda s: -s["words"])
    return speakers, sum(v["words"] for v in per.values()), len(blocks)


# --------------------------------------------------------------------------- #
#  Recap (session file) parsing                                                #
# --------------------------------------------------------------------------- #

def parse_frontmatter(text):
    fm = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return fm
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = FRONTMATTER_KV_RE.match(line)
        if m:
            key, value = m.group(1), m.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            fm[key] = value.replace('\\"', '"')
    return fm


PLAYERS_HEADING_RE = re.compile(
    r"^#{2,3} (Players Present|Party Members Present|Party Members)\s*$")


def parse_players_present(text, alias_to_canonical, roster):
    """Extract PC display names from a recap's attendance list, if present."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if PLAYERS_HEADING_RE.match(line.strip()):
            start = i + 1
            break
    if start is None:
        return None
    names = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("#") or stripped == "---":
            break
        if not stripped.startswith("-"):
            continue
        if "(DM)" in stripped or "(GM)" in stripped:
            continue
        # Some recaps link the name: **[Elspeth](/player-characters/elspeth)**
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", stripped)
        bolds = BOLD_RE.findall(cleaned)
        if not bolds:
            continue
        # Older lists embed the name in prose ("Retired Detective Olivia
        # Cooper", 'Felonias "Bru" Bru'), so scan the line for the earliest
        # roster-name match rather than trusting bold positions.
        earliest = None
        for canonical, info in roster.items():
            if info["role"] == "dm":
                continue
            for term in {info["display"], canonical.split()[0]}:
                m = re.search(r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])",
                              cleaned)
                if m and (earliest is None or m.start() < earliest[0]):
                    earliest = (m.start(), info["display"])
        if earliest:
            names.append(earliest[1])
            continue
        # "- **Player** as **Character** — Class" -> take the character;
        # otherwise the first bold name is the best candidate.
        candidate = bolds[1] if (len(bolds) >= 2 and " as " in cleaned) else bolds[0]
        canonical = alias_to_canonical.get(candidate, candidate)
        info = roster.get(canonical)
        names.append(info["display"] if info else display_name(candidate))
    return [n for i, n in enumerate(names) if n not in names[:i]] or None


# --------------------------------------------------------------------------- #
#  Personality cache merge                                                     #
# --------------------------------------------------------------------------- #

def load_personality_cache():
    cache = {}
    if not PERSONALITY_CACHE_DIR.exists():
        return cache
    for path in sorted(PERSONALITY_CACHE_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            date = data.get("date") or path.stem
            cache[date] = data
        except (json.JSONDecodeError, OSError) as e:
            print(f"  Warning: skipping unreadable personality cache {path.name}: {e}")
    return cache


def personality_for_session(cache_entry, replacements):
    if not cache_entry:
        return None
    scores, evidence = {}, {}
    for player, result in (cache_entry.get("players") or {}).items():
        scores[player] = result.get("scores", {})
        evidence[player] = {
            axis: apply_replacements(quote or "", replacements)
            for axis, quote in (result.get("evidence") or {}).items()
        }
    superlatives = {}
    for key, value in (cache_entry.get("superlatives") or {}).items():
        if isinstance(value, dict):
            superlatives[key] = {
                "player": value.get("player"),
                "quote": apply_replacements(value.get("quote") or "", replacements),
            }
        else:
            superlatives[key] = value
    return {"scores": scores, "evidence": evidence, "superlatives": superlatives}


# --------------------------------------------------------------------------- #
#  Aggregation                                                                 #
# --------------------------------------------------------------------------- #

PERSONALITY_AXES = ["chaos", "heroism", "comedy", "immersion", "strategy", "curiosity"]
SUPERLATIVE_KEYS = ["mvp", "best_joke", "most_chaotic"]


def build_aggregate(sessions, roster):
    with_transcript = [s for s in sessions if s["has_transcript"]]

    speaker_totals = {}
    for s in with_transcript:
        for sp in s["speakers"]:
            t = speaker_totals.setdefault(sp["name"], {
                "name": sp["name"], "canonical": sp["canonical"], "role": sp["role"],
                "player": sp["player"], "sessions": 0, "blocks": 0, "words": 0,
                "talk_seconds_est": 0,
            })
            t["sessions"] += 1
            t["blocks"] += sp["blocks"]
            t["words"] += sp["words"]
            t["talk_seconds_est"] += sp["talk_seconds_est"] or 0

    def merge_counts(field):
        totals = {}
        for s in with_transcript:
            for label, n in s["mentions"][field].items():
                totals[label] = totals.get(label, 0) + n
        return dict(sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])))

    # Per-player personality aggregate: mean score per axis, the strongest
    # evidence quote per axis, and superlative tallies.
    players = {}
    for s in sessions:
        p = s.get("personality")
        if not p:
            continue
        for player, axes in p["scores"].items():
            agg = players.setdefault(player, {
                "sessions_scored": 0,
                "axis_sums": {a: 0 for a in PERSONALITY_AXES},
                "axis_counts": {a: 0 for a in PERSONALITY_AXES},
                "best": {a: (0, None, None) for a in PERSONALITY_AXES},
                "superlatives": {k: 0 for k in SUPERLATIVE_KEYS},
                "decision_driver": 0,
            })
            agg["sessions_scored"] += 1
            for axis in PERSONALITY_AXES:
                score = axes.get(axis)
                if score is None:
                    continue
                agg["axis_sums"][axis] += score
                agg["axis_counts"][axis] += 1
                quote = (p["evidence"].get(player) or {}).get(axis)
                if score > agg["best"][axis][0] and quote:
                    agg["best"][axis] = (score, quote, s["id"])
        for key in SUPERLATIVE_KEYS:
            winner = (p["superlatives"].get(key) or {}).get("player")
            if winner in players:
                players[winner]["superlatives"][key] += 1
        driver = p["superlatives"].get("decision_driver")
        if driver in players:
            players[driver]["decision_driver"] += 1

    personality_by_player = {}
    for player, agg in sorted(players.items()):
        mean_scores = {
            axis: round(agg["axis_sums"][axis] / agg["axis_counts"][axis], 1)
            for axis in PERSONALITY_AXES if agg["axis_counts"][axis]
        }
        signature = {
            axis: {"quote": agg["best"][axis][1], "session": agg["best"][axis][2],
                   "score": agg["best"][axis][0]}
            for axis in PERSONALITY_AXES if agg["best"][axis][1]
        }
        personality_by_player[player] = {
            "sessions_scored": agg["sessions_scored"],
            "mean_scores": mean_scores,
            "signature_evidence": signature,
            "superlative_counts": {**agg["superlatives"],
                                   "decision_driver": agg["decision_driver"]},
        }

    return {
        "total_sessions": len(sessions),
        "sessions_with_transcripts": len(with_transcript),
        "total_words": sum(s["word_count"] or 0 for s in with_transcript),
        "total_blocks": sum(s["block_count"] or 0 for s in with_transcript),
        "total_duration_seconds": sum(s["duration_seconds"] or 0 for s in with_transcript),
        "speaker_totals": sorted(speaker_totals.values(), key=lambda t: -t["words"]),
        "top_npcs": merge_counts("npcs"),
        "top_locations": merge_counts("locations"),
        "top_pcs_mentioned": merge_counts("pcs"),
        "nat20_mentions": sum(s["fun"]["nat20_mentions"] for s in with_transcript),
        "nat1_mentions": sum(s["fun"]["nat1_mentions"] for s in with_transcript),
        "personality_by_player": personality_by_player,
    }


# --------------------------------------------------------------------------- #
#  Main extraction                                                             #
# --------------------------------------------------------------------------- #

def extract_all():
    alias_to_canonical, replacements = load_campaign_kb_mappings(KB_PATH)
    roster, npc_terms, location_terms, pc_terms = load_campaign_entities()
    npc_patterns = compile_mention_patterns(npc_terms)
    location_patterns = compile_mention_patterns(location_terms)
    pc_patterns = compile_mention_patterns(pc_terms)
    personality_cache = load_personality_cache()

    # Index transcripts by date; prefer .json over .md for the same date.
    transcripts = {}
    for path in sorted(TRANSCRIPTS_DIR.glob("*.md")):
        transcripts[path.stem] = path
    for path in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        transcripts[path.stem] = path

    sessions = []
    used_transcript_dates = set()
    session_files = sorted(SESSIONS_DIR.glob("session-*.md")) + \
        sorted(SESSIONS_DIR.glob("interlude-*.md"))
    for path in session_files:
        m = re.match(r"(session|interlude)-(\d+)\.md", path.name)
        if not m:
            continue
        stype, number = m.group(1), int(m.group(2))
        text = path.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        date = fm.get("date", "")

        record = {
            "id": path.stem,
            "type": stype,
            "number": number,
            "title": fm.get("title", path.stem),
            "date": date,
            "href": f"/sessions/{path.stem}/",
            "has_transcript": False,
            "transcript_format": None,
            "timing_quality": "none",
            "duration_seconds": None,
            "block_count": None,
            "word_count": None,
            "speakers": [],
            "players_present": None,
            "attendance_source": "none",
            "mentions": {"npcs": {}, "locations": {}, "pcs": {}},
            "fun": {"nat20_mentions": 0, "nat1_mentions": 0},
            "personality": None,
        }

        recap_players = parse_players_present(text, alias_to_canonical, roster)
        if recap_players:
            record["players_present"] = recap_players
            record["attendance_source"] = "recap"

        tpath = transcripts.get(date)
        if tpath is not None:
            used_transcript_dates.add(date)
            if tpath.suffix == ".json":
                blocks, duration, quality = parse_json_transcript(
                    tpath, date, alias_to_canonical, replacements)
            else:
                blocks, duration, quality = parse_md_transcript(
                    tpath, date, alias_to_canonical, replacements)
            speakers, word_count, block_count = summarize_speakers(blocks, roster, quality)
            full_text = "\n".join(b["text"] for b in blocks)

            record.update({
                "has_transcript": True,
                "transcript_format": tpath.suffix.lstrip("."),
                "timing_quality": quality,
                "duration_seconds": duration,
                "block_count": block_count,
                "word_count": word_count,
                "speakers": speakers,
                "mentions": {
                    "npcs": count_mentions(full_text, npc_patterns),
                    "locations": count_mentions(full_text, location_patterns),
                    "pcs": count_mentions(full_text, pc_patterns),
                },
                "fun": {
                    "nat20_mentions": len(NAT20_RE.findall(full_text)),
                    "nat1_mentions": len(NAT1_RE.findall(full_text)),
                },
            })
            pcs_present = [s["name"] for s in speakers if s["role"] == "pc"]
            if pcs_present:
                record["players_present"] = pcs_present
                record["attendance_source"] = "transcript"

        record["personality"] = personality_for_session(
            personality_cache.get(date), replacements)
        sessions.append(record)

    unmatched = sorted(set(transcripts) - used_transcript_dates)
    if unmatched:
        print(f"  Warning: transcripts with no matching recap date: {', '.join(unmatched)}")

    sessions.sort(key=lambda s: (s["date"], s["type"], s["number"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "scripts/extract_session_stats.py",
        "sessions": sessions,
        "aggregate": build_aggregate(sessions, roster),
    }


def validate(dataset):
    blob = json.dumps(dataset, ensure_ascii=False)
    problems = []
    for bad in FORBIDDEN_SPELLINGS:
        pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(bad) + r"(?![A-Za-z0-9_])")
        n = len(pattern.findall(blob))
        if n:
            problems.append(f"forbidden spelling '{bad}' appears {n}x in output")
    for s in dataset["sessions"]:
        p = s.get("personality")
        if not p:
            continue
        for player, axes in p["scores"].items():
            for axis, score in axes.items():
                if not isinstance(score, (int, float)) or not (1 <= score <= 20):
                    problems.append(f"{s['id']}: {player}.{axis} score {score!r} outside [1,20]")
    if problems:
        for p in problems:
            print(f"  VALIDATION ERROR: {p}")
        raise SystemExit(1)


def write_csv(dataset, csv_path):
    roster_names = ["Topher", "Silas", "Bru", "Elspeth", "Leliana", "Olivia",
                    "Ohma", "Helisanna", "Red", "Jasper"]
    fields = ["id", "type", "number", "title", "date", "timing_quality",
              "duration_minutes", "block_count", "word_count",
              "players_present", "attendance_source",
              "nat20_mentions", "nat1_mentions", "top_npc", "top_location"]
    fields += [f"words_{n}" for n in roster_names]

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for s in dataset["sessions"]:
            words_by_name = {sp["name"]: sp["words"] for sp in s["speakers"]}
            row = {
                "id": s["id"], "type": s["type"], "number": s["number"],
                "title": s["title"], "date": s["date"],
                "timing_quality": s["timing_quality"],
                "duration_minutes": round(s["duration_seconds"] / 60)
                if s["duration_seconds"] else "",
                "block_count": s["block_count"] or "",
                "word_count": s["word_count"] or "",
                "players_present": "; ".join(s["players_present"] or []),
                "attendance_source": s["attendance_source"],
                "nat20_mentions": s["fun"]["nat20_mentions"],
                "nat1_mentions": s["fun"]["nat1_mentions"],
                "top_npc": next(iter(s["mentions"]["npcs"]), ""),
                "top_location": next(iter(s["mentions"]["locations"]), ""),
            }
            for n in roster_names:
                row[f"words_{n}"] = words_by_name.get(n, "")
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Extract per-session campaign stats")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Rebuild the full dataset")
    group.add_argument("--date", help="Rebuild and verify this session date exists (YYYY-MM-DD)")
    args = parser.parse_args()

    print("Extracting session stats...")
    dataset = extract_all()
    validate(dataset)

    if args.date:
        match = [s for s in dataset["sessions"] if s["date"] == args.date]
        if not match:
            print(f"Error: no session recap found with date {args.date}")
            raise SystemExit(1)
        print(f"  Session for {args.date}: {', '.join(s['id'] for s in match)}")

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
        f.write("\n")
    write_csv(dataset, OUTPUT_CSV)

    agg = dataset["aggregate"]
    scored = sum(1 for s in dataset["sessions"] if s["personality"])
    print(f"  {agg['total_sessions']} sessions ({agg['sessions_with_transcripts']} with transcripts, "
          f"{scored} with personality scores)")
    print(f"  {agg['total_words']:,} words across {agg['total_duration_seconds'] / 3600:.1f} hours")
    print(f"  Wrote {OUTPUT_JSON.relative_to(PROJECT_ROOT)}")
    print(f"  Wrote {OUTPUT_CSV.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
