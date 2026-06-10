#!/usr/bin/env python3
"""
LLM verification pass for generated session notes.

Runs `claude -p` (Sonnet) with Read+Grep only. The note and campaign KB are
inlined in the prompt; the transcript is referenced by PATH so the verifier
greps for evidence instead of reading ~50k tokens — this keeps the pass cheap
(roughly cents per session).

Merges its findings with an optional lint report, applies conservative
auto-fixes to the note, and writes a combined report with an overall verdict:

  PASS            no errors, no fixes needed
  PASS_WITH_FIXES auto-fixes applied, no errors remain
  FAIL            unresolved error findings

Usage:
  python scripts/verify_session.py --note PATH --transcript PATH --kb PATH \
      --report PATH [--lint-report PATH] [--model claude-sonnet-4-6] \
      [--timeout 600] [--no-autofix]

Exit codes:
  0 = PASS or PASS_WITH_FIXES
  1 = FAIL
  2 = verifier infrastructure failure (claude crashed / timed out / output
      unparseable). Callers must treat this as fail-closed: do not publish.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "plugins"))
from campaign_kb import load_kb_entities  # noqa: E402


VERIFIER_PROMPT = """You are verifying a D&D session note against its source transcript.

The transcript is at: {transcript_path}
It is large (~150-250k chars). Do NOT read the entire file. Use Grep to locate
evidence, and Read with offset/limit only around grep matches. The transcript
contains `### [HH:MM:SS]` markers roughly every 10 minutes, and the note may
contain `<!-- transcript: HH:MM:SS -->` anchors after section headings — use
these to scope your searches to the right part of the file.

The transcript may contain known speech-to-text errors. The campaign knowledge
base below lists canonical names, their transcript aliases, and known
transcription errors. When the transcript uses an alias or error form, that
COUNTS as confirmation of the canonical name.

Perform these checks on the note:
1. Entities: every named character, NPC, and location in the note appears in
   the knowledge base or the transcript (alias forms count). If the NOTE uses
   a form listed in "Known Transcription Errors" (the "Transcript Says"
   column), report it with severity "autofix" and exact find/replace.
2. Quotes: every blockquote (`> ...`) has a near-verbatim source line in the
   transcript. Grep for distinctive 3-5 word fragments of the quote. A quote
   that cannot be found is severity "error" if it asserts something
   significant, otherwise "warn".
3. Events: for each narrative section, the headline events are supported by
   dialogue near that section's timestamp anchor. Spot-check the 2-3 most
   significant claims per section. Contradicted or invented events are
   severity "error"; plausible but unverifiable details are "warn".
4. Frontmatter: the title, description, and summary claims match what actually
   happened in the transcript.

Output ONLY a JSON object, no other text, in exactly this shape:
{{"findings": [{{"severity": "error|warn|autofix", "location": "<where in the note>",
"problem": "<what is wrong>", "find": "<exact text>", "replace": "<exact text>"}}]}}

Rules:
- "find"/"replace" only on autofix findings, and they must be exact, single-line
  strings copied from the note / knowledge base.
- An empty findings array means the note passed.
- Be conservative with "error": reserve it for invented or contradicted content,
  not stylistic judgment.

--- CAMPAIGN KNOWLEDGE BASE ---
{kb_content}

