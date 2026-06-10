#!/usr/bin/env python3
"""
Deterministic lint for generated session notes. No LLM calls — stdlib only.

Checks:
  1. kb-term:        known transcription errors present in the note (autofix)
                     and player/Google-Meet names used in narrative prose (warn)
  2. frontmatter:    required fields present, no template placeholders,
                     date matches the transcript date (error)
  3. quote:          every blockquote fuzzy-matches a span of the transcript (warn)
  4. entity:         repeated proper nouns absent from the KB and the transcript (warn)
  5. anchor:         <!-- transcript: HH:MM:SS --> section anchors are present,
                     monotonically increasing, and within the transcript range (warn)

Usage:
  python scripts/lint_session.py --note PATH --transcript PATH --kb PATH \
      --json-out PATH [--expected-date YYYY-MM-DD]

Exit codes: 0 = clean or warns only, 1 = error/autofix findings, 2 = usage/IO error.
"""

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "plugins"))
from campaign_kb import apply_replacements, load_kb_entities  # noqa: E402


PLACEHOLDER_PATTERNS = [
    "[Title To Be Generated]",
    "[Description to be generated",
    "[Summary to be generated",
    "[Content to be generated",
    "[Section Title]",
]

# Common words that look like proper nouns at sentence starts; never flag.
ENTITY_STOPWORDS = {
    "The", "A", "An", "And", "But", "He", "She", "It", "They", "We", "His",
    "Her", "Their", "Its", "This", "That", "These", "Those", "When", "While",
    "After", "Before", "Then", "Now", "With", "Without", "One", "Two", "Three",
    "Four", "Five", "Six", "Everyone", "Everybody", "Nobody", "Session", "DM",
    "Interlude", "Initiative", "Insight", "Perception", "Arcana", "History",
    "Performance", "Deception", "Persuasion", "Stealth", "Acrobatics",
    "Athletics", "Investigation", "Sleight", "Hand", "Nat", "DC", "MVP",
}


def make_finding(severity, check, location, problem, suggested_fix=None):
    return {
        "severity": severity,
        "check": check,
        "location": location,
        "problem": problem,
        "suggested_fix": suggested_fix,
    }


def parse_frontmatter(text):
    """Return (fields dict, body). Tolerates missing frontmatter."""
    m = re.match(r"\A---\n(.*?)\n---\n?(.*)\Z", text, re.DOTALL)
    if not m:
        return {}, text
    fields = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"^(\w+):\s*(.*)$", line)
        if kv:
            fields[kv.group(1)] = kv.group(2).strip().strip('"')
    return fields, m.group(2)


def extract_sections(body):
    """Split body into (heading, text) tuples by ## headings; first tuple is preamble."""
    sections = []
    current_heading = None
    current_lines = []
    for line in body.splitlines():
        m = re.match(r"^##\s+(.*)$", line)
        if m and not line.startswith("###"):
            sections.append((current_heading, "\n".join(current_lines)))
            current_heading = m.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)
    sections.append((current_heading, "\n".join(current_lines)))
    return sections


def extract_quotes(body):
    """Return list of (line_number, quote_text) for blockquote runs."""
    quotes = []
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith(">"):
            start = i
            block = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                block.append(lines[i].lstrip()[1:].strip())
                i += 1
            text = " ".join(b for b in block if b)
            # Strip attribution suffix: — Name / - Name / *— Name*
            text = re.sub(r"[*_\s]*[—–-]\s*[A-Z][\w'. ()-]*[*_\s]*$", "", text)
            # A block may contain several quoted spans with interleaved
            # attribution ("..." Finnegan replied: "..."); lint each span
            # separately so one paraphrase doesn't sink the whole block.
            spans = re.findall(r'["“]([^"“”]+)["”]', text)
            if spans:
                for span in spans:
                    span = span.strip()
                    if span:
                        quotes.append((start + 1, span))
            else:
                text = text.strip().strip("*_").strip()
                text = text.strip('"“”').strip("'").strip()
                if text:
                    quotes.append((start + 1, text))
        else:
            i += 1
    return quotes


