# Session Automation Scripts

This directory contains automation scripts for the D&D campaign documentation workflow.

## automate_session.py

A comprehensive Python script that automates the workflow of creating session notes from transcript files.

### What It Does

1. **Finds the latest SRT file** in `transcripts_raw/` (by embedded date) — exits as a NOOP if none
2. **Runs the transcript cleaner** (`plugins/transcript_cleaner_ai_optimized.py`) to convert SRT to markdown, applying the campaign KB's known-transcription-error corrections
3. **Determines the next session number** by analyzing existing session files
4. **Generates the session note single-pass** — the FULL transcript is sent to Claude (Opus) in one request; chunked summarization is only a rate-limit fallback
5. **Validates the note**: deterministic lint (`lint_session.py`) + LLM verification against the transcript (`verify_session.py`) + KB updates (`update_kb.py`)
6. **Writes `automation_output/session-meta.json`** with the verdict (`PASS` / `PASS_WITH_FIXES` / `FAIL` / `NOOP`) that CI uses to decide between publishing and opening a review PR

### Usage

#### Basic Usage (Most Common)

```bash
# Process the latest transcript and prepare for the next session
generate-session
```

This will:
- Find the newest .srt file in `transcripts_raw/`
- Clean it and save to `docs/transcripts/`
- Auto-detect the next session number
- Generate a prompt for Claude Code
- **Automatically invoke Claude Code to create the session notes**

#### Create an Interlude

```bash
# Create an interlude instead of a regular session
generate-session --interlude
```

#### Specify Session Number

```bash
# Manually specify the session number
generate-session --session-number 42
```

#### Skip Transcript Cleaning

```bash
# Use existing transcript (skip cleaning step)
generate-session --no-clean
```

#### Save Prompt Only (Don't Invoke Claude)

```bash
# Generate the prompt but don't automatically run Claude
generate-session --no-claude
```

#### Alternative: Full Python Command

If the `generate-session` alias isn't working, you can use the full command:

```bash
python3 scripts/automate_session.py
```

### Workflow Example

1. Place your new SRT file in `transcripts_raw/`
2. Run: `generate-session`
3. The script will:
   - Clean the transcript
   - Generate a detailed prompt
   - **Automatically invoke Claude Code to create the session notes**
4. Review the generated session note in `docs/sessions/`

### Setup

The `generate-session` command is an alias that was automatically added to your `~/.zshrc` file. If you need to set it up again or on a different machine, add this line to your shell config:

```bash
alias generate-session='python3 ~/Dev/docusaurus/scripts/automate_session.py'
```

Then reload your shell: `source ~/.zshrc`

### Output

The script generates:
- Cleaned transcript in `docs/transcripts/YYYY-MM-DD.md`
- A detailed prompt for Claude Code
- Saves the prompt to `scripts/last_claude_prompt.txt` for reference

### Command Line Options

| Option | Description |
|--------|-------------|
| `--session-number N` | Specify session number (default: auto-detect) |
| `--interlude` | Create an interlude instead of regular session |
| `--no-clean` | Skip transcript cleaning (use existing transcript) |
| `--no-claude` | Don't invoke Claude automatically (just save prompt) |
| `--skip-validation` | Skip lint/verify/KB-update after generation (debugging) |
| `--validate-only --note N --transcript T` | Run only the validation chain against an existing note |
| `--force-fail-verdict` | Force a FAIL verdict (CI escape hatch to exercise the review-PR path) |
| `--timeout N` | Timeout in minutes per Claude invocation (default: 15) |
| `-h, --help` | Show help message |

### Requirements

- Python 3.6+
- The `transcript_cleaner_ai_optimized.py` script must exist in `plugins/`
- SRT files should be in `transcripts_raw/`

### File Structure

```
docusaurus/
├── transcripts_raw/          # Place .srt files here
├── docs/
│   ├── transcripts/          # Cleaned transcripts output here
│   └── sessions/             # Session notes created here
├── plugins/
│   └── transcript_cleaner_ai_optimized.py
└── scripts/
    ├── automate_session.py   # This script
    └── last_claude_prompt.txt # Last generated prompt
```

### Tips

- The script automatically detects the next session number by looking at existing files
- It analyzes the 5 most recent sessions to provide context to Claude
- The generated prompt includes references to recent sessions for consistency
- The transcript date is extracted from the filename (YYYY-MM-DD.md format)

### Troubleshooting

**No .srt files found:**
- Make sure your transcript file is in `transcripts_raw/` directory
- Check that the file has a `.srt` extension

**Transcript cleaning fails:**
- Verify that `plugins/transcript_cleaner_ai_optimized.py` exists
- Try running the cleaner script manually to see detailed errors

**Wrong session number:**
- Use `--session-number N` to manually specify the correct number
- The script looks at existing files in `docs/sessions/` to auto-detect

## Other Scripts

### lint_session.py

Deterministic, zero-cost lint for a generated note: scans for known
transcription errors from the campaign KB (autofixable), checks frontmatter
completeness and date, fuzzy-matches every blockquote against the transcript,
flags repeated proper nouns absent from both KB and transcript, and validates
`<!-- transcript: HH:MM:SS -->` section anchors.

```bash
python3 scripts/lint_session.py --note docs/sessions/session-55.md \
  --transcript docs/transcripts/2026-06-05.md \
  --kb data/campaign-kb.md --json-out automation_output/lint-report.json
```

### verify_session.py

LLM verification pass (Sonnet, Read+Grep only). The note and KB are inlined;
the transcript is referenced by path so the verifier greps for evidence
instead of reading ~50k tokens. Merges lint findings, applies conservative
canonical-name autofixes, and writes a report with verdict `PASS` /
`PASS_WITH_FIXES` / `FAIL`. Exit 2 = verifier infrastructure failure —
callers must fail closed (never publish unverified).

### update_kb.py

Proposes campaign-KB updates after a session (new NPCs, locations, plot-thread
updates, observed transcription errors) as structured JSON via a Sonnet pass,
then applies them deterministically with dedupe. Never removes existing plot
threads. Use `--dry-run` to preview. Failures are non-blocking.

### render_pr_body.py

Renders `automation_output/session-report.json` as a markdown PR body
(findings table + raw report) for the review-PR path in CI.

### generate-sessions-data.js

Generates session metadata for the Docusaurus site.

### add-session-positions.js

Adds position metadata to session files for proper ordering.

---

## Contributing

When adding new automation scripts:
1. Add comprehensive help text and documentation
2. Use argparse for command-line options
3. Provide clear error messages
4. Update this README with usage examples
