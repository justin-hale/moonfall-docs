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
