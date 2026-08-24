"""Unit tests for the generated-recap guardrails.

Run with:  python -m pytest scripts/tests/ -q

These pin the rule that the model does not get to author facts it cannot
know. Sessions 57, 58 and 59 each shipped with something invented — a date
copied from another session, a fabricated Spotify URL, a future date, "Brew"
for Bru, a Google Meet handle in a quote attribution — and each needed a
hand-written repair commit afterwards. Every case below is drawn from one of
those.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import recap_postprocess as rp  # noqa: E402


SESSION_59_HEAD = '''---
title: "59: The Hairy Monkey Gambit"
date: 2026-08-28
description: "Disguised as fast food royalty."
summary: "The party dons disguises."
podcastlink: "https://creators.spotify.com/pod/show/topher-hooper/episodes/C4-E59-The-Hairy-Monkey-Gambit"
---

***August 28, 2026***

## Players Present
- **Taylor Ramsey** as Silas Fairbanks

## Plot Events

### The Toothy's Morning Briefing
'''


def _recap(head=SESSION_59_HEAD, body="Narrative filler. " * 40):
    return head + "\n" + body + "\n"


KB = """# Campaign Knowledge Base

## Character Roster

### Player Characters (Active)
| Character | Player | Google Meet Name | Transcript Aliases | File | Notes |
|-----------|--------|------------------|--------------------|------|-------|
| Silas Fairbanks | Taylor Ramsey | Tyram | "Silus", "Cyrus" | silas.md | Rogue |
| Bru (Felonias Bru) | Justin Hale | Justin Hale | "Brew", "Bruce" | bru.md | Artificer |

### NPCs (Recurring)
| NPC | Role | File | Transcript Aliases |
|-----|------|------|--------------------|
| Iro | Workshop keeper | iro.md | "Ero" |
| Scarlet | Keeper of the capsule | — | |
| Ben Boulage | Private detective | — | "Bin Bullage", "Ben Bulage" |

## Locations
| Location | Correct Spelling | Transcript Aliases | Notes |
|----------|-----------------|-------------------|-------|
| High Forge | High Forge | "Highforge" | Primary city |

## Known Transcription Errors

| Transcript Says | Should Be | Context |
|----------------|-----------|---------|
| Brew | Bru | Character name |
| Scarlet | Scarlet | NPC — not a transcription error. |
| Bon Bonner / Pon Poty | Bon Bonnery | NPC actor |
| Tyram | Taylor Ramsey | Google Meet name |

