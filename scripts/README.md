# Session Automation Scripts

This directory contains automation scripts for the D&D campaign documentation workflow.

## automate_session.py

A comprehensive Python script that automates the workflow of creating session notes from transcript files.

### What It Does

1. **Finds the latest SRT file** in `transcripts_raw/` directory
2. **Runs the transcript cleaner** (`plugins/transcript_cleaner_ai_optimized.py`) to convert SRT to markdown
3. **Determines the next session number** by analyzing existing session files
4. **Generates a Claude prompt** with context from recent sessions
5. **Prepares everything** for Claude Code to create the full session notes

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
