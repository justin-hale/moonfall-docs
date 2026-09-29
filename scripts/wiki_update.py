#!/usr/bin/env python3
"""Keep the NPC, location and organization pages current after each session.

The wiki pages under docs/npcs/, docs/locations/ and docs/organizations/ were
written once, around Session 36, and nothing touched them again: by Session 63
every page described a campaign two arcs out of date. This module is the step
the generator was missing. After a recap is published, it:

1. finds which wiki pages the new recap actually involves (a link to the page,
   or its title / an `aliases:` entry appearing in the recap body);
2. asks a model for one factual sentence per page about what that entity did or
   what happened there *in this recap*, or nothing if it was a passing mention;
3. writes that sentence as the session's bullet in the page's
   "## Session History" section, replacing any earlier bullet for the same
   session so a regeneration never duplicates it.

It also asks for recurring entities that have no page yet. Those are reported
(to the console and the Actions job summary), never created: a new page is an
editorial call, not something to generate unattended.

Everything except the single model call is a pure function, so the tests cover
matching, parsing and insertion without any network access.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

WIKI_SECTIONS = ("npcs", "locations", "organizations")
HISTORY_HEADING = "## Session History"

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n?", re.S)


@dataclass
class WikiEntity:
    section: str  # "npcs" | "locations" | "organizations"
    slug: str
    path: Path
    title: str
    terms: list = field(default_factory=list)

    @property
    def key(self):
        return f"{self.section}/{self.slug}"

    @property
    def url(self):
        return f"/{self.section}/{self.slug}"


# --------------------------------------------------------------------------- #
#  Loading pages                                                               #
# --------------------------------------------------------------------------- #

def _frontmatter(text):
    match = _FRONTMATTER_RE.match(text)
    return match.group(1) if match else ""


def _frontmatter_value(frontmatter, key):
    match = re.search(rf"^{re.escape(key)}:[ \t]*(.*)$", frontmatter, re.M)
    if not match:
        return ""
    return match.group(1).strip().strip('"').strip("'")


def _frontmatter_list(frontmatter, key):
    """Read a one-line YAML flow list: `aliases: ["Viper", "Elizandra Legrand"]`."""
    raw = _frontmatter_value(frontmatter, key)
    if not raw.startswith("["):
        # Re-read without the quote stripping _frontmatter_value applies.
        match = re.search(rf"^{re.escape(key)}:[ \t]*(\[.*\])[ \t]*$", frontmatter, re.M)
        raw = match.group(1) if match else ""
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except json.JSONDecodeError:
        values = [v.strip().strip('"').strip("'") for v in raw.strip("[]").split(",")]
    return [str(v).strip() for v in values if str(v).strip()]


def load_wiki_entities(docs_dir):
    """Every NPC, location and organization page, with the terms that name it."""
    entities = []
    for section in WIKI_SECTIONS:
        folder = Path(docs_dir) / section
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            frontmatter = _frontmatter(text)
            title = _frontmatter_value(frontmatter, "title") or path.stem.replace("-", " ").title()
            terms = [title] + _frontmatter_list(frontmatter, "aliases")
            entities.append(WikiEntity(section, path.stem, path, title,
                                       list(dict.fromkeys(t for t in terms if t))))
    return entities


# --------------------------------------------------------------------------- #
#  Matching a recap to pages                                                   #
# --------------------------------------------------------------------------- #

def _recap_body(recap_text):
    """The recap without frontmatter or publication-meta blockquotes.

    Editorial notes (sessions 58+) and correction notices are in-world
    commentary by the fictional writers, not campaign events, so a name that
    appears only there should not put a bullet on a page.
    """
    body = _FRONTMATTER_RE.sub("", recap_text, count=1)
    body = body.split("\n## Corrections", 1)[0]
    return "\n".join(line for line in body.splitlines() if not line.lstrip().startswith(">"))


def find_mentioned_entities(recap_text, entities):
    """Pages the recap links to, or names by title or alias.

    Matching is case-sensitive and word-bounded: these are proper nouns, and
    "the resistance" in running prose is not the Resistance page.
    """
    body = _recap_body(recap_text)
    found = []
    for entity in entities:
        if re.search(rf"\]\({re.escape(entity.url)}/?[)#]", body):
            found.append(entity)
            continue
        for term in entity.terms:
            if re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", body):
                found.append(entity)
                break
    return found


# --------------------------------------------------------------------------- #
#  Model prompt and response                                                   #
# --------------------------------------------------------------------------- #

def build_prompt(label, recap_text, entities, existing_titles):
    listing = "\n".join(
        f"- {e.key}: {e.title}" + (f" (also: {', '.join(e.terms[1:])})" if len(e.terms) > 1 else "")
        for e in entities)
    known = ", ".join(sorted(existing_titles))
    return f"""You maintain the wiki for a D&D campaign called "Moonfall Sessions".
