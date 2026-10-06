"""Unit tests for the comic page generator's offline stages.

Run with:  python -m pytest scripts/tests/ -q

The Claude and Gemini calls are not exercised here; everything after them
(name guardrails, layout, lettering, the recap embed) is, because that is
where a bad page would otherwise reach the site.
"""

import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import comic_scene as cs  # noqa: E402


def panel(size="wide", dialogue=(), caption="", sfx="", characters=()):
    return cs.Panel(size=size, characters=list(characters), visual="A scene.", caption=caption,
                    dialogue=list(dialogue), sfx=sfx)


def line(speaker, text, position="left"):
    return cs.Line(speaker=speaker, text=text, position=position)


def script(*panels, section="The Missile"):
    return cs.ComicScript(title="Test", section=section, why="", transcript_evidence=[],
                          panels=list(panels))


RECAP = """---
title: "64: Two Angels and a Falling Car"
date: 2026-10-02
---

## Plot Events
### The Launch
The car flies.

### The Missile
A missile hits.
"""


def test_lone_half_panels_become_wide():
    panels = cs.pair_halves([panel("half"), panel("wide"), panel("half"), panel("half"), panel("half")])
    assert [p.size for p in panels] == ["wide", "wide", "half", "half", "wide"]


def test_normalize_applies_name_rules_everywhere():
    s = script(panel(caption="Brew grins.", dialogue=[line("Brew", "Ellsworth, duck!")],
                     characters=["Brew"]), panel(), panel())
    out = cs.normalize_script(s, {"Brew": "Bru", "Ellsworth": "Elspeth"})
    p = out.panels[0]
    assert p.caption == "Bru grins."
    assert p.characters == ["Bru"]
    assert (p.dialogue[0].speaker, p.dialogue[0].text) == ("Bru", "Elspeth, duck!")


def test_normalize_caps_panels_and_balloons():
    crowded = panel(dialogue=[line("Bru", "a"), line("Bru", "b"), line("Bru", "c")])
    out = cs.normalize_script(script(*[crowded] * 8), {})
    assert len(out.panels) == cs.MAX_PANELS
    assert all(len(p.dialogue) == 2 for p in out.panels)


def test_unverified_lines_flags_invented_dialogue():
    blocks = [{"text": "If you believed in Luna,"}, {"text": "you'd go to heaven."},
              {"text": "Roll initiative."}]
    s = script(panel(dialogue=[line("Silas Fairbanks", "If you believed in Luna you'd go to heaven"),
                               line("Bru", "Behold my magnificent invention")]))
    assert cs.unverified_lines(s, blocks) == ['Bru: "Behold my magnificent invention"']


def test_embed_goes_under_the_scene_heading_and_is_idempotent():
    url = "/img/comics/session-64-the-missile.webp"
    once, changed = cs.embed_in_recap(RECAP, "The Missile", url, "Comic: [Boom]")
    assert changed
    assert f"### The Missile\n\n![Comic: (Boom)]({url})\n\nA missile hits." in once
    twice, changed_again = cs.embed_in_recap(once, "The Missile", url, "Comic: Boom")
    assert not changed_again and twice == once


def test_embed_refuses_unknown_heading():
    with pytest.raises(SystemExit):
        cs.embed_in_recap(RECAP, "Not A Scene", "/img/comics/x.webp", "alt")


def test_resolve_recap_accepts_number_stem_and_url():
    expected = cs.SESSIONS_DIR / "session-64.md"
    for ref in ("64", "session-64", "https://moonfallsessions.com/sessions/session-64/"):
        assert cs.resolve_recap(ref) == expected


def test_find_character_by_alias_ignores_case():
    sheets = cs.load_sheets()
    assert cs.find_character(sheets, "elspeth")[0] == "Elspeth Cooper"
    assert cs.find_character(sheets, "Nobody")[0] is None


def test_letter_page_renders_every_panel(tmp_path):
    s = script(panel("wide", caption="Over the farmland.", sfx="KRA-KOOM!"),
               panel("half", dialogue=[line("Silas Fairbanks", "Hey guys.")]),
               panel("half", dialogue=[line("Angel", "I'll kill you again.", "right")]))
    for n in range(1, 4):
        Image.new("RGB", (640, 480), (30 * n, 60, 120)).save(tmp_path / f"panel-{n}.webp")
    page = cs.letter_page(s, cs.load_sheets(), tmp_path, "Session 64")
    boxes, height = cs.layout(s.panels)
    assert page.size == (cs.PAGE_W, height)
    assert len(boxes) == 3
    assert boxes[1][1] == boxes[2][1]  # the halves share a row


def test_budget_refuses_an_oversized_run_up_front(monkeypatch):
    monkeypatch.setattr(cs, "MAX_IMAGE_REQUESTS", 4)
    cs.check_image_budget(4)
    with pytest.raises(SystemExit, match="COMIC_MAX_IMAGES"):
        cs.check_image_budget(5)


def test_budget_counts_retries_and_stops_at_the_cap(monkeypatch):
    from types import SimpleNamespace

    from google import genai

    calls = []

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(candidates=[], prompt_feedback="blocked")

    monkeypatch.setattr(genai, "Client", lambda: SimpleNamespace(models=FakeModels()))
    monkeypatch.setattr(cs, "MAX_IMAGE_REQUESTS", 2)
    monkeypatch.setattr(cs, "image_requests", 0)
    with pytest.raises(SystemExit, match="Stopped at COMIC_MAX_IMAGES=2"):
        cs.gemini_image(["prompt"], "16:9", attempts=3)
    assert len(calls) == 2
    assert cs.image_requests == 2
