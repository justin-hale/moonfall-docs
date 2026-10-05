#!/usr/bin/env python3
"""Convert a Google Meet transcript document into the SRT the pipeline reads.

Why this exists
---------------
Every episode before 62 was transcribed from the caption track Meet bakes into
the recording, pulled out with `ffmpeg -map 0:2`. On 2026-09-18 that track
arrived without speaker names: 2,167 of its 3,581 cues carried an empty `()`
tag and the only name present was the host's. The cleaner folds an unnamed cue
into whoever spoke last, so the whole session collapsed into a single
44,318-character block attributed to one person, the recap model was handed a
wall of unattributed text, and generation failed.

Meet had not lost the attribution — it moved it. The same meeting produces a
separate "… - Transcript" document that still names every speaker, and for
that session it holds 1,927 attributed lines across four people. This module
turns that document back into an SRT so the rest of the pipeline is unchanged.

On timestamps
-------------
The document marks time only every five minutes (`### 00:05:00`). Lines within
a section are spread evenly across it, so a cue's time is accurate to within
that window and never out of order. That is coarser than a caption track but
finer than the recap needs: `automate_session.py` uses timestamps to anchor
narrative sections, not to quote to the second.
"""

import argparse
import re
import sys
from pathlib import Path

SECTION_RE = re.compile(r"^###\s+(\d{1,2}):(\d{2}):(\d{2})\s*$")
ENDED_RE = re.compile(r"^###\s+Meeting ended after\s+(\d{1,2}):(\d{2}):(\d{2})")
# Meet writes "Speaker Name: what they said" and, for an utterance it captured
# no words for, a bare "Speaker Name:" — 34 of those in the 2026-09-18 export.
SPEAKER_RE = re.compile(r"^([^:]{1,60}?):\s*(.*)$")

SECTION_SECONDS = 300


def _hms_to_seconds(h, m, s):
    return int(h) * 3600 + int(m) * 60 + int(s)


def parse_transcript_doc(text):
    """Return [(section_start_seconds, speaker, said)] in document order.

    Headings, the attendees list and the trailing generated-by disclaimer are
    not utterances and are dropped. So are bare "Name:" lines: an utterance
    with no words contributes nothing to a recap and would only widen a cue.
    """
    entries = []
    section_start = 0
    meeting_end = None

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue

        ended = ENDED_RE.match(line)
        if ended:
            meeting_end = _hms_to_seconds(*ended.groups())
            continue

        section = SECTION_RE.match(line)
        if section:
            section_start = _hms_to_seconds(*section.groups())
            continue

        if line.startswith("#") or line.startswith("*"):
            continue

        match = SPEAKER_RE.match(line)
        if not match:
            continue
        speaker, said = match.group(1).strip(), match.group(2).strip()
        # The attendees line ("Ali Leonard, Christopher Hooper, …") has no colon
        # and so never reaches here; a name with one would still be absurd.
        if not said or not speaker:
            continue
        entries.append((section_start, speaker, said))

    return entries, meeting_end


def to_srt(entries, meeting_end=None):
    """Render entries as SRT, spreading each section's lines across it.

    Cues are emitted in document order and never overlap, so the cleaner sees
    the same shape it gets from a caption track.
    """
    if not entries:
        return ""

    # Group consecutive entries by the section they were found in.
    sections = []
    for section_start, speaker, said in entries:
        if sections and sections[-1][0] == section_start:
            sections[-1][1].append((speaker, said))
        else:
            sections.append((section_start, [(speaker, said)]))

    out = []
    index = 1
    for position, (section_start, lines) in enumerate(sections):
        if position + 1 < len(sections):
            span = sections[position + 1][0] - section_start
        elif meeting_end and meeting_end > section_start:
            span = meeting_end - section_start
        else:
            span = SECTION_SECONDS
        span = max(span, 1)
        step = span / len(lines)

        for offset, (speaker, said) in enumerate(lines):
            start = section_start + offset * step
            end = start + step
            out.append(
                f"{index}\n{_srt_time(start)} --> {_srt_time(end)}\n"
                f"({speaker})\n{said}\n"
            )
            index += 1

    return "\n".join(out)


def _srt_time(seconds):
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total = total_ms // 1000
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d},{ms:03d}"


def speaker_counts(entries):
    """How many lines each speaker has — the check that catches a bad source."""
    counts = {}
    for _, speaker, _ in entries:
        counts[speaker] = counts.get(speaker, 0) + 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Meet transcript doc, as text")
    parser.add_argument("-o", "--output", type=Path, help="SRT to write")
    args = parser.parse_args()

    entries, meeting_end = parse_transcript_doc(
        args.source.read_text(encoding="utf-8")
    )
    if not entries:
        print("ERROR: no attributed lines found in the document.", file=sys.stderr)
        return 1

    counts = speaker_counts(entries)
    print(f"  {len(entries)} lines across {len(counts)} speaker(s):")
    for speaker, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {count:6d}  {speaker}")

    srt = to_srt(entries, meeting_end)
    if args.output:
        args.output.write_text(srt, encoding="utf-8")
        print(f"  Wrote {args.output} ({len(srt):,} chars)")
    else:
        sys.stdout.write(srt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
