"""Unit tests for the deterministic session-stats extractor.

Run with:  python -m pytest scripts/tests/ -q

These use synthetic fixtures only — they must not depend on the real
transcripts or recap files, so they stay fast and stable as the campaign
grows.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extract_session_stats as ess  # noqa: E402


@pytest.fixture(scope="module")
def kb():
    alias_to_canonical, replacements = ess.load_campaign_kb_mappings(ess.KB_PATH)
    return alias_to_canonical, replacements


@pytest.fixture(scope="module")
def roster():
    roster, npc_terms, location_terms, pc_terms = ess.load_campaign_entities()
    return roster


# --------------------------------------------------------------------------- #
#  Markdown transcript parsing                                                 #
# --------------------------------------------------------------------------- #

MD_TRANSCRIPT = """\
**Christopher Hooper:** Welcome back to the table everyone.

**Tyram:** Silas checks the door for traps.

### [00:10:00]

**Justin Hale:** Brew pulls out a wrench. I mean Bru.

### [00:20:00]

**Luke Neverisky:** I sing a song about Grayport.
"""


def test_md_transcript_blocks_and_duration(tmp_path, kb):
    alias_to_canonical, replacements = kb
    path = tmp_path / "2026-01-01.md"
    path.write_text(MD_TRANSCRIPT, encoding="utf-8")
    blocks, duration, quality = ess.parse_md_transcript(
        path, "2026-01-01", alias_to_canonical, replacements)

    assert quality == "approx"
    assert len(blocks) == 4
    # Duration estimated from the last 10-minute marker (+ midpoint).
    assert duration == 20 * 60 + 300
    # Google Meet names resolve to canonical characters.
    speakers = [b["canonical"] for b in blocks]
    assert speakers[0] == "Topher"
    assert speakers[1] == "Silas Fairbanks"
    assert speakers[2] == "Bru (Felonias Bru)"
    # Known transcription errors are corrected in block text.
    assert "Brew" not in blocks[2]["text"]
    assert "Bru" in blocks[2]["text"]
    assert "Grayport" not in blocks[3]["text"]
    assert "Greyport" in blocks[3]["text"]


def test_dated_speaker_override(tmp_path, kb):
    """Before Leliana emerged (Session 34), Luke's speaker was Helisanna."""
    alias_to_canonical, replacements = kb
    path = tmp_path / "2025-09-12.md"
    path.write_text("**Luke Neverisky:** I cast a spell.\n", encoding="utf-8")
    blocks, _, _ = ess.parse_md_transcript(
        path, "2025-09-12", alias_to_canonical, replacements)
    assert blocks[0]["canonical"] == "Helisanna Doomfall"

    blocks, _, _ = ess.parse_md_transcript(
        path, "2026-01-01", alias_to_canonical, replacements)
    assert blocks[0]["canonical"] == "Leliana Goldspring"


# --------------------------------------------------------------------------- #
#  Recap parsing                                                               #
# --------------------------------------------------------------------------- #

def test_frontmatter_quote_stripping():
    fm = ess.parse_frontmatter(
        "---\n"
        'title: "46: Not Dead Yet"\n'
        "date: '2025-11-14'\n"
        "summary: plain value\n"
        "---\n"
        "body\n")
    assert fm["title"] == "46: Not Dead Yet"
    assert fm["date"] == "2025-11-14"
    assert fm["summary"] == "plain value"


MODERN_ATTENDANCE = """\
## Players Present

- **Topher** (DM)
- **Taylor Ramsey** as **Silas Fairbanks** — Halfling Rogue/Sorcerer
- **Justin Hale** as **Bru** — Goblin Artificer

---
"""

LINKED_ATTENDANCE = """\
## Party Members Present
- **[Helisanna](/player-characters/helisanna)** – Human Bard/Warlock
- **Felonias "[Bru](/player-characters/bru)" [Bru](/player-characters/bru)** – Goblin Artificer
- **Retired Detective [Olivia](/player-characters/olivia) Cooper** – Dwarf Paladin
"""


def test_players_present_modern_format(kb, roster):
    alias_to_canonical, _ = kb
    players = ess.parse_players_present(MODERN_ATTENDANCE, alias_to_canonical, roster)
    # DM line skipped; character (not player) names, display form.
    assert players == ["Silas", "Bru"]