## Active Plot Threads
- Nothing here should be parsed.
"""


@pytest.fixture
def kb_path(tmp_path):
    path = tmp_path / "campaign-kb.md"
    path.write_text(KB, encoding="utf-8")
    return path


@pytest.fixture
def docs_dir(tmp_path):
    docs = tmp_path / "docs"
    (docs / "player-characters").mkdir(parents=True)
    (docs / "player-characters" / "bru.md").write_text("# Bru\n", encoding="utf-8")
    (docs / "npcs").mkdir()
    return docs


# --------------------------------------------------------------------------- #
#  Frontmatter helpers                                                         #
# --------------------------------------------------------------------------- #

def test_get_frontmatter_value_strips_quotes():
    assert rp.get_frontmatter_value(_recap(), "title") == "59: The Hairy Monkey Gambit"
    assert rp.get_frontmatter_value(_recap(), "date") == "2026-08-28"


def test_get_frontmatter_value_missing_key_and_missing_block():
    assert rp.get_frontmatter_value(_recap(), "author") is None
    assert rp.get_frontmatter_value("no frontmatter here", "date") is None


def test_set_frontmatter_value_appends_when_absent():
    frontmatter = 'title: "x"\n'
    assert rp.set_frontmatter_value(frontmatter, "podcastlink", '""') == 'title: "x"\npodcastlink: ""\n'


def test_display_date_has_no_leading_zero():
    assert rp.display_date("2026-08-04") == "August 4, 2026"


# --------------------------------------------------------------------------- #
#  Date stamping — session 58 dated itself 2026-06-26, session 59 2026-08-28   #
# --------------------------------------------------------------------------- #

def test_stamp_session_date_overrides_both_places():
    fixed, notes = rp.stamp_session_date(_recap(), "2026-08-14")
    assert rp.get_frontmatter_value(fixed, "date") == "2026-08-14"
    assert "***August 14, 2026***" in fixed
    assert "***August 28, 2026***" not in fixed
    assert len(notes) == 2


def test_stamp_session_date_is_quiet_when_already_correct():
    fixed, notes = rp.stamp_session_date(_recap(), "2026-08-14")
    _, notes_again = rp.stamp_session_date(fixed, "2026-08-14")
    assert notes_again == []


def test_stamp_session_date_inserts_a_missing_header():
    head = SESSION_59_HEAD.replace("***August 28, 2026***\n", "")
    fixed, notes = rp.stamp_session_date(_recap(head), "2026-08-14")
    assert "***August 14, 2026***" in fixed
    assert any("inserted" in n for n in notes)


def test_stamp_session_date_keeps_the_blank_line_after_the_header():
    """The byline is inserted after this line; eating the blank line below it
    would run the byline straight into the next heading."""
    fixed, _ = rp.stamp_session_date(_recap(), "2026-08-14")
    assert "***August 14, 2026***\n\n## Players Present" in fixed


def test_stamp_session_date_without_frontmatter_is_a_noop():
    fixed, notes = rp.stamp_session_date("just prose", "2026-08-14")
    assert fixed == "just prose" and notes == []


# --------------------------------------------------------------------------- #
#  Podcast link — the campaign stopped publishing one                          #
# --------------------------------------------------------------------------- #

def test_apply_podcast_link_removes_the_key_from_a_new_recap():
    """The model still writes one: every style-reference session has the key."""
    fixed, notes = rp.apply_podcast_link(_recap(), "")
    assert rp.get_frontmatter_value(fixed, "podcastlink") is None
    assert "podcastlink" not in fixed
    assert notes and "no longer publishes a podcast" in notes[0]


def test_apply_podcast_link_leaves_the_rest_of_the_frontmatter_intact():
    fixed, _ = rp.apply_podcast_link(_recap(), "")
    for key in ("title", "date", "description", "summary"):
        assert rp.get_frontmatter_value(fixed, key) is not None


def test_apply_podcast_link_keeps_a_real_link_on_an_older_recap():
    """Regenerating a pre-podcast-shutdown session must not destroy its URL."""
    real = "https://creators.spotify.com/pod/show/topher-hooper/episodes/real-e123"
    fixed, _ = rp.apply_podcast_link(_recap(), real)
    assert rp.get_frontmatter_value(fixed, "podcastlink") == real


def test_apply_podcast_link_is_quiet_when_there_is_nothing_to_remove():
    head = SESSION_59_HEAD.replace(
        'podcastlink: "https://creators.spotify.com/pod/show/topher-hooper/'
        'episodes/C4-E59-The-Hairy-Monkey-Gambit"\n', "")
    fixed, notes = rp.apply_podcast_link(_recap(head), "")
    assert notes == []
    assert "podcastlink" not in fixed


def test_remove_frontmatter_value_is_a_noop_when_absent():
    assert rp.remove_frontmatter_value('title: "x"\n', "podcastlink") == 'title: "x"\n'


# --------------------------------------------------------------------------- #
#  Name corrections, learned from the knowledge base                           #
# --------------------------------------------------------------------------- #

def test_load_name_corrections_reads_every_table(kb_path):
    corrections = rp.load_name_corrections(kb_path)
    assert corrections["Brew"] == "Bru"          # curated error table
    assert corrections["Silus"] == "Silas"       # roster alias, first name only
    assert corrections["Ero"] == "Iro"           # NPC alias
    assert corrections["Highforge"] == "High Forge"  # location alias
    assert corrections["Tyram"] == "Taylor Ramsey"


def test_load_name_corrections_splits_slash_separated_variants(kb_path):
    corrections = rp.load_name_corrections(kb_path)
    assert corrections["Bon Bonner"] == "Bon Bonnery"
    assert corrections["Pon Poty"] == "Bon Bonnery"


def test_load_name_corrections_skips_header_rows(kb_path):
    corrections = rp.load_name_corrections(kb_path)
    assert "Transcript Aliases" not in corrections
    assert "Transcript Says" not in corrections


def test_load_name_corrections_never_renames_a_real_character(kb_path):
    """The KB's `Scarlet | Scarlet` row marks a real NPC, not an error."""
    assert "Scarlet" not in rp.load_name_corrections(kb_path)


def test_load_name_corrections_survives_a_missing_kb(tmp_path):
    assert rp.load_name_corrections(tmp_path / "nope.md") == {}


def test_apply_name_corrections_is_word_bounded_and_case_sensitive(kb_path):
    corrections = rp.load_name_corrections(kb_path)
    text = "Brew grinned. Brewery stock rose. See /player-characters/bru for more."
    fixed, notes = rp.apply_name_corrections(text, corrections)
    assert fixed == "Bru grinned. Brewery stock rose. See /player-characters/bru for more."
    assert notes == ['"Brew" -> "Bru" (1x)']


def test_apply_name_corrections_prefers_the_longest_alias(kb_path):
    fixed, _ = rp.apply_name_corrections("Bin Bullage tipped his hat.",
                                         rp.load_name_corrections(kb_path))
    assert fixed == "Ben Boulage tipped his hat."


def test_apply_name_corrections_reports_nothing_on_clean_text(kb_path):
    _, notes = rp.apply_name_corrections("Bru and Silas walked to High Forge.",
                                         rp.load_name_corrections(kb_path))
    assert notes == []


# --------------------------------------------------------------------------- #
#  Internal links — /npcs/scarlet/ once failed the whole deploy                #
# --------------------------------------------------------------------------- #