def normalize(s):
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def quote_coverage(norm_quote, norm_transcript):
    """Best fraction of the quote's characters found contiguously-ish in the
    transcript, searched near occurrences of the quote's rarest 2-word shingle."""
    words = norm_quote.split()
    if len(words) < 2:
        return 1.0  # too short to meaningfully ground
    shingles = {" ".join(words[i:i + 2]) for i in range(len(words) - 1)}

    # Rank shingles by transcript frequency (rarest-but-present first).
    ranked = []
    for sh in shingles:
        count = 0
        start = 0
        while count < 20:
            idx = norm_transcript.find(sh, start)
            if idx < 0:
                break
            count += 1
            start = idx + 1
        if count:
            ranked.append((count, sh))
    if not ranked:
        return 0.0
    ranked.sort()

    best = 0.0
    qlen = len(norm_quote)
    for _, sh in ranked[:3]:
        start = 0
        positions = []
        while len(positions) < 20:
            idx = norm_transcript.find(sh, start)
            if idx < 0:
                break
            positions.append(idx)
            start = idx + 1
        for idx in positions:
            window = norm_transcript[max(0, idx - qlen):idx + qlen + 150]
            blocks = SequenceMatcher(None, norm_quote, window).get_matching_blocks()
            coverage = sum(b.size for b in blocks) / qlen
            best = max(best, coverage)
            if best >= 0.95:
                return best
    return best


def check_kb_terms(body, sections, entities, findings):
    # 1a. Known transcription errors anywhere in the note -> autofix
    for says, should_be in entities["transcription_errors"].items():
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(says) + r"(?![A-Za-z0-9_])"
        hits = len(re.findall(pattern, body))
        if hits:
            findings.append(make_finding(
                "autofix", "kb-term", f"{hits} occurrence(s) in note body",
                f'Known transcription error "{says}" should be "{should_be}"',
                {"find": says, "replace": should_be},
            ))

    # 1b. Player / Google Meet names in narrative prose -> warn
    #     (exempting any "Players Present" section, where they belong)
    prose = "\n".join(
        text for heading, text in sections
        if not (heading and "players present" in heading.lower())
    )
    for name in sorted(entities["player_names"] | entities["google_meet_names"]):
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])"
        hits = len(re.findall(pattern, prose))
        if hits:
            findings.append(make_finding(
                "warn", "kb-term", f"{hits} occurrence(s) outside Players Present",
                f'Player/meet name "{name}" used in narrative prose — '
                f"notes should use character names",
            ))


def check_frontmatter(fields, raw_text, expected_date, findings):
    for key in ("title", "date", "description", "summary"):
        if not fields.get(key):
            findings.append(make_finding(
                "error", "frontmatter", "frontmatter",
                f'Missing or empty frontmatter field "{key}"',
            ))
    for placeholder in PLACEHOLDER_PATTERNS:
        if placeholder in raw_text:
            findings.append(make_finding(
                "error", "frontmatter", "note body",
                f'Template placeholder "{placeholder}" left in note',
            ))
    if expected_date and fields.get("date") and fields["date"] != expected_date:
        findings.append(make_finding(
            "error", "frontmatter", "frontmatter",
            f'Frontmatter date "{fields["date"]}" does not match '
            f'transcript date "{expected_date}"',
        ))


def check_quotes(body, norm_transcript, findings, threshold=0.75):
    for line_no, quote in extract_quotes(body):
        nq = normalize(quote)
        if len(nq) < 15:
            continue
        coverage = quote_coverage(nq, norm_transcript)
        if coverage < threshold:
            findings.append(make_finding(
                "warn", "quote", f"line {line_no}",
                f"Blockquote not found in transcript "
                f"(best match {coverage:.0%}): \"{quote[:90]}\"",
            ))


