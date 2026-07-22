#!/usr/bin/env python3
"""
Session Automation Script for Docusaurus D&D Campaign

This script automates the workflow of creating session notes from transcript files:
1. Finds the latest transcript in docs/transcripts/
2. Summarises long transcripts chunk-by-chunk (using Claude Haiku)
3. Creates a comprehensive session note using Claude Sonnet
4. Merges the new session's updates into the campaign-state.md running memory

Usage:
    python automate_session.py [--session-number N] [--interlude] [--no-clean] [--no-generate] [--timeout MIN] [--local]

Arguments:
    --session-number N : Specify session number (default: auto-detect next number)
    --interlude        : Create an interlude instead of a regular session
    --no-clean         : Skip transcript cleaning (use existing transcript)
    --no-generate      : Don't call the API (just save the prompt)
    --timeout MIN      : Timeout in minutes for API calls (default: 10)
    --local            : Route model calls through the local `claude` CLI, billed
                          against your Claude subscription (Pro/Max/Team), instead
                          of the metered Anthropic API. Intended for local runs;
                          GitHub Actions always uses the direct API regardless of
                          this flag, since CI has no interactive subscription login.
"""

import os
import sys
import subprocess
import argparse
import json
import tempfile
import time
from pathlib import Path
from datetime import datetime
import re

try:
    import anthropic
except ImportError:
    print("Error: anthropic package not installed. Run: pip install anthropic")
    sys.exit(1)


class CLIError(Exception):
    """Raised when the local `claude` CLI backend (--local) fails."""


# Both the direct-API and local-CLI backends accept these same model strings.
# --- Model configuration ---
# Haiku for cheap summarisation; Sonnet for creative recap generation.
SUMMARIZATION_MODEL = "claude-haiku-4-5-20251001"
GENERATION_MODEL = "claude-sonnet-5"

# Transcript size thresholds.
CHUNK_SIZE = 55_000       # Each chunk sent for summarisation.
MAX_DIRECT_CHARS = 60_000 # Transcripts below this are sent whole (no pre-summary).


