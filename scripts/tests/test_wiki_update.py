"""Tests for the wiki step: which pages a recap touches, and how their
Session History is written.

Run with:  python -m pytest scripts/tests/ -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wiki_update as wu  # noqa: E402


def _page(title, body="# Title\n\nSome text.\n", aliases=None):
    extra = f"aliases: {aliases}\n" if aliases else ""
    return f"---\ntitle: {title}\ndescription: x\nsidebar_position: 1\n{extra}---\n\n{body}"


def _docs(tmp_path):
    (tmp_path / "npcs").mkdir()
    (tmp_path / "locations").mkdir()
    (tmp_path / "organizations").mkdir()
    (tmp_path / "npcs" / "lady-viper.md").write_text(
        _page("Lady Viper", aliases='["Viper", "Elizandra Legrand"]'), encoding="utf-8")
    (tmp_path / "npcs" / "iro.md").write_text(_page("Iro"), encoding="utf-8")
    (tmp_path / "locations" / "greyport.md").write_text(_page("Greyport"), encoding="utf-8")
    (tmp_path / "organizations" / "resistance.md").write_text(_page("Resistance"), encoding="utf-8")
    return tmp_path


RECAP = """---
title: "64: Test"
summary: "Iro in the summary only."
---

***October 2, 2026***

## Plot Events
### Scene
Viper met the party in [Greyport](/locations/greyport). They joined the resistance.

> *An editorial note mentioning Iro. — V.*
"""


def test_loads_titles_and_aliases(tmp_path):
    entities = {e.key: e for e in wu.load_wiki_entities(_docs(tmp_path))}
    assert entities["npcs/lady-viper"].terms == ["Lady Viper", "Viper", "Elizandra Legrand"]
    assert entities["locations/greyport"].url == "/locations/greyport"


def test_matches_alias_and_link_but_not_frontmatter_notes_or_lowercase(tmp_path):
    entities = wu.load_wiki_entities(_docs(tmp_path))
    keys = {e.key for e in wu.find_mentioned_entities(RECAP, entities)}
    # Alias "Viper" and the Greyport link count; Iro appears only in the
    # frontmatter and an editorial note; "resistance" is lowercase prose.
    assert keys == {"npcs/lady-viper", "locations/greyport"}


def test_parse_response_tolerates_fences_and_junk():
    text = 'Here:\n```json\n{"updates": {"npcs/iro": "Iro fixed the ship."}, "new_entities": [{"name": "Toothy", "type": "npc"}, 3]}\n```'
    parsed = wu.parse_response(text)
    assert parsed["updates"] == {"npcs/iro": "Iro fixed the ship."}
    assert parsed["new_entities"] == [{"name": "Toothy", "type": "npc"}]
    assert wu.parse_response("no json at all") == {"updates": {}, "new_entities": []}


def test_clean_entry_strips_mdx_hazards():
    assert wu.clean_entry('  "Iro built a <thing> {fast}."  ') == "Iro built a thing fast."
    assert wu.clean_entry(None) == ""


def test_upsert_creates_section_then_appends_then_replaces():
    page = _page("Iro")
    page = wu.upsert_session_entry(page, 63, "First.")
    assert page.rstrip().endswith("- **[Session 63](/sessions/session-63)** — First.")
    assert page.count(wu.HISTORY_HEADING) == 1

    page = wu.upsert_session_entry(page, 64, "Second.")
    page = wu.upsert_session_entry(page, 63, "Rewritten.")
    history = page.split(wu.HISTORY_HEADING, 1)[1]
    assert history.count("Session 63") == 1
    assert "Rewritten." in history and "First." not in history
    assert history.index("Session 63") < history.index("Session 64")


def test_upsert_stays_inside_its_section():
    page = _page("Iro", body="# Iro\n\n## Session History\n\n- **[Session 1](/sessions/session-1)** — A.\n\n## Related\n\n- x\n")
    page = wu.upsert_session_entry(page, 2, "B.", )
    history, related = page.split("## Related", 1)
    assert "Session 2" in history and "Session 2" not in related


def test_interlude_label():
    page = wu.upsert_session_entry(_page("Iro"), 16, "Side story.", is_interlude=True)
    assert "- **[Interlude 16](/sessions/interlude-16)** — Side story." in page


def test_apply_updates_skips_unknown_and_null(tmp_path):
    entities = wu.load_wiki_entities(_docs(tmp_path))
    written = wu.apply_updates(entities, {"npcs/iro": "Iro repaired the van.",
                                          "npcs/lady-viper": None,
                                          "npcs/nobody": "Ghost."}, 64)
    assert written == ["npcs/iro"]
    assert "Iro repaired the van." in (tmp_path / "npcs" / "iro.md").read_text()
    assert wu.HISTORY_HEADING not in (tmp_path / "npcs" / "lady-viper.md").read_text()
