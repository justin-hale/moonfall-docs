"""Unit tests for the SRT -> markdown transcript cleaner.

Run with:  python -m pytest scripts/tests/ -q

Google Meet labels a caption "()" when it cannot name the speaker. The cleaner
used to drop those cues entirely; for Session 62, where only the DM was named,
that discarded 59% of the dialogue and the recap run failed. These tests pin
that unnamed cues are kept, under an explicit label.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins"))

import transcript_cleaner_ai_optimized as cleaner  # noqa: E402

# Shape of a real Meet SRT: CRLF inside a cue, LF between cues, "-" between
# speakers sharing a cue.
SRT = (
    "1\n00:09:28,000 --> 00:09:32,000\n"
    "(Christopher Hooper)\r\nHello. Pretty good.\r\n-\r\n\r\n()\r\nHello. How you\n\n"
    "2\n00:09:32,000 --> 00:09:36,000\n"
    "()\r\ndoing? Glad to hear\n\n"
    "3\n00:09:36,000 --> 00:09:40,000\n"
    "(Ali Leonard)\r\nElspeth checks the door.\n\n"
)


def _clean(tmp_path):
    srt = tmp_path / "DnD_2026-09-18.srt"
    srt.write_bytes(SRT.encode("utf-8"))  # keep the CRLFs as Meet writes them
    out = tmp_path / "out.md"
    assert cleaner.process_file(srt, out)
    return out.read_text(encoding="utf-8")


def test_unnamed_speaker_cues_are_kept(tmp_path):
    md = _clean(tmp_path)
    assert f"**{cleaner.UNIDENTIFIED_SPEAKER}:** Hello. How you doing? Glad to hear" in md


def test_named_speakers_are_unchanged(tmp_path):
    md = _clean(tmp_path)
    assert md.startswith("**Christopher Hooper:** Hello. Pretty good.")
    assert "**Ali Leonard:** Elspeth checks the door." in md


def test_unnamed_speaker_has_no_canonical_mapping(tmp_path):
    import json
    _clean(tmp_path)
    blocks = json.loads((tmp_path / "out.json").read_text())["blocks"]
    unnamed = [b for b in blocks if b["speaker_raw"] == cleaner.UNIDENTIFIED_SPEAKER]
    assert unnamed and all(b["speaker_canonical"] is None for b in unnamed)


def test_stats_count_speakers_and_warn_when_most_are_unnamed(tmp_path, capsys):
    _clean(tmp_path)
    out = capsys.readouterr().out
    assert "3 speakers:" in out
    assert "WARNING" in out and "no speaker name" in out
