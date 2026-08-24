#!/usr/bin/env python3
"""Deterministic post-processing and validation for generated session recaps.

The generator hands the model an empty file and asks it to write the whole
thing, frontmatter included. That works for prose, but the model has also been
authoring fields it cannot possibly know, and the results shipped:

  * Session 57 dropped `podcastlink` entirely and replaced "Players Present"
    with a "Setting" section, so the stats extractor found no attendance.
  * Session 58 dated itself 2026-06-26 — Session 56's date — and invented a
    Spotify episode URL.
  * Session 59 dated itself 2026-08-28, three weeks after the session it was
    recapping, invented another episode URL, printed "Brew" for Bru, and
    credited a quote to "Tyram" (a Google Meet handle).

Every one of those needed a hand-written repair commit, and a wrong date is
worse than it looks: extract_session_stats.py joins a recap to its transcript
on that date, so a hallucinated one silently drops the session out of the
stats dataset entirely.

So this module takes the knowable fields away from the model. The prompt still
asks; these functions guarantee — the same division of labour
_apply_publication_metadata() already uses for the byline. Anything that
cannot be repaired deterministically is caught by validate_recap() and fails
the run, which leaves the SRT in place for a re-run instead of publishing a
malformed recap.

The name corrections are read from data/campaign-kb.md rather than hardcoded,
so every row `/fix-notes` adds to the Known Transcription Errors table
immunises future recaps against that mistake automatically.
"""

import re
from datetime import datetime
from pathlib import Path

# Frontmatter keys every recap must carry. `author`/`beat` are stamped
# separately by the persona layer and are absent on pre-arc sessions.
REQUIRED_FRONTMATTER = ("title", "date", "description", "summary", "podcastlink")

# Headings extract_session_stats.py accepts for the attendance list
# (see its ATTENDANCE heading pattern) — a recap without one is invisible
# to the stats dataset.
# Trailing whitespace is matched as [ \t]* rather than \s* throughout: \s
# swallows newlines even before a multiline $, which would let the date-header
# rewrite below eat the blank line separating it from the next section.
ATTENDANCE_HEADING_RE = re.compile(
    r"^#{2,3} (Players Present|Party Members Present|Party Members)[ \t]*$", re.M)

PLOT_HEADING_RE = re.compile(r"^#{2,3} Plot Events[ \t]*$", re.M)

FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n?", re.S)

# The ***Month D, YYYY*** line under the frontmatter.
DATE_HEADER_RE = re.compile(r"^\*\*\*.+\*\*\*[ \t]*$", re.M)

# Placeholder text from create_session_template() that must never survive.
PLACEHOLDER_RE = re.compile(r"\[(?:Title|Description|Summary|Content)[^\]]*[Gg]enerated\]|\[To be generated\]")

# Internal doc link: [label](/dir/page) — optional trailing slash and anchor.
# The lookbehind skips images, whose target lives in static/ rather than docs/.
INTERNAL_LINK_RE = re.compile(
    r"(?<!!)\[([^\]\n]+)\]\((/[A-Za-z0-9._/-]*?)/?(#[A-Za-z0-9._-]+)?\)")


# --------------------------------------------------------------------------- #
#  Frontmatter helpers                                                         #
# --------------------------------------------------------------------------- #