def test_players_present_linked_prose_format(kb, roster):
    alias_to_canonical, _ = kb
    players = ess.parse_players_present(LINKED_ATTENDANCE, alias_to_canonical, roster)
    assert players == ["Helisanna", "Bru", "Olivia"]


def test_players_present_absent_returns_none(kb, roster):
    alias_to_canonical, _ = kb
    assert ess.parse_players_present("## Plot Events\n- stuff\n",
                                     alias_to_canonical, roster) is None


# --------------------------------------------------------------------------- #
#  Names and mentions                                                          #
# --------------------------------------------------------------------------- #

def test_display_name():
    assert ess.display_name("Bru (Felonias Bru)") == "Bru"
    assert ess.display_name("Silas Fairbanks") == "Silas"
    assert ess.display_name("Red (Thurnok Skyhammer)") == "Red"


def test_case_sensitive_mention_terms():
    """'Red' the PC must not match 'red' the color."""
    patterns = ess.compile_mention_patterns({"Red": ["Red"]})
    assert ess.count_mentions("Red waves. The red door opens. RED ALERT.",
                              patterns) == {"Red": 1}


def test_case_insensitive_mention_terms_with_aliases():
    patterns = ess.compile_mention_patterns({"Astro": ["Astro", "Astra"]})
    counts = ess.count_mentions("astro spoke to Astra about Astro's orb.", patterns)
    assert counts == {"Astro": 3}


def test_mentions_are_whole_word():
    patterns = ess.compile_mention_patterns({"Iro": ["Iro"]})
    assert ess.count_mentions("The environment ironically has no Iro.",
                              patterns) == {"Iro": 1}


# --------------------------------------------------------------------------- #
#  Validation                                                                  #
# --------------------------------------------------------------------------- #

def test_forbidden_spelling_validation_fails():
    dataset = {"sessions": [{"id": "session-1", "title": "Brew goes to Grayport",
                             "personality": None}]}
    with pytest.raises(SystemExit):
        ess.validate(dataset)


def test_personality_score_range_validation():
    dataset = {"sessions": [{
        "id": "session-1", "title": "ok",
        "personality": {"scores": {"Bru": {"chaos": 25}}},
    }]}
    with pytest.raises(SystemExit):
        ess.validate(dataset)


def test_valid_dataset_passes():
    dataset = {"sessions": [{
        "id": "session-1", "title": "A fine session",
        "personality": {"scores": {"Bru": {"chaos": 18}}},
    }]}
    ess.validate(dataset)  # should not raise


# --------------------------------------------------------------------------- #
#  Slim stat-block slice                                                       #
# --------------------------------------------------------------------------- #

def test_build_slim_blocks_shape():
    session = {
        "id": "session-99", "has_transcript": True, "timing_quality": "exact",
        "duration_seconds": 100, "block_count": 2, "word_count": 10,
        "players_present": ["Bru"], "attendance_source": "transcript",
        "speakers": [{"name": "Bru", "canonical": "Bru (Felonias Bru)",
                      "role": "pc", "player": "Justin Hale", "blocks": 2,
                      "words": 10, "talk_seconds_est": 30, "word_share": 1.0}],
        "mentions": {"npcs": {"Astro": 4, "Iro": 3, "Naomi": 2, "Victor": 1},
                     "locations": {}, "pcs": {}},
        "fun": {"nat20_mentions": 1, "nat1_mentions": 0},
        "personality": {
            "scores": {}, "evidence": {},
            "superlatives": {"mvp": {"player": "Bru", "quote": "boom"},
                             "best_joke": {"player": None, "quote": ""},
                             "decision_driver": "Bru"},
        },
    }
    empty = {"id": "interlude-9", "has_transcript": False, "players_present": None}
    slim = ess.build_slim_blocks({"sessions": [session, empty]})

    assert "interlude-9" not in slim["blocks"]
    block = slim["blocks"]["session-99"]
    assert list(block["top_npcs"]) == ["Astro", "Iro", "Naomi"]  # capped at 3
    assert block["speakers"] == [{"name": "Bru", "role": "pc", "word_share": 1.0}]
    # Superlatives keep only entries with a player; decision_driver excluded.
    assert block["superlatives"] == {"mvp": {"player": "Bru", "quote": "boom"}}
