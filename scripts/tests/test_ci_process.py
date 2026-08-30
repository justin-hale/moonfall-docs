"""Unit tests for the episode intake pipeline's resume paths.

Run with:  python -m pytest scripts/tests/ -q

Episode 60 was downloaded, released, added to the feed and opened as a notes
PR — and then the run failed on the very last step, a `git push` of
data/episodes.json that a concurrently merged PR had made non-fast-forward.
All five stage records were discarded. The next run re-detected episode 60,
found the release already published, skipped the release step, and died on
`KeyError: 'audio_url'` with a 1.2 GB download already paid for.

These tests pin the rule that came out of it: every stage has to reach the
same recorded end state whether it did the work or found the work already
done. No network — `gh` and `git` are stubbed.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ci_process as ci  # noqa: E402


RELEASE_URL = (
    "https://github.com/topherhooper/omelas-stories/"
    "releases/download/v60/DnD_2026-08-21.mp3"
)

EMPTY_FEED = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<rss version="2.0"><channel><title>Omelas</title></channel></rss>\n'
)


class FakeRun:
    """Stand-in for subprocess.run, dispatching on the command's first words.

    Handlers are keyed by a prefix of the argv list, e.g.
    ("gh", "release", "view"). Each returns (returncode, stdout, stderr).
    Every call is recorded so tests can assert on what was *not* run.
    """

    def __init__(self, handlers):
        self.handlers = handlers
        self.calls = []

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(list(cmd))
        for prefix, outcome in self.handlers.items():
            if list(cmd[:len(prefix)]) == list(prefix):
                code, out, err = outcome
                return _Completed(code, out, err)
        return _Completed(0, "", "")

    def ran(self, *prefix):
        return any(c[:len(prefix)] == list(prefix) for c in self.calls)


class _Completed:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A temp project with workspace/metadata.json and an empty registry."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ci, "WORKSPACE", Path("workspace"))
    monkeypatch.setattr(ci, "METADATA_FILE", Path("workspace/metadata.json"))
    monkeypatch.setattr(ci, "REGISTRY_FILE", Path("data/episodes.json"))

    Path("workspace").mkdir()
    mp3 = Path("workspace/DnD_2026-08-21.mp3")
    mp3.write_bytes(b"\x00" * 32)
    Path("workspace/metadata.json").write_text(json.dumps({
        "original_filename": "DnD - 2026/08/21 19:08 CDT - Recording",
        "source_path": "workspace/source_video.mp4",
        "episode_number": 60,
        "session_date": "2026-08-21",
        "mp3_path": str(mp3),
        "srt_path": "workspace/DnD_2026-08-21.srt",
    }))
    return tmp_path


def read_meta():
    return json.loads(Path("workspace/metadata.json").read_text())


# --------------------------------------------------------------------------- #
#  registry helpers                                                            #
# --------------------------------------------------------------------------- #

def test_stage_value_returns_the_recorded_value(workspace):
    ci.mark_stage(60, "release", RELEASE_URL)
    assert ci.stage_value(60, "release") == RELEASE_URL
    assert ci.stage_done(60, "release")


def test_stage_value_is_none_for_unknown_episode_or_stage(workspace):
    assert ci.stage_value(60, "release") is None
    ci.mark_stage(60, "download", "abc")
    assert ci.stage_value(60, "release") is None
    assert not ci.stage_done(60, "release")



# --------------------------------------------------------------------------- #
#  extract                                                                     #
# --------------------------------------------------------------------------- #

def test_extract_reruns_when_the_registry_says_done_but_workspace_is_empty(workspace, monkeypatch):
    """workspace/ is per-run; the registry outlives it.

    Skipping on the registry alone left metadata without mp3_path, so release
    died on `KeyError: 'mp3_path'` — the same shape as the audio_url break, one
    step earlier.
    """
    Path("workspace/DnD_2026-08-21.mp3").unlink()
    ci.mark_stage(60, "extract", "DnD_2026-08-21.mp3")

    ran = []

    def fake_run(cmd, *a, **k):
        ran.append(list(cmd))
        if cmd[0] == "ffmpeg":
            # emulate ffmpeg writing its output file
            Path(cmd[-1]).write_bytes(b"\x00" * 8)
        return _Completed(0, "", "")

    monkeypatch.setattr(ci.subprocess, "run", fake_run)

    ci.cmd_extract()

    assert any(c[0] == "ffmpeg" for c in ran)
    assert read_meta()["mp3_path"] == "workspace/DnD_2026-08-21.mp3"


def test_extract_skips_when_its_output_is_still_on_disk(workspace, monkeypatch):
    ci.mark_stage(60, "extract", "DnD_2026-08-21.mp3")
    Path("workspace/DnD_2026-08-21.srt").write_text("1\n")

    ran = []
    monkeypatch.setattr(ci.subprocess, "run",
                        lambda cmd, *a, **k: (ran.append(list(cmd)), _Completed(0, "", ""))[1])

    ci.cmd_extract()

    assert not any(c[0] == "ffmpeg" for c in ran)
    # Still republishes the paths, so release and update-feed can find them.
    assert read_meta()["mp3_path"] == "workspace/DnD_2026-08-21.mp3"
    assert read_meta()["srt_path"] == "workspace/DnD_2026-08-21.srt"


# --------------------------------------------------------------------------- #
#  release lookups                                                             #
# --------------------------------------------------------------------------- #

def test_release_audio_url_prefers_the_published_asset(monkeypatch):
    # The asset on an older release is named C4E*, not DnD_* — constructing the
    # URL from the local filename would 404.
    fake = FakeRun({("gh", "release", "view"): (0, json.dumps({"assets": [
        {"name": "notes.txt", "url": "https://example.invalid/notes.txt"},
        {"name": "C4E61_2026-08-21.mp3", "url": "https://example.invalid/C4E61.mp3"},
    ]}), "")})
    monkeypatch.setattr(ci.subprocess, "run", fake)
    assert ci.release_audio_url("v60", "DnD_2026-08-21.mp3") == "https://example.invalid/C4E61.mp3"


def test_release_audio_url_falls_back_to_the_local_name(monkeypatch):
    fake = FakeRun({("gh", "release", "view"): (1, "", "release not found")})
    monkeypatch.setattr(ci.subprocess, "run", fake)
    assert ci.release_audio_url("v60", "DnD_2026-08-21.mp3") == RELEASE_URL
    assert ci.release_audio_url("v60") is None


def test_release_tag_for_date_matches_on_the_release_title(monkeypatch):
    fake = FakeRun({("gh", "release", "list"): (0, json.dumps([
        {"tagName": "v59", "name": "Episode 59 - 2026-08-14"},
        {"tagName": "v60", "name": "Episode 60 - 2026-08-21"},
    ]), "")})
    monkeypatch.setattr(ci.subprocess, "run", fake)
    assert ci.release_tag_for_date("2026-08-21") == "v60"
    assert ci.release_tag_for_date("2026-08-28") is None


# --------------------------------------------------------------------------- #
#  release                                                                     #
# --------------------------------------------------------------------------- #

def test_release_reuses_an_existing_release_and_still_sets_audio_url(workspace, monkeypatch):
    """The regression itself: a release for this date is already published."""
    fake = FakeRun({
        ("gh", "release", "list"): (0, json.dumps(
            [{"tagName": "v60", "name": "Episode 60 - 2026-08-21"}]), ""),
        ("gh", "release", "view"): (0, json.dumps(
            {"assets": [{"name": "DnD_2026-08-21.mp3", "url": RELEASE_URL}]}), ""),
    })
    monkeypatch.setattr(ci.subprocess, "run", fake)

    ci.cmd_release()

    assert read_meta()["audio_url"] == RELEASE_URL
    # Recorded as a URL, like every other entry in the registry — the old code
    # stored the release *title* here.
    assert ci.stage_value(60, "release") == RELEASE_URL
    assert not fake.ran("gh", "release", "create")


def test_release_reuses_a_url_already_in_the_registry(workspace, monkeypatch):
    ci.mark_stage(60, "release", RELEASE_URL)
    fake = FakeRun({("gh", "release", "list"): (0, "[]", "")})
    monkeypatch.setattr(ci.subprocess, "run", fake)

    ci.cmd_release()

    assert read_meta()["audio_url"] == RELEASE_URL
    assert not fake.ran("gh", "release", "create")


def test_release_creates_when_nothing_exists(workspace, monkeypatch):
    fake = FakeRun({("gh", "release", "list"): (0, "[]", "")})
    monkeypatch.setattr(ci.subprocess, "run", fake)
    written = {}
    monkeypatch.setattr(ci, "write_github_env",
                        lambda k, v: written.__setitem__(k, v))

    ci.cmd_release()

    assert fake.ran("gh", "release", "create")
    assert read_meta()["audio_url"] == RELEASE_URL
    assert written == {"RELEASE_CREATED_THIS_RUN": "true"}


def test_release_does_not_claim_a_preexisting_tag_for_cleanup(workspace, monkeypatch):
    """Uploading into someone else's tag must not arm the delete-on-failure step."""
    fake = FakeRun({
        ("gh", "release", "list"): (0, "[]", ""),
        ("gh", "release", "create"): (1, "", "release already exists"),
        ("gh", "release", "upload"): (0, "", ""),
    })
    monkeypatch.setattr(ci.subprocess, "run", fake)
    written = {}
    monkeypatch.setattr(ci, "write_github_env",
                        lambda k, v: written.__setitem__(k, v))

    ci.cmd_release()

    assert fake.ran("gh", "release", "upload")
    assert read_meta()["audio_url"] == RELEASE_URL
    assert "RELEASE_CREATED_THIS_RUN" not in written