def split_frontmatter(text):
    """Return (frontmatter_block, body) or (None, text) when there is none."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, text
    return match.group(1), text[match.end():]


def join_frontmatter(frontmatter, body):
    return f"---\n{frontmatter}---\n{body}"


def get_frontmatter_value(text, key):
    """Read a scalar frontmatter value, with surrounding quotes stripped.

    Returns None when there is no frontmatter or the key is absent.
    """
    frontmatter, _ = split_frontmatter(text)
    if frontmatter is None:
        return None
    match = re.search(rf"^{re.escape(key)}:[ \t]*(.*)$", frontmatter, re.M)
    if not match:
        return None
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def set_frontmatter_value(frontmatter, key, rendered_value):
    """Replace `key:` in *frontmatter*, appending it if it is missing.

    *rendered_value* is written verbatim, so callers control quoting.
    """
    pattern = re.compile(rf"^{re.escape(key)}:.*$", re.M)
    line = f"{key}: {rendered_value}"
    if pattern.search(frontmatter):
        return pattern.sub(lambda _: line, frontmatter, count=1)
    return frontmatter + line + "\n"


def display_date(date_str):
    """2026-08-14 -> 'August 14, 2026' (no platform-specific strftime flags)."""
    parsed = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


# --------------------------------------------------------------------------- #
#  Repairs                                                                     #
# --------------------------------------------------------------------------- #

def stamp_session_date(text, transcript_date):
    """Force the recap's date to the transcript's date, in both places.

    The transcript filename is the authoritative record of when the session
    happened; the model only ever guesses. Rewrites the `date:` frontmatter
    key and the ***Month D, YYYY*** display header, inserting the header when
    the model omitted it (it is also the anchor the byline is inserted after).
    """
    notes = []
    header = f"***{display_date(transcript_date)}***"

    frontmatter, body = split_frontmatter(text)
    if frontmatter is None:
        return text, notes  # validate_recap() reports the missing frontmatter.

    existing = get_frontmatter_value(text, "date")
    if existing != transcript_date:
        notes.append(f"date: {existing or '(missing)'} -> {transcript_date}")
    frontmatter = set_frontmatter_value(frontmatter, "date", transcript_date)

    match = DATE_HEADER_RE.search(body)
    if match:
        if match.group(0).strip() != header:
            notes.append(f"date header: {match.group(0).strip()} -> {header}")
        body = body[:match.start()] + header + body[match.end():]
    else:
        notes.append(f"date header inserted: {header}")
        body = f"\n{header}\n{body.lstrip(chr(10))}"

    return join_frontmatter(frontmatter, body), notes


def stamp_podcast_link(text, known_link):
    """Force `podcastlink` to the link we actually know about.

    The model has no way to know an episode URL, so left to itself it invents
    one that matches the shape of the previous session's (sessions 58 and 59
    both shipped fabricated Spotify links). *known_link* is whatever the file
    already carried before generation — normally empty, or a real URL a human
    pasted in. Anything else the model wrote is dropped.
    """
    notes = []
    frontmatter, body = split_frontmatter(text)
    if frontmatter is None:
        return text, notes

    known_link = known_link or ""
    existing = get_frontmatter_value(text, "podcastlink")
    if (existing or "") != known_link:
        notes.append(f"podcastlink: {existing or '(missing)'!r} -> {known_link!r} "
                     "(model-authored URLs are not trusted)")
    frontmatter = set_frontmatter_value(frontmatter, "podcastlink", f'"{known_link}"')
    return join_frontmatter(frontmatter, body), notes


def _table_rows(kb_text, heading):
    """Yield the data rows (as cell lists) of the table under *heading*.

    The first non-separator row is the column header and is skipped — without
    that, "Transcript Aliases" would be learned as an alias of "Correct
    Spelling".
    """
    section = re.search(rf"^#{{2,3}} {re.escape(heading)}\s*$(.*?)(?=^#{{2,3}} |\Z)",
                        kb_text, re.M | re.S)
    if not section:
        return
    seen_header = False
    for line in section.group(1).splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells or set("".join(cells)) <= set("-: "):
            continue  # separator row
        if not seen_header:
            seen_header = True
            continue
        yield cells


def _clean_alias(raw):
    return raw.strip().strip('"').strip("'").strip()


def _canonical_from(name, first_word_only=False):
    """Strip a parenthetical, optionally keep only the leading name.

    Roster entries read "Bru (Felonias Bru)" and "Silas Fairbanks"; recaps
    refer to those characters as "Bru" and "Silas".
    """
    name = re.sub(r"\s*\([^)]*\)", "", name).strip()
    if first_word_only:
        name = name.split(" ")[0]
    return name


def load_name_corrections(kb_path):
    """Build {wrong form: canonical form} from data/campaign-kb.md.

    Reads the curated Known Transcription Errors table plus the alias columns
    of the roster, NPC, and location tables. Rows where the two sides agree
    (the table's "Scarlet -> Scarlet: not an error" entry) and aliases that
    collide with a real canonical name are skipped, so this can never rename
    an actual character.
    """
    try:
        kb_text = Path(kb_path).read_text(encoding="utf-8")
    except OSError:
        return {}

    corrections = {}

    def add(wrong, right):
        wrong, right = _clean_alias(wrong), _clean_alias(right)
        if not wrong or not right or wrong.lower() == right.lower():
            return
        corrections.setdefault(wrong, right)

    # Curated error table: "Bin Bullage / Bim Bulage" lists variants of one name.
    for cells in _table_rows(kb_text, "Known Transcription Errors"):
        if len(cells) < 2:
            continue
        for variant in cells[0].split("/"):
            add(variant, cells[1])

    # Alias columns elsewhere in the KB.
    alias_tables = [
        ("Player Characters (Active)", 0, 3, True),
        ("NPCs (Recurring)", 0, 3, False),
        ("Locations", 1, 2, False),
    ]
    for heading, canon_col, alias_col, first_word in alias_tables:
        for cells in _table_rows(kb_text, heading):
            if len(cells) <= max(canon_col, alias_col):
                continue
            canonical = _canonical_from(cells[canon_col], first_word_only=first_word)
            if not canonical:
                continue
            for alias in cells[alias_col].split(","):
                add(alias, canonical)

    # Never rewrite a name that is itself canonical somewhere in the KB
    # (Red's roster note warns against "Scarlet", but Scarlet is a real NPC).
    canonical_names = {v.lower() for v in corrections.values()}
    return {k: v for k, v in corrections.items() if k.lower() not in canonical_names}


def apply_name_corrections(text, corrections):
    """Replace known-wrong names with their canonical spelling.

    Case-sensitive and word-bounded: the aliases are all capitalised, so
    lowercase link paths like /player-characters/bru are untouched. Longer
    aliases are applied first so "Bin Bullage" is not half-matched by "Bin".
    """
    notes = []
    for wrong in sorted(corrections, key=len, reverse=True):
        right = corrections[wrong]
        pattern = re.compile(rf"(?<![\w-]){re.escape(wrong)}(?![\w-])")
        text, count = pattern.subn(right, text)
        if count:
            notes.append(f'"{wrong}" -> "{right}" ({count}x)')
    return text, notes


def repair_internal_links(text, docs_dir):
    """Unwrap links whose target page does not exist, keeping the label.

    A generated recap linking to a page nobody has written broke the deploy
    once already (Session 58's /npcs/scarlet/ failed `npm run build`, which is
    why the site now only warns on broken links). Dropping the link keeps the
    prose intact and the site clean.
    """
    notes = []
    docs_dir = Path(docs_dir)

    def is_doc_page(target):
        """True when *target* addresses a page inside the docs tree.

        Anything else — /img/ assets, the /stats React page under src/pages —
        is none of this function's business, so an unrecognised first segment
        is left alone rather than unwrapped.
        """
        rel = target.strip("/")
        if not rel or "/" not in rel:
            return False
        return (docs_dir / rel.split("/")[0]).is_dir()

    def resolve(target):
        rel = target.strip("/")
        return (docs_dir / f"{rel}.md").exists() or (docs_dir / rel / "index.md").exists()

    def replace(match):
        label, target, anchor = match.group(1), match.group(2), match.group(3)
        if not is_doc_page(target) or resolve(target):
            return match.group(0)
        notes.append(f'dropped dead link {target}{anchor or ""} (kept text "{label}")')
        return label

    return INTERNAL_LINK_RE.sub(replace, text), notes


# --------------------------------------------------------------------------- #
#  Validation                                                                  #
# --------------------------------------------------------------------------- #

def validate_recap(text, expected_date=None, is_interlude=False):
    """Return a list of problems that post-processing could not repair.

    A non-empty list means the recap should not be published: the caller fails
    the run, which leaves the SRT in transcripts_raw/ so a re-run picks it up.

    Interludes are exempt from the section checks — they are flashbacks and
    side stories with their own shape (none of the sixteen published ones has
    a Players Present or Plot Events section), so requiring the session format
    of them would fail every `--interlude` run.
    """
    problems = []

    frontmatter, body = split_frontmatter(text)
    if frontmatter is None:
        problems.append("no YAML frontmatter block at the top of the file")
        return problems

    for key in REQUIRED_FRONTMATTER:
        if get_frontmatter_value(text, key) is None:
            problems.append(f"frontmatter is missing `{key}`")

    title = get_frontmatter_value(text, "title") or ""
    if not title.strip():
        problems.append("frontmatter `title` is empty")

    if expected_date is not None:
        actual = get_frontmatter_value(text, "date")
        if actual != expected_date:
            problems.append(
                f"frontmatter date {actual!r} does not match the transcript date "
                f"{expected_date!r} (the stats extractor joins on this)")

    placeholder = PLACEHOLDER_RE.search(text)
    if placeholder:
        problems.append(f"unfilled template placeholder left in the recap: {placeholder.group(0)}")

    if not is_interlude:
        if not ATTENDANCE_HEADING_RE.search(body):
            problems.append('no "## Players Present" section (attendance stats are parsed from it)')

        if not PLOT_HEADING_RE.search(body):
            problems.append('no "## Plot Events" section')

    if len(body.strip()) < 500:
        problems.append(f"recap body is only {len(body.strip())} chars — generation looks truncated")

    return problems


# --------------------------------------------------------------------------- #
#  Entry point                                                                 #
# --------------------------------------------------------------------------- #

def postprocess_recap(text, transcript_date, podcast_link, kb_path, docs_dir,
                      is_interlude=False):
    """Apply every deterministic repair, then validate.

    Returns (repaired_text, notes, problems).
    """
    notes = []
    text, step_notes = stamp_session_date(text, transcript_date)
    notes.extend(step_notes)
    text, step_notes = stamp_podcast_link(text, podcast_link)
    notes.extend(step_notes)
    text, step_notes = apply_name_corrections(text, load_name_corrections(kb_path))
    notes.extend(step_notes)
    text, step_notes = repair_internal_links(text, docs_dir)
    notes.extend(step_notes)
    problems = validate_recap(text, expected_date=transcript_date, is_interlude=is_interlude)
    return text, notes, problems
