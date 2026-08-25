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

#### Save Prompt Only (Don't Call the API)

```bash
# Generate the prompt but don't call the model
generate-session --no-generate
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

### Generation Guardrails

The model writes the whole recap file, frontmatter included — so it used to
write fields it has no way to know, and those shipped. Session 58 dated itself
2026-06-26 (Session 56's date), Session 59 dated itself three weeks into the
future, both invented a Spotify episode URL, and Session 59 printed "Brew" and
a Google Meet handle despite the prompt's name rules. Each one needed a
hand-written repair commit, and a wrong date is worse than it looks:
`extract_session_stats.py` joins a recap to its transcript on that date, so a
hallucinated one silently drops the session out of the stats dataset.

`recap_postprocess.py` now takes those fields away from the model. After every
generation it:

- **stamps the date** — both the `date:` key and the `***Month D, YYYY***`
  header — from the transcript filename, which is the authoritative record
- **strips `podcastlink`** — the campaign no longer publishes a podcast, so
  the key is removed outright. The model writes one anyway, because every
  session it reads for style still has one. A recap that already carried a
  real episode URL keeps it, so regenerating an older session does not
  destroy its link
- **applies the canonical names** from the tables in `data/campaign-kb.md` —
  Known Transcription Errors plus the alias columns of the roster, NPC and
  location tables. Every row `/fix-notes` adds there immunises future recaps
  automatically
- **unwraps dead internal links**, keeping the label. A generated link to a
  page nobody had written (`/npcs/scarlet/`) once failed `npm run build` and
  blocked a deploy
- **validates what is left** — frontmatter keys, leftover template
  placeholders, the `Players Present` and `Plot Events` sections (interludes
  are exempt; they have their own shape), and a plausible body length

Everything repaired is printed in the run log. Anything that cannot be
repaired fails the run: the recap is still written so it can be inspected, but
nothing is committed and the SRT stays in `transcripts_raw/` so a re-run picks
it up.

Run the tests with `python -m pytest scripts/tests/ -q`.

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
| `--no-generate` | Don't call the API (just save the prompt) |
| `--timeout MIN` | API timeout in minutes (default: 10) |
| `--local` | Route model calls through the local `claude` CLI |
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

## ci_process.py

The intake pipeline: Google Drive recording → MP3 + SRT → GitHub release →
podcast feed → an SRT pull request on this repo. Driven a stage at a time by
`.github/workflows/process-episode.yml`, which runs Saturday 14:00 UTC and can
be dispatched by hand.

```
detect → download → extract → release → update-feed → open-pr
```

`detect` picks the oldest published release that has no `open-pr` recorded, so
a run that stops halfway is picked up by the next one. Nothing else about the
pipeline is worth understanding before this:

### Two files hold all the state

- **`workspace/metadata.json`** — per-run scratch, thrown away with the runner.
  The stages hand each other paths and URLs through it.
- **`data/episodes.json`** — the durable registry, committed to `main` at the
  end of every run, successful or not. It records which stages an episode has
  completed and is the *only* thing standing between a re-run and a duplicate
  release, a duplicate podcast entry, or a second SRT PR.

### Every stage has to be safe to run twice

Because the registry is committed at the end of the job, a run that dies —
or whose final push loses a race — leaves work done that the registry does not
know about. Episode 60 hit exactly that: release, feed and PR all succeeded,
the registry push was rejected by a PR that merged mid-job, and the record was
discarded. The next run then found the release already published, skipped the
release step, and died on `KeyError: 'audio_url'` after re-downloading 1.2 GB.

So each stage resolves its own state from the world rather than trusting the
registry to be complete:

| Stage | Already-done check | Result |
|-------|--------------------|--------|
| `extract` | the MP3 is still in `workspace/` — the registry alone is not enough, `workspace/` dies with the runner | re-extracts, and republishes the paths either way |
| `release` | a published release whose title carries this session date | reuses it and reads its MP3 asset URL back off GitHub |
| `update-feed` | an `<item>` in `feed.xml` with this episode's guid | leaves the feed alone |
| `open-pr` | an open PR whose head is `srt/episode-N`, or an SRT already on `main` | reuses the PR, or opens none |

The workflow reflects the same rule. The release step is **not** gated on
whether a release exists — it is the step that resolves the audio URL, and
skipping it is what broke the resume path. Only a release this run actually
created sets `RELEASE_CREATED_THIS_RUN`, so the delete-on-failure cleanup can
never remove an artifact belonging to an earlier run.

### Failures are announced

The registry commit rebases onto `origin/main` and retries rather than dropping
its changes, and a failed run posts to the Discord webhook. The 2026-08-22 run
died 24 seconds in and sat unnoticed until Monday, which is what turned a
four-minute failure into a missed week of publishing.

### After the pipeline

`open-pr` leaves a PR titled `Add SRT for Episode N`. Merging it lands an
`.srt` in `transcripts_raw/` on `main`, which fires **Generate Session Notes**
— the recap, the site build, the deploy and the Discord post. The pipeline
deliberately stops at the PR: nothing is published until someone merges.

Run the tests with `python -m pytest scripts/tests/ -q`.

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