def test_release_fails_loudly_when_the_asset_cannot_be_resolved(workspace, monkeypatch):
    fake = FakeRun({
        ("gh", "release", "list"): (0, json.dumps(
            [{"tagName": "v60", "name": "Episode 60 - 2026-08-21"}]), ""),
        ("gh", "release", "view"): (0, json.dumps({"assets": []}), ""),
    })
    monkeypatch.setattr(ci.subprocess, "run", fake)
    # No fallback name is available for a tag we did not build, so this must
    # stop rather than write a URL that 404s into the podcast feed.
    monkeypatch.setattr(ci, "release_audio_url", lambda *a, **k: None)

    with pytest.raises(SystemExit) as excinfo:
        ci.cmd_release()
    assert excinfo.value.code == 1


# --------------------------------------------------------------------------- #
#  update-feed                                                                 #
# --------------------------------------------------------------------------- #

def test_update_feed_resolves_audio_url_when_metadata_lacks_it(workspace, monkeypatch):
    """The regression: metadata.json only carries audio_url if release ran here.

    On a resumed run the release already exists, so the release step used to be
    skipped and this raised `KeyError: 'audio_url'`. The URL now comes off the
    published release, and has to reach the feed's <enclosure> unchanged.
    """
    meta = read_meta()
    meta.pop("audio_url", None)
    Path("workspace/metadata.json").write_text(json.dumps(meta))
    monkeypatch.setenv("OMELAS_PAT", "token")
    monkeypatch.setattr(ci, "release_audio_url", lambda *a, **k: RELEASE_URL)
    monkeypatch.setattr(ci, "get_audio_duration", lambda p: 7200)

    state = {}

    def fake_run(cmd, *a, **k):
        if list(cmd[:2]) == ["git", "clone"]:
            repo = Path(cmd[-1])
            repo.mkdir(parents=True, exist_ok=True)
            (repo / "feed.xml").write_text(EMPTY_FEED)
            state["repo"] = repo
        if list(cmd[:2]) == ["git", "add"]:
            state["feed"] = (state["repo"] / "feed.xml").read_text()
        return _Completed(0, "", "")

    monkeypatch.setattr(ci.subprocess, "run", fake_run)

    ci.cmd_update_feed()

    assert RELEASE_URL in state["feed"]
    assert ci.stage_value(60, "update-feed") == RELEASE_URL


