"""Unit tests for the session generator's "nothing to do" path.

Run with:  python -m pytest scripts/tests/ -q

The generator deletes each .srt once it has been processed, so an empty (or
absent) transcripts_raw/ is the normal resting state between sessions. These
tests pin the rule that this state is a no-op that exits 0 rather than a
failure — a re-run in that state used to abort the whole workflow before it
could build and deploy.
"""

import sys
from pathlib import Path

import pytest

# The generator imports the anthropic SDK at module scope and exits if it is
# missing; skip cleanly rather than blowing up collection when it is absent.
pytest.importorskip("anthropic")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import automate_session as auto  # noqa: E402


@pytest.fixture
def automation(tmp_path, monkeypatch):
    """A SessionAutomation rooted at an empty temp project."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    return auto.SessionAutomation(tmp_path)


# --------------------------------------------------------------------------- #
#  find_latest_srt                                                             #
# --------------------------------------------------------------------------- #

def test_find_latest_srt_missing_directory(automation):
    assert not automation.raw_dir.exists()
    assert automation.find_latest_srt() is None


def test_find_latest_srt_empty_directory(automation):
    automation.raw_dir.mkdir()
    assert automation.find_latest_srt() is None


def test_find_latest_srt_returns_newest(automation):
    automation.raw_dir.mkdir()
    older = automation.raw_dir / "DnD_2026-07-17.srt"
    newer = automation.raw_dir / "DnD_2026-07-24.srt"
    older.write_text("1\n", encoding="utf-8")
    newer.write_text("1\n", encoding="utf-8")
    import os
    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))
    assert automation.find_latest_srt() == newer


# --------------------------------------------------------------------------- #
#  run_automation with no transcript waiting                                   #
# --------------------------------------------------------------------------- #

def test_run_automation_with_no_srt_is_a_no_op(automation, monkeypatch):
    """No SRT waiting must not look like a failure, and must not call the API."""
    def fail(*args, **kwargs):
        raise AssertionError("generation must not run without a transcript")

    monkeypatch.setattr(automation, "generate_recap", fail)
    monkeypatch.setattr(automation, "run_transcript_cleaner", fail)

    assert automation.run_automation() == auto.NOTHING_TO_DO


def test_nothing_to_do_is_distinct_from_failure():
    assert auto.NOTHING_TO_DO is not False
    assert auto.NOTHING_TO_DO != False  # noqa: E712 — the sentinel must not compare equal to a failure


# --------------------------------------------------------------------------- #
#  Exit codes                                                                  #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("result,expected_code", [
    (auto.NOTHING_TO_DO, 0),
    (True, 0),
    (False, 1),
])
def test_main_exit_code(monkeypatch, result, expected_code):
    class StubAutomation:
        def __init__(self, *args, **kwargs):
            pass

        def run_automation(self, **kwargs):
            return result

    monkeypatch.setattr(auto, "SessionAutomation", StubAutomation)
    monkeypatch.setattr(sys, "argv", ["automate_session.py"])

    with pytest.raises(SystemExit) as excinfo:
        auto.main()
    assert excinfo.value.code == expected_code


# --------------------------------------------------------------------------- #
#  Generation guardrails                                                       #
# --------------------------------------------------------------------------- #

GOOD_RECAP = '''---
title: "59: The Hairy Monkey Gambit"
date: 2026-08-28
description: "A description."
summary: "A summary."
podcastlink: "https://creators.spotify.com/pod/show/topher-hooper/episodes/invented"
---

***August 28, 2026***

## Players Present
- **Taylor Ramsey** as Silas Fairbanks

## Plot Events

### Into the Furnace Factory
''' + "Narrative filler. " * 40


def test_date_from_transcript_uses_the_filename(automation):
    assert automation.date_from_transcript(Path("docs/transcripts/2026-08-14.md")) == "2026-08-14"


def test_date_from_transcript_falls_back_to_today(automation):
    import datetime
    assert (automation.date_from_transcript(Path("docs/transcripts/notes.md"))
            == datetime.datetime.now().strftime("%Y-%m-%d"))


def test_read_existing_podcast_link_when_there_is_no_page(automation):
    assert automation.read_existing_podcast_link("session-99.md") == ""


def test_read_existing_podcast_link_round_trips_through_the_template(automation):
    """Regenerating an older recap must not destroy the episode URL it carries."""
    automation.sessions_dir.mkdir(parents=True)
    (automation.sessions_dir / "session-59.md").write_text(
        '---\ntitle: "59: x"\npodcastlink: "https://example.com/e59"\n---\n', encoding="utf-8")

    link = automation.read_existing_podcast_link("session-59.md")
    assert link == "https://example.com/e59"

    _, template = automation.create_session_template(59, False, "2026-08-14", podcast_link=link)
    assert 'podcastlink: "https://example.com/e59"' in template


def test_guardrails_repair_the_date_and_strip_the_podcast_link(automation):
    (automation.project_root / "data").mkdir()
    (automation.project_root / "data" / "campaign-kb.md").write_text("# empty\n", encoding="utf-8")

    fixed, problems = automation._apply_generation_guardrails(GOOD_RECAP, "2026-08-14", "")

    assert problems == []
    assert "date: 2026-08-14" in fixed
    assert "***August 14, 2026***" in fixed
    assert "podcastlink" not in fixed


def test_new_session_template_has_no_podcast_link(automation):
    _, template = automation.create_session_template(60, False, "2026-08-21")
    assert "podcastlink" not in template


def test_guardrails_reject_a_recap_with_no_players_present(automation):
    _, problems = automation._apply_generation_guardrails(
        GOOD_RECAP.replace("## Players Present", "## Setting"), "2026-08-14", "")
    assert any("Players Present" in p for p in problems)


def test_guardrails_exempt_interludes_from_the_section_rules(automation):
    _, problems = automation._apply_generation_guardrails(
        GOOD_RECAP.replace("## Players Present", "## Session Overview")
                  .replace("## Plot Events", "## The Oracle's Quest"),
        "2026-08-14", "", is_interlude=True)
    assert problems == []