def test_repair_internal_links_unwraps_a_dead_link(docs_dir):
    fixed, notes = rp.repair_internal_links("[Scarlet](/npcs/scarlet/) waited.", docs_dir)
    assert fixed == "Scarlet waited."
    assert notes and "/npcs/scarlet" in notes[0]


def test_repair_internal_links_keeps_a_live_link(docs_dir):
    text = "[Bru](/player-characters/bru) grinned."
    fixed, notes = rp.repair_internal_links(text, docs_dir)
    assert fixed == text and notes == []


def test_repair_internal_links_leaves_external_urls_alone(docs_dir):
    text = "[the show](https://example.com/episode)"
    assert rp.repair_internal_links(text, docs_dir)[0] == text


# --------------------------------------------------------------------------- #
#  Validation                                                                  #
# --------------------------------------------------------------------------- #

def test_validate_recap_accepts_a_well_formed_session():
    assert rp.validate_recap(_recap(), expected_date="2026-08-28") == []


def test_validate_recap_flags_a_date_that_lost_its_transcript():
    problems = rp.validate_recap(_recap(), expected_date="2026-08-14")
    assert any("does not match the transcript date" in p for p in problems)


def test_validate_recap_flags_missing_frontmatter():
    problems = rp.validate_recap("## Plot Events\n" + "x" * 600)
    assert problems == ["no YAML frontmatter block at the top of the file"]


def test_validate_recap_flags_missing_keys():
    head = SESSION_59_HEAD.replace('summary: "The party dons disguises."\n', "")
    problems = rp.validate_recap(_recap(head))
    assert any("missing `summary`" in p for p in problems)


def test_validate_recap_does_not_require_a_podcast_link():
    head = SESSION_59_HEAD.replace(
        'podcastlink: "https://creators.spotify.com/pod/show/topher-hooper/'
        'episodes/C4-E59-The-Hairy-Monkey-Gambit"\n', "")
    assert rp.validate_recap(_recap(head)) == []


def test_validate_recap_flags_unfilled_template_placeholders():
    head = SESSION_59_HEAD.replace('"59: The Hairy Monkey Gambit"',
                                   '"59: [Title To Be Generated]"')
    problems = rp.validate_recap(_recap(head))
    assert any("placeholder" in p for p in problems)


def test_validate_recap_flags_a_missing_players_present_section():
    head = SESSION_59_HEAD.replace("## Players Present", "## Setting")
    problems = rp.validate_recap(_recap(head))
    assert any("Players Present" in p for p in problems)


def test_validate_recap_accepts_alternative_attendance_headings():
    head = SESSION_59_HEAD.replace("## Players Present", "## Party Members Present")
    assert rp.validate_recap(_recap(head)) == []


def test_validate_recap_flags_a_truncated_body():
    problems = rp.validate_recap(_recap(body="short"))
    assert any("truncated" in p for p in problems)


def test_validate_recap_exempts_interludes_from_the_section_rules():
    """None of the sixteen published interludes uses the session format."""
    head = SESSION_59_HEAD.replace("## Players Present", "## Session Overview")
    head = head.replace("## Plot Events", "## The Oracle's Quest")
    assert rp.validate_recap(_recap(head), is_interlude=True) == []
    assert rp.validate_recap(_recap(head), is_interlude=False) != []


# --------------------------------------------------------------------------- #
#  End to end                                                                  #
# --------------------------------------------------------------------------- #

def test_postprocess_recap_repairs_the_session_59_failures(kb_path, docs_dir):
    raw = _recap(body='> "Fine," said Brew, credited to Tyram. ' * 20
                      + "[Scarlet](/npcs/scarlet/) watched. ")
    fixed, notes, problems = rp.postprocess_recap(
        raw, transcript_date="2026-08-14", podcast_link="",
        kb_path=kb_path, docs_dir=docs_dir)

    assert problems == []
    assert rp.get_frontmatter_value(fixed, "date") == "2026-08-14"
    assert "podcastlink" not in fixed
    assert "***August 14, 2026***" in fixed
    assert "Brew" not in fixed and "Tyram" not in fixed
    assert "](/npcs/scarlet" not in fixed and "Scarlet watched." in fixed
    assert len(notes) == 6


def test_postprocess_recap_is_idempotent(kb_path, docs_dir):
    args = dict(transcript_date="2026-08-14", podcast_link="",
                kb_path=kb_path, docs_dir=docs_dir)
    once, _, _ = rp.postprocess_recap(_recap(), **args)
    twice, notes, problems = rp.postprocess_recap(once, **args)
    assert twice == once and notes == [] and problems == []


def test_repair_internal_links_leaves_images_alone(docs_dir):
    text = "![a map](/img/map.webp)"
    assert rp.repair_internal_links(text, docs_dir)[0] == text


def test_repair_internal_links_leaves_non_docs_pages_alone(docs_dir):
    """/stats is a React page under src/pages, not a doc."""
    text = "[the dashboard](/stats)"
    assert rp.repair_internal_links(text, docs_dir)[0] == text
