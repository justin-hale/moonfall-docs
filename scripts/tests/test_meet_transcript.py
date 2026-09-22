"""Unit tests for the Meet transcript document → SRT converter.

Run with:  python -m pytest scripts/tests/ -q

Session 62 is why this exists. The caption track Meet embeds in the recording
arrived with 2,167 of its 3,581 cues carrying an empty `()` speaker tag, so the
cleaner folded the whole session into one 44,318-character block attributed to
a single person and recap generation failed on the result. The separate Meet
transcript document for the same meeting still named all four speakers across
1,927 lines. These tests pin the shape of that document and the SRT it becomes.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import meet_transcript as mt  # noqa: E402


DOC = """## **DnD - 2026/09/18 19:48 CDT - Transcript**

# **Attendees**

Ali Leonard, Christopher Hooper, Luke Neverisky, Tyram

# **Transcript**

### 00:05:00

Christopher Hooper: Hello.

Tyram: Hello. How you doing?

### 00:10:00

Tyram:

Ali Leonard: Rolling for initiative.

Luke Neverisky: Nat twenty.

### Meeting ended after 00:15:00 \U0001f44b

*This editable transcript was computer generated and might contain errors.*
"""


def test_every_attributed_line_is_kept_in_order():
    entries, _ = mt.parse_transcript_doc(DOC)
    assert [(s, t) for _, s, t in entries] == [
        ("Christopher Hooper", "Hello."),
        ("Tyram", "Hello. How you doing?"),
        ("Ali Leonard", "Rolling for initiative."),
        ("Luke Neverisky", "Nat twenty."),
    ]


def test_headings_attendees_and_the_disclaimer_are_not_utterances():
    entries, _ = mt.parse_transcript_doc(DOC)
    said = [t for _, _, t in entries]
    assert not any("Attendees" in t for t in said)
    assert not any("computer generated" in t for t in said)
    # The attendees list is a bare line with no colon, so it must not appear.
    assert not any("Ali Leonard, Christopher Hooper" in t for t in said)


def test_a_speaker_with_no_words_is_dropped():
    # Meet emits a bare "Name:" for an utterance it captured no words for —
    # 34 of them in the 2026-09-18 export. They would only widen a cue.
    entries, _ = mt.parse_transcript_doc(DOC)
    assert all(t for _, _, t in entries)
    assert len(entries) == 4


def test_lines_are_timed_inside_the_section_they_were_found_in():
    entries, _ = mt.parse_transcript_doc(DOC)
    sections = [sec for sec, _, _ in entries]
    assert sections == [300, 300, 600, 600]


def test_meeting_end_is_read_from_the_closing_marker():
    _, meeting_end = mt.parse_transcript_doc(DOC)
    assert meeting_end == 900


def test_srt_cues_are_ordered_and_never_overlap():
    entries, meeting_end = mt.parse_transcript_doc(DOC)
    srt = mt.to_srt(entries, meeting_end)

    times = []
    for line in srt.split("\n"):
        if "-->" in line:
            start, end = (part.strip() for part in line.split("-->"))
            times.append((start, end))

    assert len(times) == 4
    for (_, end), (next_start, _) in zip(times, times[1:]):
        assert end <= next_start, f"{end} overlaps {next_start}"


def test_srt_carries_the_speaker_in_the_shape_the_cleaner_reads():
    entries, meeting_end = mt.parse_transcript_doc(DOC)
    srt = mt.to_srt(entries, meeting_end)
    assert "(Christopher Hooper)\nHello." in srt
    assert "(Luke Neverisky)\nNat twenty." in srt
    # No empty speaker tags — the whole point.
    assert "()" not in srt


def test_the_last_section_runs_to_the_meeting_end_not_a_fixed_window():
    entries, meeting_end = mt.parse_transcript_doc(DOC)
    srt = mt.to_srt(entries, meeting_end)
    last_end = [l for l in srt.split("\n") if "-->" in l][-1].split("-->")[1].strip()
    assert last_end == "00:15:00,000"


def test_a_document_with_no_utterances_produces_no_srt():
    entries, _ = mt.parse_transcript_doc("# Attendees\n\nNobody\n")
    assert entries == []
    assert mt.to_srt(entries) == ""


def test_speaker_counts_report_what_the_source_actually_contains():
    entries, _ = mt.parse_transcript_doc(DOC)
    assert mt.speaker_counts(entries) == {
        "Christopher Hooper": 1,
        "Tyram": 1,
        "Ali Leonard": 1,
        "Luke Neverisky": 1,
    }


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "00:00:00,000"), (61.5, "00:01:01,500"), (3661, "01:01:01,000")],
)
def test_srt_timestamps_are_formatted_as_srt_expects(seconds, expected):
    assert mt._srt_time(seconds) == expected
