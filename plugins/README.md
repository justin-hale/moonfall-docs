# Transcript Processing Scripts

Quick and easy way to process D&D session transcripts from SRT files to AI-optimized markdown.

## Quick Setup (One-time)

Run this once to set up the easy command:

```bash
./plugins/setup-alias.sh
source ~/.zshrc  # Or open a new terminal
```

## Usage

### Super Easy Way (Recommended)

1. Drop your `.srt` file into the `transcripts_raw/` folder
2. Run from anywhere:
   ```bash
   process-transcript
   ```
3. Done! Your transcript is now in `docs/transcripts/YYYY-MM-DD.md`

### Manual Way

If you didn't run the setup script:

```bash
./plugins/process-transcript.sh
```

Or directly with Python:

```bash
python3 plugins/transcript_cleaner_ai_optimized.py transcripts_raw/your-file.srt
```

## What It Does

- ✅ Finds the most recent `.srt` file in `transcripts_raw/`
- ✅ Extracts and normalizes the date to `YYYY-MM-DD` format
- ✅ Processes it into AI-friendly markdown format:
  - Groups consecutive statements by the same speaker
  - Adds blank lines between speakers
  - Bold speaker names
  - Timestamp markers every 10 minutes
- ✅ Saves to `docs/transcripts/YYYY-MM-DD.md`
- ✅ Automatically creates folders if needed

## Output Format

The processed transcript will look like:

```markdown
### [00:10:00]

**Christopher Hooper:** Complete dialogue grouped together for this speaker.

**Luke Neverisky:** Their response here, also fully grouped.

**Walden Briarhelm:** Another speaker's dialogue.

### [00:20:00]

**Tyram:** New section with timestamp...
```

This format is optimized for:
- AI parsing (GitHub Copilot, ChatGPT, etc.)
- Easy reading and navigation
- Creating session notes
- Cross-referencing with podcast timestamps

## Workflow

1. Get `.srt` file from your friend
2. Drop it in `transcripts_raw/`
3. Run `process-transcript`
4. Use the cleaned markdown file in `docs/transcripts/` to create session notes with AI
5. (Optional) Delete or archive the raw `.srt` file

## Files

- `transcript_cleaner_ai_optimized.py` - Main Python script that does the processing
- `process-transcript.sh` - Convenience script that finds and processes the latest SRT
- `setup-alias.sh` - One-time setup to create the `process-transcript` command
