"""Unit tests for the scene-image generator's offline stages.

Run with:  python -m pytest scripts/tests/ -q

The Claude and Gemini calls are not exercised here; everything around them
(name guardrails, shot selection, the band, previews vs publishing, the
recap embed, the spend cap) is, because that is where a bad image would
otherwise reach the site.
"""

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import comic_scene as cs  # noqa: E402


def scene(*shots, chosen=None, quote=None, section="The Missile", characters=()):
    return cs.SceneImage(title="Test", section=section, why="", transcript_evidence=[],
                         characters=list(characters), shots=list(shots) or ["A shot."],
                         chosen=chosen, quote=quote)


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


def test_normalize_applies_name_rules_everywhere():
    s = scene("Brew grins at Ellsworth.", characters=["Brew"],
              quote=cs.Quote(speaker="Brew", text="Ellsworth, duck!"))
    out = cs.normalize_script(s, {"Brew": "Bru", "Ellsworth": "Elspeth"})
    assert out.shots == ["Bru grins at Elspeth."]
    assert out.characters == ["Bru"]
    assert (out.quote.speaker, out.quote.text) == ("Bru", "Elspeth, duck!")


def test_normalize_drops_an_empty_quote_and_refuses_bad_scripts():
    assert cs.normalize_script(scene(quote=cs.Quote(speaker="Bru", text=" ")), {}).quote is None
    with pytest.raises(SystemExit, match="no shots"):
        cs.normalize_script(scene(" "), {})
    with pytest.raises(SystemExit, match="chosen is 3"):
        cs.normalize_script(scene("a", "b", chosen=3), {})


def test_which_shots_get_drawn():
    assert cs.shots_to_draw(scene("a", "b", "c")) == [1, 2, 3]       # compare them all
    assert cs.shots_to_draw(scene("a", "b", "c", chosen=2)) == [2]   # just the pick
    assert cs.shots_to_draw(scene("a")) == [1]                       # a lone shot is the pick
    assert cs.shots_to_draw(scene("a", "b", "c"), only=3) == [3]
    with pytest.raises(SystemExit):
        cs.shots_to_draw(scene("a", "b"), only=5)


def test_unverified_lines_flags_an_invented_quote():
    blocks = [{"text": "Guys, we need"}, {"text": "some luck."}, {"text": "Roll initiative."}]
    real = scene(quote=cs.Quote(speaker="Olivia Cooper", text="Guys, we need some luck."))
    fake = scene(quote=cs.Quote(speaker="Bru", text="Behold my magnificent invention"))
    assert cs.unverified_lines(real, blocks) == []
    assert cs.unverified_lines(fake, blocks) == ['Bru: "Behold my magnificent invention"']


def test_prompt_carries_style_shot_and_composition():
    sheets = cs.load_sheets()
    s = scene("first framing", "second framing", characters=["Silas"])
    prompt = cs.image_prompt(s, sheets, 2)
    assert sheets["style"] in prompt
    assert "Shot: second framing" in prompt and "first framing" not in prompt
    assert cs.COMPOSITION in prompt
    assert "Silas Fairbanks:" in prompt


def test_band_sits_under_full_width_art(tmp_path):
    Image.new("RGB", (1024, 1024), (40, 60, 140)).save(cs.art_path(tmp_path, 1))
    s = scene(quote=cs.Quote(speaker="Olivia Cooper", text="Guys, we need some luck."))
    page = cs.compose(s, cs.load_sheets(), tmp_path, 1, "Session 64 · The Launch")
    assert page.width == cs.PAGE_W and page.height > cs.ART_H
    assert page.getpixel((cs.PAGE_W // 2, cs.ART_H // 2)) == (40, 60, 140)  # art is not covered


def test_embed_goes_under_the_scene_heading_and_refreshes_alt_text():
    url = "/img/comics/session-64-the-missile.webp"
    once, changed = cs.embed_in_recap(RECAP, "The Missile", url, "Comic: [Boom]")
    assert changed
    assert f"### The Missile\n\n![Comic: (Boom)]({url})\n\nA missile hits." in once
    twice, changed_again = cs.embed_in_recap(once, "The Missile", url, "Comic: (Boom)")
    assert not changed_again and twice == once
    redrawn, changed = cs.embed_in_recap(once, "The Missile", url, "New alt")
    assert changed and f"![New alt]({url})" in redrawn and redrawn.count(url) == 1


def test_embed_refuses_unknown_heading():
    with pytest.raises(SystemExit):
        cs.embed_in_recap(RECAP, "Not A Scene", "/img/comics/x.webp", "alt")


def test_alt_text_is_capped_at_a_sentence():
    s = scene("One. " + "Two words here. " * 40)
    assert len(cs.alt_text(s, 1)) <= 320 and cs.alt_text(s, 1).endswith(".")


def test_previews_until_a_shot_is_chosen_then_publishes_it(tmp_path, monkeypatch):
    sessions, data, img = tmp_path / "docs/sessions", tmp_path / "data/comics", tmp_path / "static/img/comics"
    sessions.mkdir(parents=True)
    (sessions / "session-64.md").write_text(RECAP)
    for name, value in (("ROOT", tmp_path), ("SESSIONS_DIR", sessions),
                        ("COMICS_DATA_DIR", data), ("COMICS_IMG_DIR", img)):
        monkeypatch.setattr(cs, name, value)
    comic = data / "session-64-the-launch"
    comic.mkdir(parents=True)
    script = scene("a", "b", section="The Launch").model_dump()
    (comic / "script.json").write_text(json.dumps(script))
    for n in (1, 2):
        Image.new("RGB", (800, 450), (30 * n, 60, 120)).save(cs.art_path(comic, n))

    cs.main(["--comic", "session-64-the-launch", "--letter-only"])
    assert (comic / "preview-1.webp").exists() and (comic / "preview-2.webp").exists()
    assert not img.exists()
    assert "/img/comics/" not in (sessions / "session-64.md").read_text()

    script["chosen"] = 2
    (comic / "script.json").write_text(json.dumps(script))
    cs.main(["--comic", "session-64-the-launch", "--letter-only"])
    assert (img / "session-64-the-launch.webp").exists()
    assert "](/img/comics/session-64-the-launch.webp)" in (sessions / "session-64.md").read_text()


def test_comic_name_maps_to_its_recap():
    assert cs.recap_ref_from_slug("session-64-the-missile") == "session-64"
    assert cs.recap_ref_from_slug("interlude-12-a-quiet-night") == "interlude-12"
    with pytest.raises(SystemExit):
        cs.recap_ref_from_slug("the-missile")


def test_resolve_recap_accepts_number_stem_and_url():
    expected = cs.SESSIONS_DIR / "session-64.md"
    for ref in ("64", "session-64", "https://moonfallsessions.com/sessions/session-64/"):
        assert cs.resolve_recap(ref) == expected


def test_find_character_by_alias_ignores_case():
    sheets = cs.load_sheets()
    assert cs.find_character(sheets, "elspeth")[0] == "Elspeth Cooper"
    assert cs.find_character(sheets, "Nobody")[0] is None


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
        cs.gemini_image(["prompt"], "16:9", attempts=3, size="2K")
    assert len(calls) == 2
    assert calls[0]["config"].image_config.image_size == "2K"
    assert cs.image_requests == 2