Below is the published recap for {label}, and a list of wiki pages whose subject the recap names.

For EACH listed page, write ONE sentence (at most two) stating what that character did, what
happened to them, or what happened at that place / to that group IN THIS RECAP. Rules:
- Use only facts stated in the recap. Do not infer, speculate, or add anything the recap does not say.
- If the page's subject is only mentioned in passing (named, remembered, or referenced, with nothing
  happening), return null for it.
- Name the player characters by character name (Silas, Bru, Elspeth, Leliana, Olivia, Ohma...).
- Plain prose: no markdown, no links, no quotation marks around the whole sentence.
- Ignore bylines, editorial notes, and correction notices — they are publication commentary, not events.

Also list recurring characters, places, or organizations that play a real part in this recap but
have NO page yet. Existing pages (do not list these): {known}.
Only include ones that matter to the ongoing story; skip one-off extras.

PAGES:
{listing}

RECAP:
{recap_text[:14000]}

Respond with ONLY a JSON object, no other text:
{{"updates": {{"<page key>": "<sentence>" or null, ...}},
  "new_entities": [{{"type": "npc" | "location" | "organization", "name": "...", "why": "<one line>"}}]}}"""


def parse_response(text):
    """Pull the JSON object out of the model's reply; tolerate a code fence."""
    if not text:
        return {"updates": {}, "new_entities": []}
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"updates": {}, "new_entities": []}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"updates": {}, "new_entities": []}
    updates = data.get("updates") if isinstance(data.get("updates"), dict) else {}
    new_entities = data.get("new_entities") if isinstance(data.get("new_entities"), list) else []
    return {"updates": updates, "new_entities": [n for n in new_entities if isinstance(n, dict)]}


def clean_entry(text):
    """Make a model sentence safe to drop into an MDX page as one bullet."""
    if not isinstance(text, str):
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    # MDX treats braces and angle brackets as JSX; a stray one breaks the build.
    text = re.sub(r"[{}<>]", "", text)
    text = text.strip('"').strip()
    return text


# --------------------------------------------------------------------------- #
#  Writing the Session History bullet                                          #
# --------------------------------------------------------------------------- #

def session_label(session_number, is_interlude=False):
    kind = "Interlude" if is_interlude else "Session"
    slug = f"{'interlude' if is_interlude else 'session'}-{session_number}"
    return f"{kind} {session_number}", f"/sessions/{slug}"


def upsert_session_entry(page_text, session_number, entry, is_interlude=False):
    """Set this session's bullet in the page's Session History section.

    Replaces an existing bullet for the same session (a regenerated recap must
    not leave two), otherwise appends to the end of the section. The section is
    created at the end of the page if the page does not have one yet.
    """
    label, url = session_label(session_number, is_interlude)
    bullet = f"- **[{label}]({url})** — {entry}"
    lines = page_text.rstrip("\n").split("\n")

    start = next((i for i, line in enumerate(lines) if line.strip() == HISTORY_HEADING), None)
    if start is None:
        return "\n".join(lines) + f"\n\n{HISTORY_HEADING}\n\n{bullet}\n"

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## ") or lines[i].strip() == "---":
            end = i
            break

    marker = re.compile(rf"^- \*\*\[{re.escape(label)}\]\(")
    for i in range(start + 1, end):
        if marker.match(lines[i]):
            lines[i] = bullet
            return "\n".join(lines) + "\n"

    # Append after the last non-blank line of the section.
    insert_at = end
    while insert_at - 1 > start and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines[insert_at:insert_at] = [bullet] if insert_at - 1 > start else ["", bullet]
    return "\n".join(lines) + "\n"


def apply_updates(entities, updates, session_number, is_interlude=False):
    """Write every non-null update to its page. Returns the keys written."""
    by_key = {e.key: e for e in entities}
    written = []
    for key, sentence in updates.items():
        entity = by_key.get(key)
        entry = clean_entry(sentence)
        if entity is None or not entry:
            continue
        page = entity.path.read_text(encoding="utf-8")
        entity.path.write_text(upsert_session_entry(page, session_number, entry, is_interlude),
                               encoding="utf-8")
        written.append(key)
    return written


def format_new_entities(new_entities):
    lines = []
    for item in new_entities:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        kind = str(item.get("type", "")).strip() or "entity"
        why = str(item.get("why", "")).strip()
        lines.append(f"- **{name}** ({kind})" + (f" — {why}" if why else ""))
    return lines