def check_entities(body, transcript_text, entities, findings):
    known = set()
    for name in entities["canonical_names"] | entities["locations"] \
            | entities["player_names"] | entities["google_meet_names"]:
        known.add(name.lower())
        for word in name.split():
            known.add(word.lower())
    for canonical, aliases in entities["aliases_by_canonical"].items():
        for alias in aliases:
            known.add(alias.lower())
            for word in alias.split():
                known.add(word.lower())

    transcript_lower = transcript_text.lower()
    # Strip markdown emphasis so **Name** parses as a capitalized token.
    plain = re.sub(r"[*_`#>\[\]()]", " ", body)
    candidates = {}
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", plain):
        cand = m.group(1)
        words = cand.split()
        if all(w in ENTITY_STOPWORDS for w in words):
            continue
        # Single words only count when not at sentence start (preceded by
        # a lowercase character earlier on the same line).
        if len(words) == 1:
            line_start = plain.rfind("\n", 0, m.start()) + 1
            prefix = plain[line_start:m.start()]
            if not re.search(r"[a-z][^A-Za-z]*$", prefix):
                continue
            if words[0] in ENTITY_STOPWORDS:
                continue
        candidates[cand] = candidates.get(cand, 0) + 1

    flagged = []
    for cand, count in sorted(candidates.items()):
        if count < 2:
            continue
        words = [w.lower() for w in cand.split()]
        if any(w in known for w in words):
            continue
        if cand.lower() in transcript_lower:
            continue
        if all(w in transcript_lower for w in words):
            continue
        flagged.append(f"{cand} (x{count})")
    if flagged:
        findings.append(make_finding(
            "warn", "entity", "note body",
            "Names not found in KB or transcript: " + ", ".join(flagged[:15]),
        ))


def check_anchors(body, transcript_text, findings):
    anchor_re = re.compile(r"<!--\s*transcript:\s*(\d{2}):(\d{2}):(\d{2})\s*-->")
    anchors = [(m.start(), int(h) * 3600 + int(mn) * 60 + int(s))
               for m, (h, mn, s) in
               ((m, m.groups()) for m in anchor_re.finditer(body))]
    if not anchors:
        findings.append(make_finding(
            "warn", "anchor", "note body",
            "No <!-- transcript: HH:MM:SS --> section anchors found "
            "(expected for notes generated after the anchors change)",
        ))
        return

    seconds = [s for _, s in anchors]
    if seconds != sorted(seconds):
        findings.append(make_finding(
            "warn", "anchor", "note body",
            "Transcript anchors are not monotonically increasing",
        ))

    markers = re.findall(r"^### \[(\d{2}):(\d{2}):(\d{2})\]", transcript_text, re.M)
    if markers:
        h, mn, s = markers[-1]
        last_marker = int(h) * 3600 + int(mn) * 60 + int(s)
        # Anchors may legitimately fall after the last 10-minute marker.
        limit = last_marker + 600
        for _, sec in anchors:
            if sec > limit:
                findings.append(make_finding(
                    "warn", "anchor", "note body",
                    f"Anchor at {sec}s exceeds transcript range (~{limit}s)",
                ))


def main():
    parser = argparse.ArgumentParser(description="Lint a generated session note")
    parser.add_argument("--note", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--kb", required=True)
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--expected-date", default=None,
                        help="Defaults to the transcript filename date")
    args = parser.parse_args()

    note_path = Path(args.note)
    transcript_path = Path(args.transcript)
    kb_path = Path(args.kb)
    for p in (note_path, transcript_path, kb_path):
        if not p.exists():
            print(f"Error: {p} not found", file=sys.stderr)
            return 2

    note_text = note_path.read_text(encoding="utf-8")
    transcript_text = transcript_path.read_text(encoding="utf-8")
    entities = load_kb_entities(kb_path)

    expected_date = args.expected_date
    if not expected_date:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", transcript_path.stem)
        expected_date = m.group(1) if m else None

    # Canonicalize the transcript in memory so notes (which use canonical
    # names) match transcripts that still contain alias forms — required
    # for every transcript cleaned before the canonicalization fix.
    canonical_transcript = apply_replacements(
        transcript_text, entities["transcription_errors"], case_sensitive=True
    )
    norm_transcript = normalize(canonical_transcript)

    fields, body = parse_frontmatter(note_text)
    sections = extract_sections(body)

    findings = []
    check_kb_terms(body, sections, entities, findings)
    check_frontmatter(fields, note_text, expected_date, findings)
    check_quotes(body, norm_transcript, findings)
    check_entities(body, canonical_transcript, entities, findings)
    check_anchors(body, transcript_text, findings)

    out = {"findings": findings}
    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_out).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    errors = [f for f in findings if f["severity"] in ("error", "autofix")]
    warns = [f for f in findings if f["severity"] == "warn"]
    print(f"Lint: {len(errors)} error/autofix, {len(warns)} warn "
          f"-> {args.json_out}")
    for f in findings:
        print(f"  [{f['severity']}] {f['check']} @ {f['location']}: {f['problem']}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
