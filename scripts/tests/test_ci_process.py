"""Unit tests for the episode-intake helpers.

Run with:  python -m pytest scripts/tests/ -q

These pin the rule that the intake stays re-runnable once a release exists.
Process Episode run 47 (2026-08-25) got all the way through detect, download,
extract and release and then died:

    File "scripts/ci_process.py", line 675, in cmd_update_feed
        audio_url = meta["audio_url"]
    KeyError: 'audio_url'

`detect` had found an existing release for the session date and set
RELEASE_EXISTS, so the workflow skipped the release step entirely and nothing
ever wrote audio_url. open-pr never ran, and the "Add SRT for Episode 60" PR
had to be created by hand.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ci_process as ci  # noqa: E402


def test_release_audio_url_shape():
    assert ci.release_audio_url(60, "moonfall-2026-08-21.mp3") == (
        "https://github.com/topherhooper/omelas-stories"
        "/releases/download/v60/moonfall-2026-08-21.mp3")


def test_resolve_audio_url_prefers_what_the_release_step_recorded():
    meta = {"audio_url": "https://example.com/actual.mp3",
            "mp3_path": "workspace/moonfall-2026-08-21.mp3"}
    assert ci.resolve_audio_url(meta, 60) == "https://example.com/actual.mp3"


def test_resolve_audio_url_derives_when_the_release_step_was_skipped():
    """The RELEASE_EXISTS path: cmd_release never runs, so nothing records it."""
    meta = {"mp3_path": "workspace/moonfall-2026-08-21.mp3"}
    assert ci.resolve_audio_url(meta, 60) == ci.release_audio_url(
        60, "moonfall-2026-08-21.mp3")


def test_derived_url_matches_what_the_create_path_would_have_built():
    """Byte-identical to the f-string cmd_release used before this fix."""
    episode_number, mp3_path = 60, Path("workspace/moonfall-2026-08-21.mp3")
    repo, tag = "topherhooper/omelas-stories", f"v{episode_number}"
    legacy = f"https://github.com/{repo}/releases/download/{tag}/{mp3_path.name}"
    assert ci.resolve_audio_url({"mp3_path": str(mp3_path)}, episode_number) == legacy


def test_record_audio_url_persists_to_metadata(tmp_path, monkeypatch):
    metadata = tmp_path / "metadata.json"
    monkeypatch.setattr(ci, "METADATA_FILE", metadata)
    meta = {"mp3_path": "workspace/moonfall-2026-08-21.mp3"}

    returned = ci.record_audio_url(meta, 60)

    assert meta["audio_url"] == returned
    assert json.loads(metadata.read_text())["audio_url"] == returned


def test_record_audio_url_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "METADATA_FILE", tmp_path / "metadata.json")
    meta = {"mp3_path": "workspace/moonfall-2026-08-21.mp3"}
    assert ci.record_audio_url(meta, 60) == ci.record_audio_url(meta, 60)