def test_update_feed_exits_when_no_audio_url_can_be_found(workspace, monkeypatch):
    meta = read_meta()
    meta.pop("audio_url", None)
    Path("workspace/metadata.json").write_text(json.dumps(meta))
    monkeypatch.setattr(ci, "release_audio_url", lambda *a, **k: None)

    with pytest.raises(SystemExit) as excinfo:
        ci.cmd_update_feed()
    assert excinfo.value.code == 1


def test_update_feed_skips_an_episode_the_feed_already_lists(workspace, monkeypatch):
    """Defence in depth: the registry can be lost, subscribers see duplicates."""
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel><title>Omelas</title>'
        '<item><title>Episode 60</title>'
        '<guid isPermaLink="false">omelas-stories-e60</guid></item>'
        "</channel></rss>\n"
    )
    meta = read_meta()
    meta["audio_url"] = RELEASE_URL
    Path("workspace/metadata.json").write_text(json.dumps(meta))
    monkeypatch.setenv("OMELAS_PAT", "token")

    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(list(cmd))
        if list(cmd[:2]) == ["git", "clone"]:
            repo = Path(cmd[-1])
            repo.mkdir(parents=True, exist_ok=True)
            (repo / "feed.xml").write_text(feed)
        return _Completed(0, "", "")

    monkeypatch.setattr(ci.subprocess, "run", fake_run)
    monkeypatch.setattr(ci, "get_audio_duration", lambda p: 7200)

    ci.cmd_update_feed()

    assert ci.stage_value(60, "update-feed") == RELEASE_URL
    assert not any(c[:2] == ["git", "push"] for c in calls)


