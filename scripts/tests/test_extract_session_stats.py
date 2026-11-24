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


def test_players_present_excludes_non_roster_npcs(kb, roster):
    """NPCs listed alongside the party (session-4's Philbin) must not count."""
    alias_to_canonical, _ = kb
    text = (
        "## Party Members Present\n"
        "- **[Silas](/player-characters/silas)**\n"
        "- **Philbin** (gnome NPC, captured and interrogated)\n"
    )
    players = ess.parse_players_present(text, alias_to_canonical, roster)
    assert players == ["Silas"]


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


# --------------------------------------------------------------------------- #
#  Side arcs: a guest DM and different characters                              #
# --------------------------------------------------------------------------- #
#
# Session 69 opened the H.I.D.E. arc: Taylor ran the game and Topher, Justin
# and Luke played Tex, Shade and Ward. The roster maps each Meet name to one
# character and assumes Topher is DM, so the stats credited Silas, Bru and
# Leliana and marked Topher as DM.

ARC = {
    "id": "hide",
    "name": "H.I.D.E.",
    "dm": {"name": "Taylor", "player": "Taylor Ramsey", "meet_names": ["Tyram"]},
    "cast": [
        {"character": "Tex", "player": "Topher", "meet_names": ["Christopher Hooper"]},
        {"character": "Shade", "player": "Justin Hale", "meet_names": ["Justin Hale"]},
        {"character": "Ward", "player": "Luke Neverisky", "meet_names": ["Luke Neverisky"]},
    ],
}

ARC_RECAP = """\
## Players Present
- Christopher "Topher" Hooper as Tex
- Justin Hale as [Shade](/player-characters/shade)
- **Luke Neverisky** as **Ward**

*Taylor Ramsey served as Dungeon Master.*

## Plot Events
Silas was mentioned as Tex walked in.
"""

MAIN_RECAP = """\
## Players Present
- **Taylor Ramsey** as **Silas Fairbanks** — Rogue
- **Justin Hale** as **Bru** — Artificer

## Plot Events
The party met a courier who introduced himself as Tex. Ward off the cold.
"""


def test_side_arc_detected_from_players_present():
    assert ess.detect_side_arc(ARC_RECAP, [ARC]) is ARC


def test_side_arc_not_detected_in_main_campaign_recap():
    # "as Tex" and "Ward" appear in the prose, not under Players Present.
    assert ess.detect_side_arc(MAIN_RECAP, [ARC]) is None
    assert ess.detect_side_arc("no attendance section at all", [ARC]) is None


def test_side_arc_recredits_speakers(tmp_path, kb, roster):
    alias_to_canonical, replacements = kb
    path = tmp_path / "2026-11-20.md"
    path.write_text(MD_TRANSCRIPT, encoding="utf-8")
    blocks, _, quality = ess.parse_md_transcript(
        path, "2026-11-20", alias_to_canonical, replacements)

    moved = ess.apply_side_arc(blocks, ARC)
    speakers, _, _ = ess.summarize_speakers(
        blocks, {**roster, **ess.side_arc_roster(ARC)}, quality)

    by_name = {s["name"]: s for s in speakers}
    assert set(by_name) == {"Taylor", "Tex", "Shade", "Ward"}
    assert by_name["Taylor"]["role"] == "dm"
    assert by_name["Tex"]["role"] == "pc" and by_name["Tex"]["player"] == "Topher"
    assert moved["Silas Fairbanks"] == "Taylor Ramsey"
    assert moved["Topher"] == "Tex"


def test_side_arc_mentions_are_case_sensitive():
    patterns = ess.side_arc_pc_patterns(ARC)
    counts = ess.count_mentions("Ward took the ward; Shade stood in the shade.", patterns)
    assert counts == {"Shade": 1, "Ward": 1}


def test_slim_blocks_relabel_superlatives_in_a_side_arc():
    dataset = {"sessions": [{
        "id": "session-69", "has_transcript": True, "players_present": ["Tex"],
        "timing_quality": "exact", "duration_seconds": 60, "word_count": 10,
        "attendance_source": "transcript",
        "speakers": [{"name": "Tex", "role": "pc", "word_share": 1.0}],
        "mentions": {"npcs": {}}, "fun": {"nat20_mentions": 0, "nat1_mentions": 0},
        "personality": {"superlatives": {"mvp": {"player": "Topher", "quote": "q"}}},
        "side_arc": {"id": "hide", "name": "H.I.D.E.", "labels": {"Topher": "Tex"}},
    }]}
    block = ess.build_slim_blocks(dataset)["blocks"]["session-69"]
    assert block["superlatives"]["mvp"] == {"player": "Tex", "quote": "q"}


# A guest DM whose cast includes a regular character (Scarlet) can't be
# picked out by attendance, so the arc lists its recaps.
LISTED_ARC = {
    "id": "toyota-works",
    "name": "Toyota Works",
    "sessions": ["session-67", "session-68"],
    "dm": {"name": "Justin", "player": "Justin Hale", "meet_names": ["Justin Hale"]},
    "cast": [{"character": "Scarlet", "player": "Topher", "meet_names": ["Christopher Hooper"]}],
}

SCARLET_RECAP = """\
## Players Present
- Taylor Ramsey as [Silas Fairbanks](/player-characters/silas)
- Christopher "Topher" Hooper as [Scarlet](/npcs/scarlet)

## Plot Events
"""


def test_listed_arc_applies_only_to_its_sessions():
    arcs = [ARC, LISTED_ARC]
    assert ess.detect_side_arc(MAIN_RECAP, arcs, "session-67") is LISTED_ARC
    # Scarlet under Players Present in another recap is not this arc.
    assert ess.detect_side_arc(SCARLET_RECAP, arcs, "session-44") is None
    assert ess.detect_side_arc(SCARLET_RECAP, arcs, "interlude-67") is None
    # Attendance-detected arcs still work alongside it.
    assert ess.detect_side_arc(ARC_RECAP, arcs, "session-70") is ARC


def test_listed_arc_recredits_only_the_seats_that_changed(tmp_path, kb, roster):
    alias_to_canonical, replacements = kb
    path = tmp_path / "2026-11-06.md"
    path.write_text(MD_TRANSCRIPT, encoding="utf-8")
    blocks, _, quality = ess.parse_md_transcript(
        path, "2026-11-06", alias_to_canonical, replacements)

    moved = ess.apply_side_arc(blocks, LISTED_ARC)
    speakers, _, _ = ess.summarize_speakers(
        blocks, {**roster, **ess.side_arc_roster(LISTED_ARC)}, quality)

    by_name = {s["name"]: s for s in speakers}
    assert by_name["Justin"]["role"] == "dm"
    assert by_name["Scarlet"]["role"] == "pc" and by_name["Scarlet"]["player"] == "Topher"
    assert "Topher" not in by_name and "Bru" not in by_name
    assert by_name["Silas"]["role"] == "pc"
    assert moved == {"Bru (Felonias Bru)": "Justin Hale", "Topher": "Scarlet"}