class SessionAutomation:
    def __init__(self, project_root, use_local_cli=False):
        self.project_root = Path(project_root)
        self.raw_dir = self.project_root / "transcripts_raw"
        self.transcripts_dir = self.project_root / "docs" / "transcripts"
        self.sessions_dir = self.project_root / "docs" / "sessions"
        self.plugins_dir = self.project_root / "plugins"
        self.cleaner_script = self.plugins_dir / "transcript_cleaner_ai_optimized.py"
        self.use_local_cli = use_local_cli
        self.client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var (direct-API backend only)
        if self.use_local_cli:
            print("  Backend: local `claude` CLI — billed against your Claude subscription, not the API")
        else:
            print("  Backend: direct Anthropic API — billed per-token against ANTHROPIC_API_KEY")

    def find_latest_srt(self):
        """Find the most recent .srt file in transcripts_raw/"""
        if not self.raw_dir.exists():
            print(f"Error: transcripts_raw directory not found at {self.raw_dir}")
            return None
        srt_files = list(self.raw_dir.glob("*.srt"))
        if not srt_files:
            print(f"Error: No .srt files found in {self.raw_dir}")
            return None
        srt_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return srt_files[0]

    def run_transcript_cleaner(self, srt_file):
        """Run the transcript cleaner script on the SRT file"""
        print(f"Processing transcript: {srt_file.name}")
        print("Running transcript cleaner...")
        try:
            result = subprocess.run(
                ["python3", str(self.cleaner_script), str(srt_file)],
                capture_output=True, text=True, check=True
            )
            print(result.stdout)
            print("Transcript cleaned successfully")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error running transcript cleaner: {e}")
            print(e.stderr)
            return False

    def find_latest_transcript(self):
        """Find the most recently created transcript in docs/transcripts/"""
        if not self.transcripts_dir.exists():
            print(f"Error: transcripts directory not found at {self.transcripts_dir}")
            return None
        transcript_files = list(self.transcripts_dir.glob("*.md"))
        if not transcript_files:
            print(f"Error: No transcript files found in {self.transcripts_dir}")
            return None
        transcript_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return transcript_files[0]

    def get_next_session_number(self, is_interlude=False):
        """Determine the next session or interlude number"""
        if not self.sessions_dir.exists():
            return 1
        pattern = "interlude-*.md" if is_interlude else "session-*.md"
        prefix = "interlude" if is_interlude else "session"
        session_files = list(self.sessions_dir.glob(pattern))
        if not session_files:
            return 1
        numbers = []
        for f in session_files:
            match = re.search(rf"{prefix}-(\d+)\.md", f.name)
            if match:
                numbers.append(int(match.group(1)))
        return max(numbers) + 1 if numbers else 1

    def get_recent_sessions(self, count=5, exclude_filename=None):
        """Get the most recent session files for context.

        *exclude_filename* should be the filename of the session currently
        being generated. run_automation() writes a placeholder template for
        it before generation runs, which makes it the newest file by mtime —
        without excluding it here, it would displace a real prior session as
        a "recent session" style reference with its own empty scaffold.
        """
        if not self.sessions_dir.exists():
            return []
        session_files = list(self.sessions_dir.glob("session-*.md"))
        session_files.extend(list(self.sessions_dir.glob("interlude-*.md")))
        if exclude_filename:
            session_files = [f for f in session_files if f.name != exclude_filename]
        session_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return session_files[:count]

    def create_session_template(self, session_number, is_interlude, transcript_date):
        """Create a basic session template"""
        prefix = "Interlude" if is_interlude else ""
        title = f"{prefix}{' ' if prefix else ''}{session_number}"
        filename = f"{'interlude' if is_interlude else 'session'}-{session_number}.md"
        template = f"""---
title: "{title}: [Title To Be Generated]"
date: {transcript_date}
description: "[Description to be generated]"
summary: "[Summary to be generated]"
podcastlink: ""
---

***{transcript_date}***

## Players Present

[To be generated]

---

## Plot Events

[Content to be generated]

---
"""
        return filename, template

    # ------------------------------------------------------------------ #
    #  API helpers                                                         #
    # ------------------------------------------------------------------ #

    def _call_api(self, model, system, messages, max_tokens=4096, timeout=None):
        """Make a single Anthropic Messages API call.

        Note: we deliberately do NOT use prompt caching (cache_control)
        here. This script makes exactly one generation call per run, so
        there is never a second read to hit the cache within the 5-minute
        ephemeral TTL — caching would only add the ~25% cache-write
        premium with no offsetting discount. If a future batch mode
        processes multiple sessions in one process (reusing the same
        system prompt across calls), caching would be worth reintroducing.
        """
        kwargs = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            **kwargs,
        )
        return response.content[0].text

    def _call_cli(self, model, system, messages, timeout=None):
        """Run the prompt through the local `claude` CLI instead of the
        direct API, so usage is billed against a Claude subscription
        (Pro/Max/Team) rather than metered API tokens.

        Two things this depends on to actually bill the subscription
        instead of silently falling back to metered API pricing:
          - ANTHROPIC_API_KEY must be absent from the subprocess env — the
            CLI prefers it over a logged-in session whenever it's set.
          - We do NOT pass --bare: bare mode only supports API-key auth,
            not the OAuth/keychain session `claude login` sets up.
        Tool use is disabled (--tools "") so this behaves as a plain
        text-completion call, not an agentic coding session, and the
        subprocess cwd is a scratch temp dir (not the repo) so it doesn't
        pick up this project's CLAUDE.md as extra, uncounted context.
        """
        user_content = messages[0]["content"]

        env = os.environ.copy()
        if env.pop("ANTHROPIC_API_KEY", None):
            print("  (--local: ignoring ANTHROPIC_API_KEY for this call so it bills your subscription, not the API)")

        # `claude --help` (v2.1.217) only exposes --system-prompt <text>, not
        # a --system-prompt-file variant — pass it inline. Safe here: our
        # system prompts run tens of KB, well under the ~1MB ARG_MAX on this
        # machine (`getconf ARG_MAX`); re-check that if this ever runs on a
        # platform with a much lower argv limit (e.g. Windows' ~32K).
        cmd = [
            "claude", "-p",
            "--output-format", "text",
            "--model", model,
            "--tools", "",
            "--system-prompt", system,
        ]
        try:
            result = subprocess.run(
                cmd,
                input=user_content,
                capture_output=True,
                text=True,
                env=env,
                cwd=tempfile.gettempdir(),
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise CLIError(f"claude CLI timed out after {timeout}s")
        except FileNotFoundError:
            raise CLIError("`claude` CLI not found on PATH — install with: npm install -g @anthropic-ai/claude-code")

        if result.returncode != 0:
            raise CLIError(f"claude CLI exited {result.returncode}: {(result.stderr or '').strip()[:500]}")

        return result.stdout.strip()

    def _call_model(self, model, system, messages, max_tokens=4096, timeout=None):
        """Dispatch to the local CLI or the direct API depending on --local.

        All call sites should go through this rather than calling
        _call_api/_call_cli directly.
        """
        if self.use_local_cli:
            return self._call_cli(model, system, messages, timeout=timeout)
        return self._call_api(model, system, messages, max_tokens=max_tokens, timeout=timeout)

    def _summarize_chunk(self, chunk_text, chunk_num, total_chunks):
        """Summarise a single transcript chunk via Haiku."""
        prompt = f"""You are summarising chunk {chunk_num} of {total_chunks} from a D&D session transcript.

Extract and list in bullet-point form:
- Key plot events and story developments
- Important character actions and decisions
- Significant dialogue and memorable quotes
- New information, revelations, or lore
- Combat encounters and their outcomes

Be concise but thorough — every meaningful event should appear.
Do NOT invent anything not present in the transcript.

TRANSCRIPT CHUNK:
{chunk_text}"""
        return self._call_model(
            model=SUMMARIZATION_MODEL,
            system="You are a precise transcript summariser. Output only bullet points.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
            timeout=180,
        )

    def _summarize_long_transcript(self, text):
        """Split a large transcript into chunks and summarise each via Haiku."""
        chunks = [text[i:i + CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE)]
        print(f"  Transcript is {len(text):,} chars — summarising {len(chunks)} chunks via Haiku...")
        summaries = []
        for i, chunk in enumerate(chunks, 1):
            print(f"  Summarising chunk {i}/{len(chunks)} ({len(chunk):,} chars)...")
            try:
                summary = self._summarize_chunk(chunk, i, len(chunks))
            except (anthropic.APIError, CLIError) as e:
                print(f"  Warning: chunk {i} summarisation failed ({e}); using a placeholder so later chunks aren't lost")
                summary = f"[Chunk {i} summarisation failed: {e}]"
            if summary:
                summaries.append(f"--- CHUNK {i}/{len(chunks)} SUMMARY ---\n{summary}")
            # Small pause between chunks to avoid rate limits.
            if i < len(chunks):
                time.sleep(2)
        combined = "\n\n".join(summaries)
        print(f"  Combined summaries: {len(combined):,} chars (down from {len(text):,})")
        return combined

    # ------------------------------------------------------------------ #
    #  Prompt construction                                                 #
    # ------------------------------------------------------------------ #

    def _load_file(self, path):
        """Read a file and return its contents, or empty string on error."""
        try:
            return Path(path).read_text(encoding="utf-8")
        except Exception as e:
            print(f"  Warning: could not read {path}: {e}")
            return ""

    def build_system_prompt(self, exclude_filename=None):
        """Build the system prompt."""
        kb_content = self._load_file(self.project_root / "data" / "campaign-kb.md")
        state_content = self._load_file(self.project_root / "data" / "campaign-state.md")

        # Load 1-2 recent sessions as style reference (full text).
        recent = self.get_recent_sessions(2, exclude_filename=exclude_filename)
        style_refs = []
        for s in recent:
            content = self._load_file(s)
            if content:
                style_refs.append(f"### {s.name}\n\n{content[:8000]}")  # First 8K chars for style

        style_section = "\n\n---\n\n".join(style_refs) if style_refs else "(no previous sessions available)"

        return f"""You are an expert D&D session recap writer. You create engaging, detailed session notes for a campaign called "Moonfall Sessions."

## Your Task
Write a comprehensive session recap based on a transcript of the session. The recap should be written in third person, past tense, capturing the narrative flow, character development, and key plot points.

## Format
Follow this exact structure:
1. YAML frontmatter with title, date, description, summary, podcastlink
2. Date header (e.g. ***July 17, 2026***)
3. Players Present section
4. Plot Events section with ### subheadings
5. Notable Character Moments section
6. Themes section
7. Session MVP section

## Campaign Knowledge Base (CRITICAL - use these names):
{kb_content}

## Campaign State & Running Memory:
{state_content}

## Style Reference (from recent sessions):
{style_section}

## Character Name Rules (MUST follow):
- Bru is ALWAYS "Bru", NEVER "Brew"
- Elspeth is ALWAYS "Elspeth", NEVER "Ellsworth" or "Elizabeth"
- Leliana is ALWAYS "Leliana", NEVER "Liliana"
- Eldoran is ALWAYS "Eldoran", NEVER "Elderan"
- Greyport is ALWAYS "Greyport", NEVER "Grayport"
- Astro is ALWAYS "Astro", NEVER "Astra"

## Writing Guidelines:
- Use concrete details from the transcript only. Do NOT invent events, characters, or locations.
- Include memorable quotes in blockquote format (> "quote" — Speaker)
- Capture combat mechanics (rolls, damage) when they add drama
- Highlight character growth and relationship moments
- End with a Session MVP choice
- Make callbacks to previous sessions where the transcript references them
- Write for readers who know the campaign but want to relive the session"""

    def build_generation_prompt(self, transcript_content, session_number, is_interlude, dry_run=False):
        """Build the user-facing prompt for recap generation.

        *dry_run* skips the Haiku summarisation call (which costs real
        money) and substitutes a truncated preview instead — used by
        --no-generate, which is documented/advertised as a free, no-API-call
        path and should stay that way regardless of transcript size.
        """
        prefix = "interlude" if is_interlude else "session"
        session_type = "interlude" if is_interlude else "session"

        # If transcript is too large, summarise first.
        if len(transcript_content) > MAX_DIRECT_CHARS:
            if dry_run:
                transcript_content = (
                    f"[DRY RUN: transcript is {len(transcript_content):,} chars — "
                    f"would be summarised via Haiku in a real run. Showing first "
                    f"{MAX_DIRECT_CHARS:,} chars as a preview.]\n\n"
                    + transcript_content[:MAX_DIRECT_CHARS]
                )
            else:
                transcript_content = self._summarize_long_transcript(transcript_content)
            transcript_label = "TRANSCRIPT SUMMARY (condensed from full transcript):"
        else:
            transcript_label = "TRANSCRIPT CONTENT:"

        return f"""Create a detailed {session_type} note for {session_type} {session_number}.

Write the file to: docs/sessions/{prefix}-{session_number}.md

{transcript_label}

{transcript_content}"""

    # ------------------------------------------------------------------ #
    #  Campaign state updater                                              #
    # ------------------------------------------------------------------ #

    # Maps each labeled part of the Haiku response to the top-level
    # "## " section of campaign-state.md it actually belongs in.
    _STATE_UPDATE_SECTIONS = {
        "SESSION SUMMARY ENTRY": ("Session Event Index", None),
        "PLOT THREAD UPDATES": ("Active Plot Threads", "no changes"),
        "CHARACTER UPDATES": ("Character Status", "no changes"),
        "NEW CALLBACKS/HOOKS": ("Key Callbacks & Unresolved Hooks", "no new hooks"),
    }

    # Cap on how much of the existing state doc gets fed back into the
    # update prompt. The Session Event Index only grows a few lines per
    # session, but this keeps a runaway document from silently inflating
    # every future call's input cost.
    MAX_STATE_CONTEXT_CHARS = 20_000

    def _parse_state_update(self, result_text):
        """Split Haiku's four labeled sections out of its response."""
        pattern = re.compile(
            r"^### (" + "|".join(re.escape(k) for k in self._STATE_UPDATE_SECTIONS) + r")\s*$",
            re.MULTILINE,
        )
        matches = list(pattern.finditer(result_text))
        parts = {}
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(result_text)
            parts[m.group(1)] = result_text[start:end].strip()
        return parts

    def _insert_into_section(self, content, heading, text):
        """Insert *text* at the end of the top-level "## {heading}" section.

        Falls back to creating the section at the end of the document if
        it doesn't exist (defensive; every section should already exist
        in a well-formed campaign-state.md).
        """
        heading_line = f"## {heading}"
        lines = content.split("\n")
        start_idx = next((i for i, l in enumerate(lines) if l.strip() == heading_line), None)

        if start_idx is None:
            return content.rstrip("\n") + f"\n\n{heading_line}\n\n{text}\n"

        end_idx = len(lines)
        for i in range(start_idx + 1, len(lines)):
            if lines[i].startswith("## "):
                end_idx = i
                break
        lines[end_idx:end_idx] = ["", text, ""]
        return "\n".join(lines)

    def update_campaign_state(self, session_number, recap_text):
        """Merge a new session's updates into data/campaign-state.md.

        Each part of the model's response is inserted into the section of
        the document it actually describes, rather than dumped as one
        undifferentiated blob — otherwise Active Plot Threads and
        Character Status silently go stale while every update piles up
        in one place, defeating the point of a curated running memory.
        """
        state_path = self.project_root / "data" / "campaign-state.md"
        current = self._load_file(state_path)
        state_for_prompt = current[-self.MAX_STATE_CONTEXT_CHARS:]

        prompt = f"""You are updating a running campaign state document for a D&D campaign called "Moonfall Sessions."

Given the following session recap, extract:
1. A 2-4 line summary for the Session Event Index
2. Any updates to Active Plot Threads (add new ones, update status of existing ones)
3. Any changes to Character Status
4. Any new callback opportunities or unresolved hooks

SESSION {session_number} RECAP:
{recap_text[:12000]}

CURRENT CAMPAIGN STATE (may be truncated to the most recent portion):
{state_for_prompt}

Respond in this EXACT format (no other text):

### SESSION SUMMARY ENTRY
**Session {session_number}** – [Title]
[2-4 sentence summary]

### PLOT THREAD UPDATES
[bullet list of changes, or "No changes" if none]

### CHARACTER UPDATES
[bullet list of changes, or "No changes" if none]

### NEW CALLBACKS/HOOKS
[bullet list, or "No new hooks" if none]"""

        try:
            result = self._call_model(
                model=SUMMARIZATION_MODEL,
                system="You are a precise campaign historian. Output only the requested sections.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
                timeout=180,
            )
        except (anthropic.APIError, CLIError) as e:
            print(f"  Warning: campaign state update call failed ({e}); state left unchanged")
            return

        parts = self._parse_state_update(result)
        if not parts:
            print("  Warning: could not parse state update response; appending raw output at end of file")
            with open(state_path, "a", encoding="utf-8") as f:
                f.write(f"\n\n{result}\n")
            return

        updated = current
        for label, (heading, skip_phrase) in self._STATE_UPDATE_SECTIONS.items():
            text = parts.get(label)
            if not text:
                continue
            if skip_phrase and skip_phrase in text.lower():
                continue
            if label != "SESSION SUMMARY ENTRY":
                text = f"#### Session {session_number} Updates\n{text}"
            updated = self._insert_into_section(updated, heading, text)

        state_path.write_text(updated, encoding="utf-8")
        print(f"  Campaign state updated with session {session_number}")

    # ------------------------------------------------------------------ #
    #  Main generation flow                                                #
    # ------------------------------------------------------------------ #

    def generate_recap(self, transcript_path, session_number, is_interlude, timeout_minutes=10):
        """Generate the session recap using the Anthropic API."""
        print("\n" + "=" * 60)
        print("GENERATING SESSION RECAP")
        print("=" * 60)

        # Load transcript.
        print(f"Reading transcript from {transcript_path}...")
        transcript_content = self._load_file(transcript_path)
        if not transcript_content:
            print("Error: could not read transcript")
            return False
        print(f"  Transcript loaded ({len(transcript_content):,} chars)")

        # Build prompts. Exclude this session's own (still-placeholder) file
        # from the style-reference lookup — see get_recent_sessions().
        own_filename = f"{'interlude' if is_interlude else 'session'}-{session_number}.md"
        system_prompt = self.build_system_prompt(exclude_filename=own_filename)
        user_prompt = self.build_generation_prompt(transcript_content, session_number, is_interlude)

        print(f"  System prompt: {len(system_prompt):,} chars")
        print(f"  User prompt: {len(user_prompt):,} chars")

        # Save prompt for debugging.
        prompt_file = self.project_root / "scripts" / "last_claude_prompt.txt"
        prompt_file.write_text(f"SYSTEM:\n{system_prompt}\n\nUSER:\n{user_prompt}", encoding="utf-8")
        print(f"  Prompt saved to {prompt_file}")

        backend = "local claude CLI" if self.use_local_cli else GENERATION_MODEL
        print(f"\n  Calling {backend} (timeout {timeout_minutes} min)...")
        start_time = time.time()
        try:
            recap_text = self._call_model(
                model=GENERATION_MODEL,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=8192,
                timeout=timeout_minutes * 60,
            )
            elapsed = time.time() - start_time
            print(f"  Generation complete ({elapsed:.1f}s, {len(recap_text):,} chars)")
        except anthropic.APITimeoutError:
            print(f"  Error: API call timed out after {timeout_minutes} minutes")
            return False
        except (anthropic.APIError, CLIError) as e:
            print(f"  Error: generation call failed: {e}")
            return False

        # Write the recap file.
        filename = own_filename
        session_path = self.sessions_dir / filename
        session_path.write_text(recap_text, encoding="utf-8")
        print(f"  Recap written to {session_path}")

        # Update campaign state.
        print("\n  Updating campaign state...")
        self.update_campaign_state(session_number, recap_text)

        return True

    # ------------------------------------------------------------------ #
    #  Orchestration                                                       #
    # ------------------------------------------------------------------ #

    def run_automation(self, session_number=None, is_interlude=False,
                       skip_cleaning=False, invoke_api=True, timeout_minutes=10):
        """Run the full automation workflow."""
        print("=" * 60)
        print("Session Automation Workflow")
        print("=" * 60)

        srt_file = None
        if not skip_cleaning:
            print("\n[Step 1/3] Finding and cleaning transcript...")
            srt_file = self.find_latest_srt()
            if not srt_file:
                return False
            if not self.run_transcript_cleaner(srt_file):
                return False
        else:
            print("\n[Step 1/3] Skipping transcript cleaning...")

        print("\n[Step 2/3] Finding latest transcript...")
        latest_transcript = self.find_latest_transcript()
        if not latest_transcript:
            return False
        print(f"  Found transcript: {latest_transcript.name}")

        try:
            transcript_date = latest_transcript.stem
            datetime.strptime(transcript_date, "%Y-%m-%d")
        except ValueError:
            transcript_date = datetime.now().strftime("%Y-%m-%d")
            print(f"  Could not parse date from filename, using today: {transcript_date}")

        if session_number is None:
            session_number = self.get_next_session_number(is_interlude)

        print(f"\n[Step 3/3] Creating {'interlude' if is_interlude else 'session'} {session_number}...")

        # Create template file.
        filename, template = self.create_session_template(session_number, is_interlude, transcript_date)
        session_path = self.sessions_dir / filename
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        session_path.write_text(template, encoding="utf-8")

        if invoke_api:
            success = self.generate_recap(latest_transcript, session_number, is_interlude, timeout_minutes)
            if success and srt_file and srt_file.exists():
                try:
                    srt_file.unlink()
                    print(f"\n  Deleted original SRT: {srt_file.name}")
                except Exception as e:
                    print(f"  Could not delete {srt_file.name}: {e}")
            return success
        else:
            # Just save the prompt without calling API.
            transcript_content = self._load_file(latest_transcript)
            user_prompt = self.build_generation_prompt(transcript_content, session_number, is_interlude, dry_run=True)
            system_prompt = self.build_system_prompt(exclude_filename=filename)
            prompt_file = self.project_root / "scripts" / "last_claude_prompt.txt"
            prompt_file.write_text(f"SYSTEM:\n{system_prompt}\n\nUSER:\n{user_prompt}", encoding="utf-8")
            print(f"\n  Prompt saved to {prompt_file}")
            print("  Skipping API call (use without --no-generate to auto-generate)")
            return True


def main():
    parser = argparse.ArgumentParser(
        description="Automate D&D session note creation from transcripts"
    )
    parser.add_argument("--session-number", type=int, help="Session number (default: auto-detect)")
    parser.add_argument("--interlude", action="store_true", help="Create an interlude instead")
    parser.add_argument("--no-clean", action="store_true", help="Skip transcript cleaning")
    parser.add_argument("--no-generate", action="store_true", help="Don't call API (just save prompt)")
    parser.add_argument("--timeout", type=int, default=10, help="API timeout in minutes (default: 10)")
    parser.add_argument(
        "--local", action="store_true",
        help="Route model calls through the local `claude` CLI (billed against your "
             "Claude subscription) instead of the metered Anthropic API. For local runs "
             "only — the GitHub Actions workflow always uses the direct API."
    )
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    automation = SessionAutomation(project_root, use_local_cli=args.local)
    success = automation.run_automation(
        session_number=args.session_number,
        is_interlude=args.interlude,
        skip_cleaning=args.no_clean,
        invoke_api=not args.no_generate,
        timeout_minutes=args.timeout,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
