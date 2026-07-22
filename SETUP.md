# Moonfall Sessions Setup Guide

## Quick Start

### Prerequisites
- Python 3.x
- Node.js 20+
- Anthropic API key

### Installation

1. **Install Python dependencies:**
```bash
pip install -r requirements.txt
```

2. **Install Node dependencies:**
```bash
npm install
```

3. **Set your Anthropic API key:**
```bash
export ANTHROPIC_API_KEY='your-api-key-here'
```

4. **Test the setup:**
```bash
python3 scripts/test_api.py
```

## Pipeline Overview

The new pipeline uses direct Anthropic API calls instead of the Claude Code CLI to reduce costs:

### Old Cost Structure (Claude Code CLI)
- 5-7 API calls per recap (chunking + agentic loop)
- Re-read several full past session files for context every time
- **Cost: $0.75-1.00 per recap**

### New Cost Structure (Direct API)
- Uses Claude Haiku for chunk summarization (~$0.01-0.02)
- Uses Claude Sonnet for generation (~$0.08-0.15)
- One running `campaign-state.md` replaces re-reading several full past sessions
- **Cost: $0.10-0.20 per recap**

Note: this script does not use prompt caching. Each run makes exactly one
generation call, and caching only pays off on a *second* call that reuses the
same system prompt within the 5-minute cache TTL — a one-shot call would just
pay the ~25% cache-write premium for no discount. If a future batch mode
generates multiple sessions in a single process, reusing the same system
prompt across those calls, caching would be worth adding back then.

## How It Works

1. **Transcript Processing**: 
   - SRT file → Python cleaner → Markdown transcript
   - If > 60K chars, chunks are summarized with Haiku

2. **Recap Generation**:
   - System prompt includes campaign KB + state
   - User prompt includes transcript/summary
   - Claude Sonnet generates the recap

3. **Campaign State Update**:
   - After each recap, the model extracts a session summary, plot thread
     updates, character updates, and new callback hooks
   - Each piece is merged into its matching section of campaign-state.md
     (Session Event Index / Active Plot Threads / Character Status / Key
     Callbacks) rather than appended as one undifferentiated blob, so the
     document stays organized as real long-term memory instead of a log

## Key Files

- `data/campaign-kb.md` - Character names, locations, corrections
- `data/campaign-state.md` - Running memory of all sessions
- `scripts/automate_session.py` - Main automation script
- `requirements.txt` - Python dependencies

## Manual Testing

### Test without API calls (free):
```bash
python3 scripts/automate_session.py --no-clean --no-generate
```

### Generate a real recap (costs ~$0.10-0.20):
```bash
python3 scripts/automate_session.py --no-clean
```

### Full pipeline with SRT cleaning:
```bash
python3 scripts/automate_session.py
```

### Generate locally against your Claude subscription instead of the API:
```bash
python3 scripts/automate_session.py --no-clean --local
```
Requires the `claude` CLI installed and logged in (`claude login`) to a
Pro/Max/Team plan. `--local` routes model calls through `claude -p` instead of
the Anthropic API, so usage is billed against your subscription instead of
metered tokens — even if `ANTHROPIC_API_KEY` is set in your shell, `--local`
explicitly ignores it for these calls so they don't silently bill the API
instead. Two things to know before using it a lot:
- **Shared usage pool**: subscription usage is the same pool your interactive
  Claude Code sessions draw from. A full recap run (several Haiku summary
  calls + one Sonnet generation call) can eat into that budget.
- **GitHub Actions is unaffected**: the workflow never passes `--local` and
  always uses the direct API key — this flag is for local runs only.

## GitHub Actions

The workflow runs automatically when:
- An SRT file is pushed to `transcripts_raw/`
- Manual workflow dispatch

It uses the `ANTHROPIC_API_KEY` secret configured in your GitHub repository
settings — always the direct API, regardless of local `--local` usage.

## Troubleshooting

### "anthropic package not installed"
```bash
pip install anthropic
```

### "ANTHROPIC_API_KEY not set"
```bash
export ANTHROPIC_API_KEY='your-key-here'
```

### Test the API connection
```bash
python3 scripts/test_api.py
```

## Cost Optimization Tips

1. **Haiku for Summaries**: Uses the cheapest model for intermediate work
2. **Campaign State**: Reduces need to read old sessions (was 5 full files, now 1 summary)
3. **Campaign State stays capped**: only the most recent ~20K chars of
   campaign-state.md are fed back into the state-update prompt, so per-session
   cost doesn't creep up as the campaign gets longer