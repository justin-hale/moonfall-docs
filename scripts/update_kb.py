#!/usr/bin/env python3
"""
Propose and apply campaign knowledge-base updates after a session.

A cheap Sonnet pass reads the new note (+ KB, with grep access to the
transcript) and proposes STRUCTURED JSON: new NPCs, locations, plot-thread
updates, observed transcription errors, and correction-log entries. This
script then edits data/campaign-kb.md deterministically:

- appends deduplicated rows to the NPC / Locations / Transcription Errors tables
- merges Active Plot Threads (never removes a thread the model didn't address;
  "resolved" threads are marked, not deleted)
- appends a Session block to the Session Correction Log (including any
  auto-fixes recorded in the verification report)
- bumps the "Last updated:" date

Usage:
  python scripts/update_kb.py --note PATH --transcript PATH --kb PATH \
      [--report PATH] [--model claude-sonnet-4-6] [--timeout 600] [--dry-run]

Exit codes: 0 = applied or nothing to apply, 2 = infrastructure error.
Callers should treat failures as NON-blocking — the note still publishes.
"""

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "plugins"))
from campaign_kb import load_kb_entities  # noqa: E402


PROPOSAL_PROMPT = """You maintain the campaign knowledge base for a D&D campaign.
A new session note has been generated. Propose UPDATES to the knowledge base as
structured JSON. The transcript is at {transcript_path} — use Grep to confirm
spellings or check how often a name appears; do NOT read the whole file.

Inclusion bar (be conservative):
- new_npcs: only NPCs named at least 3 times in the transcript OR clearly
  plot-relevant going forward. Not one-scene extras.
- new_locations: only locations the party visited or that matter to the plot.
- plot_thread_updates: update threads that materially advanced; add genuinely
  new threads; mark threads "resolved" only when clearly concluded. NEVER
  propose removing a thread.
- new_transcription_errors: only systematic speech-to-text mistakes you can
  CONFIRM by grepping the transcript (the wrong form actually appears there)
  where the note (or the fixes below) uses a corrected form.
- correction_log: one bullet per notable correction made to this session's note.

Auto-fixes already applied to this session's note:
{fixes_applied}

Output ONLY a JSON object, no other text:
{{"new_npcs": [{{"name": "...", "role": "...", "aliases": ["..."]}}],
"new_locations": [{{"name": "...", "aliases": ["..."], "notes": "..."}}],
"plot_thread_updates": [{{"title": "...", "text": "...", "status": "new|updated|resolved"}}],
"new_transcription_errors": [{{"says": "...", "should_be": "...", "context": "..."}}],
"correction_log": ["..."]}}

Empty arrays are fine — propose nothing rather than guessing.

--- CURRENT KNOWLEDGE BASE ---
{kb_content}

--- NEW SESSION NOTE ({note_path}) ---
{note_content}
"""


def run_proposal(note_path, transcript_path, kb_path, fixes_applied, model,
                 timeout, project_root):
    prompt = PROPOSAL_PROMPT.format(
        transcript_path=transcript_path,
        fixes_applied=json.dumps(fixes_applied, indent=2) if fixes_applied else "(none)",
        kb_content=Path(kb_path).read_text(encoding="utf-8"),
        note_path=note_path,
        note_content=Path(note_path).read_text(encoding="utf-8"),
    )
    cmd = ["claude", "-p", "--model", model, "--output-format", "json",
           "--allowedTools", "Read,Grep"]
    try:
        result = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                timeout=timeout, cwd=str(project_root))
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"✗ KB proposal failed: {e}", file=sys.stderr)
        return None
    if result.returncode != 0:
        print(f"✗ KB proposal exited {result.returncode}: {result.stderr[:300]}",
              file=sys.stderr)
        return None
    try:
        envelope = json.loads(result.stdout)
        text = envelope.get("result", "")
    except json.JSONDecodeError:
        text = result.stdout
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        print(f"✗ No JSON in KB proposal: {text[:200]}", file=sys.stderr)
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        print(f"✗ Unparseable KB proposal: {e}", file=sys.stderr)
        return None


def _fmt_aliases(aliases):
    return ", ".join(f'"{a}"' for a in aliases if a)


def _insert_table_row(lines, section_heading, next_heading_prefix, row):
    """Insert a table row after the last existing row of the section's table."""
    start = None
    for i, line in enumerate(lines):
        if line.strip() == section_heading:
            start = i
            break
    if start is None:
        return False
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith(next_heading_prefix):
            end = j
            break
    last_row = None
    for j in range(start, end):
        if lines[j].strip().startswith("|"):
            last_row = j
    if last_row is None:
        return False
    lines.insert(last_row + 1, row)
    return True


