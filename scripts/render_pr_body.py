#!/usr/bin/env python3
"""
Render a markdown PR body from a verification report.

Usage:
  python scripts/render_pr_body.py automation_output/session-report.json \
      [automation_output/session-meta.json]

Prints markdown to stdout. Used by the generate-session workflow when a
note FAILs validation and is routed to a review PR instead of publishing.
"""

import json
import sys
from pathlib import Path


def esc(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def main():
    if len(sys.argv) < 2:
        print("usage: render_pr_body.py REPORT [META]", file=sys.stderr)
        return 2

    report = {}
    report_path = Path(sys.argv[1])
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))

    meta = {}
    if len(sys.argv) > 2 and Path(sys.argv[2]).exists():
        meta = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

    verdict = report.get("verdict", "UNKNOWN")
    verifier_status = report.get("verifier_status", "unknown")
    findings = report.get("findings", [])
    fixes = report.get("fixes_applied", [])

    lines = []
    lines.append("## Automated session note — needs review")
    lines.append("")
    lines.append(f"Validation verdict: **{verdict}** "
                 f"(verifier: {verifier_status}"
                 + (f", generation: {meta['generation_mode']}" if meta.get("generation_mode") else "")
                 + ")")
    lines.append("")
    if verifier_status != "ok":
        lines.append("> ⚠️ The verifier itself failed or timed out, so this note "
                     "is **unverified** — review it manually before merging.")
        lines.append("")

    errors = [f for f in findings if f.get("severity") == "error"]
    autofixes = [f for f in findings if f.get("severity") == "autofix"]
    warns = [f for f in findings if f.get("severity") == "warn"]

    if findings:
        lines.append(f"### Findings ({len(errors)} error, "
                     f"{len(autofixes)} autofix, {len(warns)} warn)")
        lines.append("")
        lines.append("| Severity | Check | Location | Problem |")
        lines.append("|---|---|---|---|")
        for f in sorted(findings, key=lambda x: ("error", "autofix", "warn")
                        .index(x.get("severity", "warn"))):
            lines.append(f"| {f.get('severity')} | {esc(f.get('check', ''))} "
                         f"| {esc(f.get('location', ''))} "
                         f"| {esc(f.get('problem', ''))[:300]} |")
        lines.append("")

    if fixes:
        lines.append("### Auto-fixes already applied")
        lines.append("")
        for fx in fixes:
            lines.append(f"- `{fx['find']}` → `{fx['replace']}` "
                         f"({fx.get('count', '?')} instances)")
        lines.append("")

    lines.append("Merging this PR publishes the note (the site deploys and "
                 "Discord is notified automatically).")
    lines.append("")
    lines.append("<details><summary>Raw report</summary>")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(report, indent=2)[:60000])
    lines.append("```")
    lines.append("")
    lines.append("</details>")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