def test_update_feed_appends_and_pushes_a_new_episode(workspace, monkeypatch):
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel><title>Omelas</title>'
        '<item><title>Episode 59</title>'
        '<guid isPermaLink="false">omelas-stories-e59</guid></item>'
        "</channel></rss>\n"
    )
    meta = read_meta()
    meta["audio_url"] = RELEASE_URL
    Path("workspace/metadata.json").write_text(json.dumps(meta))
    monkeypatch.setenv("OMELAS_PAT", "token")

    state = {}
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(list(cmd))
        if list(cmd[:2]) == ["git", "clone"]:
            repo = Path(cmd[-1])
            repo.mkdir(parents=True, exist_ok=True)
            (repo / "feed.xml").write_text(feed)
            state["repo"] = repo
        if list(cmd[:2]) == ["git", "add"]:
            state["feed_at_add"] = (state["repo"] / "feed.xml").read_text()
        return _Completed(0, "", "")

    monkeypatch.setattr(ci.subprocess, "run", fake_run)
    monkeypatch.setattr(ci, "get_audio_duration", lambda p: 7200)

    ci.cmd_update_feed()

    written = state["feed_at_add"]
    assert "omelas-stories-e60" in written
    assert RELEASE_URL in written
    assert written.index("omelas-stories-e60") < written.index("omelas-stories-e59")
    assert any(c[:2] == ["git", "push"] for c in calls)
    assert ci.stage_value(60, "update-feed") == RELEASE_URL


# --------------------------------------------------------------------------- #
#  open-pr                                                                     #
# --------------------------------------------------------------------------- #

def test_open_pr_for_branch_reads_the_url(monkeypatch):
    fake = FakeRun({("gh", "pr", "list"): (0, json.dumps(
        [{"url": "https://github.com/justin-hale/moonfall-docs/pull/40"}]), "")})
    monkeypatch.setattr(ci.subprocess, "run", fake)
    assert ci.open_pr_for_branch("srt/episode-60") == \
        "https://github.com/justin-hale/moonfall-docs/pull/40"


def test_open_pr_for_branch_is_none_when_nothing_is_open(monkeypatch):
    fake = FakeRun({("gh", "pr", "list"): (0, "[]", "")})
    monkeypatch.setattr(ci.subprocess, "run", fake)
    assert ci.open_pr_for_branch("srt/episode-60") is None


def test_open_pr_reuses_an_already_open_pr(workspace, monkeypatch):
    """`gh pr create` errors outright when the PR exists; reuse it instead."""
    Path("workspace/DnD_2026-08-21.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    pr_url = "https://github.com/justin-hale/moonfall-docs/pull/40"

    fake = FakeRun({
        ("gh", "pr", "list"): (0, json.dumps([{"url": pr_url}]), ""),
        # branch differs from main, so the no-op short circuit is not taken
        ("git", "diff", "--quiet"): (1, "", ""),
    })
    monkeypatch.setattr(ci.subprocess, "run", fake)
    monkeypatch.setenv("GH_TOKEN", "token")

    ci.cmd_open_pr()

    assert ci.stage_value(60, "open-pr") == pr_url
    assert not fake.ran("gh", "pr", "create")


def test_open_pr_skips_when_the_srt_is_already_on_main(workspace, monkeypatch):
    Path("workspace/DnD_2026-08-21.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")

    fake = FakeRun({("git", "diff", "--quiet"): (0, "", "")})
    monkeypatch.setattr(ci.subprocess, "run", fake)
    monkeypatch.setenv("GH_TOKEN", "token")

    ci.cmd_open_pr()

    assert ci.stage_value(60, "open-pr") == "already-on-main"
    assert not fake.ran("git", "push")
    assert not fake.ran("gh", "pr", "create")