def apply_proposal(kb_path, proposal, entities, fixes_applied, session_label,
                   dry_run=False):
    """Deterministically apply a proposal to the KB. Returns summary of changes."""
    text = kb_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    changes = []

    known_names_lower = {n.lower() for n in entities["canonical_names"]}
    for aliases in entities["aliases_by_canonical"].values():
        known_names_lower |= {a.lower() for a in aliases}
    known_locations_lower = {l.lower() for l in entities["locations"]}
    known_errors_lower = {s.lower() for s in entities["transcription_errors"]}

    # --- NPCs ---
    for npc in proposal.get("new_npcs", []) or []:
        name = (npc.get("name") or "").strip()
        if not name or name.lower() in known_names_lower:
            continue
        role = (npc.get("role") or "").strip().replace("|", "/")
        aliases = _fmt_aliases(npc.get("aliases") or [])
        row = f"| {name} | {role} | — | {aliases} |"
        if _insert_table_row(lines, "### NPCs (Recurring)", "## Locations", row):
            known_names_lower.add(name.lower())
            changes.append(f"NPC added: {name}")

    # --- Locations ---
    for loc in proposal.get("new_locations", []) or []:
        name = (loc.get("name") or "").strip()
        if not name or name.lower() in known_locations_lower:
            continue
        aliases = _fmt_aliases(loc.get("aliases") or [])
        notes = (loc.get("notes") or "").strip().replace("|", "/")
        row = f"| {name} | {name} | {aliases} | {notes} |"
        if _insert_table_row(lines, "## Locations", "## Known Transcription Errors", row):
            known_locations_lower.add(name.lower())
            changes.append(f"Location added: {name}")

    # --- Transcription errors ---
    for err in proposal.get("new_transcription_errors", []) or []:
        says = (err.get("says") or "").strip()
        should_be = (err.get("should_be") or "").strip()
        if not says or not should_be or says == should_be:
            continue
        if says.lower() in known_errors_lower:
            continue
        context = (err.get("context") or "").strip().replace("|", "/")
        row = f"| {says} | {should_be} | {context} |"
        if _insert_table_row(lines, "## Known Transcription Errors",
                             "## Active Plot Threads", row):
            known_errors_lower.add(says.lower())
            changes.append(f"Transcription error added: {says} -> {should_be}")

    # --- Active Plot Threads (merge; never drop unaddressed threads) ---
    updates = proposal.get("plot_thread_updates", []) or []
    if updates:
        start = end = None
        for i, line in enumerate(lines):
            if line.strip() == "## Active Plot Threads":
                start = i
            elif start is not None and line.startswith("## ") and i > start:
                end = i
                break
        if start is not None:
            end = end if end is not None else len(lines)
            section = lines[start + 1:end]
            bullets = []  # (title, full_line)
            for line in section:
                m = re.match(r"-\s+\*\*(.+?)\*\*:\s*(.*)", line.strip())
                if m:
                    bullets.append([m.group(1), m.group(2)])
            titles_lower = {b[0].lower(): b for b in bullets}
            for upd in updates:
                title = (upd.get("title") or "").strip()
                new_text = (upd.get("text") or "").strip()
                status = (upd.get("status") or "updated").strip()
                if not title or not new_text:
                    continue
                existing = titles_lower.get(title.lower())
                if status == "resolved":
                    if existing:
                        existing[1] = f"RESOLVED ({session_label}) — {new_text}"
                        changes.append(f"Plot thread resolved: {title}")
                elif existing:
                    existing[1] = new_text
                    changes.append(f"Plot thread updated: {title}")
                else:
                    bullets.append([title, new_text])
                    titles_lower[title.lower()] = bullets[-1]
                    changes.append(f"Plot thread added: {title}")
            new_section = [f"- **{t}**: {txt}" for t, txt in bullets]
            lines[start + 1:end] = new_section + [""]

    # --- Session Correction Log ---
    log_entries = list(proposal.get("correction_log", []) or [])
    for fix in fixes_applied or []:
        log_entries.append(
            f'Fixed: "{fix["find"]}" → "{fix["replace"]}" '
            f'({fix.get("count", "?")} instances) [auto-applied by verifier]'
        )
    if log_entries:
        lines.append("")
        lines.append(f"### {session_label}")
        for entry in log_entries:
            entry = entry.strip().lstrip("-").strip()
            lines.append(f"- {entry}")
        changes.append(f"Correction log: {len(log_entries)} entries")

    if changes:
        today = datetime.date.today().isoformat()
        for i, line in enumerate(lines):
            if line.startswith("Last updated:"):
                lines[i] = f"Last updated: {today}"
                break

    new_text = "\n".join(lines).rstrip("\n") + "\n"
    if dry_run:
        print("--- DRY RUN: proposed KB changes ---")
        for c in changes:
            print(f"  {c}")
        if not changes:
            print("  (none)")
        return changes
    if changes:
        kb_path.write_text(new_text, encoding="utf-8")
    return changes


def session_label_from_note(note_path):
    m = re.match(r"(session|interlude)-(\d+)", Path(note_path).stem)
    kind = m.group(1).capitalize() if m else "Session"
    number = m.group(2) if m else "?"
    date = ""
    try:
        head = Path(note_path).read_text(encoding="utf-8")[:500]
        dm = re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})", head, re.M)
        if dm:
            date = f" ({dm.group(1)})"
    except OSError:
        pass
    return f"{kind} {number}{date}"


def main():
    parser = argparse.ArgumentParser(description="Propose + apply KB updates")
    parser.add_argument("--note", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--kb", required=True)
    parser.add_argument("--report", default=None,
                        help="verify_session.py report (for fixes_applied)")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    note_path = Path(args.note)
    kb_path = Path(args.kb)
    for p in (note_path, Path(args.transcript), kb_path):
        if not p.exists():
            print(f"Error: {p} not found", file=sys.stderr)
            return 2

    fixes_applied = []
    if args.report and Path(args.report).exists():
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
        fixes_applied = report.get("fixes_applied", [])

    project_root = Path(__file__).parent.parent
    proposal = run_proposal(note_path, args.transcript, kb_path, fixes_applied,
                            args.model, args.timeout, project_root)
    if proposal is None:
        return 2

    entities = load_kb_entities(kb_path)
    label = session_label_from_note(note_path)
    changes = apply_proposal(kb_path, proposal, entities, fixes_applied, label,
                             dry_run=args.dry_run)
    print(f"KB update: {len(changes)} change(s) for {label}")
    for c in changes:
        print(f"  {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