--- SESSION NOTE UNDER REVIEW ({note_path}) ---
{note_content}
"""


def run_verifier(note_path, transcript_path, kb_path, model, timeout, project_root):
    """Run the claude CLI verifier. Returns (status, findings) where status is
    "ok" | "error" | "timeout"."""
    prompt = VERIFIER_PROMPT.format(
        transcript_path=transcript_path,
        kb_content=Path(kb_path).read_text(encoding="utf-8"),
        note_path=note_path,
        note_content=Path(note_path).read_text(encoding="utf-8"),
    )

    cmd = [
        "claude", "-p",
        "--model", model,
        "--output-format", "json",
        "--allowedTools", "Read,Grep",
    ]
    try:
        result = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            timeout=timeout, cwd=str(project_root),
        )
    except subprocess.TimeoutExpired:
        print(f"✗ Verifier timed out after {timeout}s", file=sys.stderr)
        return "timeout", []
    except FileNotFoundError:
        print("✗ 'claude' command not found", file=sys.stderr)
        return "error", []

    if result.returncode != 0:
        print(f"✗ Verifier exited {result.returncode}: {result.stderr[:500]}",
              file=sys.stderr)
        return "error", []

    # claude -p --output-format json prints a single envelope object whose
    # "result" field holds the model's text.
    try:
        envelope = json.loads(result.stdout)
        text = envelope.get("result", "")
    except json.JSONDecodeError:
        text = result.stdout

    findings = parse_findings(text)
    if findings is None:
        print(f"✗ Could not parse verifier output: {text[:300]}", file=sys.stderr)
        return "error", []
    return "ok", findings


def parse_findings(text):
    """Extract the findings JSON from model output (tolerates code fences)."""
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    raw = data.get("findings")
    if not isinstance(raw, list):
        return None
    findings = []
    for f in raw:
        if not isinstance(f, dict):
            continue
        severity = f.get("severity")
        if severity not in ("error", "warn", "autofix"):
            continue
        finding = {
            "severity": severity,
            "check": "verify",
            "location": str(f.get("location", "")),
            "problem": str(f.get("problem", "")),
            "suggested_fix": None,
        }
        if severity == "autofix" and f.get("find") and f.get("replace"):
            finding["suggested_fix"] = {
                "find": str(f["find"]),
                "replace": str(f["replace"]),
            }
        findings.append(finding)
    return findings


def apply_autofixes(note_path, findings, entities):
    """Apply conservative auto-fixes: exact single-line replacements whose
    target is a canonical KB name. Returns list of applied fix descriptions."""
    canonical_targets = set(entities["canonical_names"]) \
        | set(entities["locations"]) \
        | set(entities["transcription_errors"].values())
    # First words of canonical names are also acceptable ("Elspeth" for
    # "Elspeth Cooper").
    for name in list(canonical_targets):
        canonical_targets.add(name.split()[0])

    note_text = Path(note_path).read_text(encoding="utf-8")
    applied = []
    resolved_finds = set()
    for finding in findings:
        fix = finding.get("suggested_fix")
        if finding["severity"] != "autofix" or not fix:
            continue
        find, replace = fix["find"], fix["replace"]
        if not find or find == replace:
            continue
        if "\n" in find or "\n" in replace or len(find) > 200:
            continue
        if replace not in canonical_targets:
            # Refuse fixes whose target is not a known canonical name.
            finding["severity"] = "warn"
            finding["problem"] += " [autofix refused: replacement not a canonical KB name]"
            continue
        count = note_text.count(find)
        if count == 0:
            # Term no longer (or never) present — e.g. an earlier duplicate
            # finding already replaced it. Nothing left to fix.
            resolved_finds.add(find)
            continue
        note_text = note_text.replace(find, replace)
        resolved_finds.add(find)
        applied.append({"find": find, "replace": replace, "count": count,
                        "source": finding["check"]})
    if applied:
        Path(note_path).write_text(note_text, encoding="utf-8")
    return applied, resolved_finds


def main():
    parser = argparse.ArgumentParser(description="Verify a session note via LLM")
    parser.add_argument("--note", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--kb", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--lint-report", default=None)
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--no-autofix", action="store_true")
    args = parser.parse_args()

    note_path = Path(args.note)
    transcript_path = Path(args.transcript)
    kb_path = Path(args.kb)
    for p in (note_path, transcript_path, kb_path):
        if not p.exists():
            print(f"Error: {p} not found", file=sys.stderr)
            return 2

    project_root = Path(__file__).parent.parent
    entities = load_kb_entities(kb_path)

    findings = []
    if args.lint_report and Path(args.lint_report).exists():
        lint_data = json.loads(Path(args.lint_report).read_text(encoding="utf-8"))
        findings.extend(lint_data.get("findings", []))

    verifier_status, verifier_findings = run_verifier(
        note_path, transcript_path, kb_path, args.model, args.timeout, project_root
    )
    findings.extend(verifier_findings)

    fixes_applied = []
    resolved_finds = set()
    if not args.no_autofix:
        fixes_applied, resolved_finds = apply_autofixes(note_path, findings, entities)

    unresolved_errors = []
    for f in findings:
        if f["severity"] == "error":
            unresolved_errors.append(f)
        elif f["severity"] == "autofix":
            fix = f.get("suggested_fix") or {}
            if fix.get("find") not in resolved_finds:
                unresolved_errors.append(f)

    if verifier_status != "ok":
        verdict = "FAIL"
    elif unresolved_errors:
        verdict = "FAIL"
    elif fixes_applied:
        verdict = "PASS_WITH_FIXES"
    else:
        verdict = "PASS"

    report = {
        "verdict": verdict,
        "verifier_status": verifier_status,
        "findings": findings,
        "fixes_applied": fixes_applied,
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n",
                                 encoding="utf-8")

    print(f"Verdict: {verdict} (verifier {verifier_status}, "
          f"{len(findings)} findings, {len(fixes_applied)} fixes applied)")
    for f in findings:
        print(f"  [{f['severity']}] {f['check']} @ {f['location']}: {f['problem'][:140]}")

    if verifier_status != "ok":
        return 2
    return 0 if verdict in ("PASS", "PASS_WITH_FIXES") else 1


if __name__ == "__main__":
    sys.exit(main())
