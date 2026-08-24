#!/usr/bin/env python3
"""
Session Automation Script for Docusaurus D&D Campaign

This script automates the workflow of creating session notes from transcript files:
1. Finds the latest transcript in docs/transcripts/
2. Summarises long transcripts chunk-by-chunk (using Claude Haiku)
3. Creates a comprehensive session note using Claude Sonnet
4. Merges the new session's updates into the campaign-state.md running memory
5. Updates the session-stats dataset (personality analysis + stats extraction)

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

# Local module; resolve it relative to this file so the script works from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from recap_postprocess import (  # noqa: E402  (local module)
    get_frontmatter_value,
    postprocess_recap,
)

try:
    import anthropic
except ImportError:
    print("Error: anthropic package not installed. Run: pip install anthropic")
    sys.exit(1)


class CLIError(Exception):
    """Raised when the local `claude` CLI backend (--local) fails."""


class EmptyResponseError(Exception):
    """Raised when a model returns no usable text (e.g. a refusal, or a
    response that is thinking blocks only)."""


# Both the direct-API and local-CLI backends accept these same model strings.
# --- Model configuration ---
# Haiku for cheap summarisation; Sonnet for creative recap generation.
SUMMARIZATION_MODEL = "claude-haiku-4-5-20251001"
GENERATION_MODEL = "claude-sonnet-5"

# Transcript size thresholds.
CHUNK_SIZE = 55_000       # Each chunk sent for summarisation.
MAX_DIRECT_CHARS = 60_000 # Transcripts below this are sent whole (no pre-summary).

# Returned by run_automation() when no new .srt is waiting to be processed.
# This is a no-op, not a failure: the generator consumes (deletes) each SRT it
# processes, so an empty transcripts_raw/ is the normal resting state. A re-run
# in that state has nothing to generate but must still exit 0, so the workflow
# goes on to build and deploy whatever is already committed.
NOTHING_TO_DO = "nothing-to-do"


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
        """Find the most recent .srt file in transcripts_raw/.

        Returns None when nothing is waiting — either because the directory is
        absent or because it holds no .srt files. Neither is an error: the
        generator deletes each SRT once processed, so both states just mean
        there is no new transcript to turn into a recap.
        """
        if not self.raw_dir.exists():
            print(f"  No transcripts_raw directory at {self.raw_dir}")
            return None
        srt_files = list(self.raw_dir.glob("*.srt"))
        if not srt_files:
            print(f"  No .srt files waiting in {self.raw_dir}")
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

    def run_stats_extractor(self, transcript_date, include_llm=True):
        """Update the session-stats dataset for this session (non-fatal).

        Runs the LLM personality analyzer for the new session's date, then
        rebuilds data/session-stats.json + static/data/session-stats.csv.
        Failures are warnings only — stats should never block recap creation.
        Pass include_llm=False to skip the model call (e.g. --no-generate runs).
        """
        print("\nUpdating session stats dataset...")
        scripts_dir = self.project_root / "scripts"
        steps = []
        if include_llm:
            analyzer_cmd = ["python3", str(scripts_dir / "analyze_session_personality.py"),
                            "--date", transcript_date]
            if self.use_local_cli:
                analyzer_cmd.append("--local")
            steps.append(("personality analysis", analyzer_cmd))
        steps.append(
            ("stats extraction", ["python3", str(scripts_dir / "extract_session_stats.py"),
                                  "--date", transcript_date]))
        for name, cmd in steps:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
                if result.returncode != 0:
                    print(f"  Warning: {name} failed (non-fatal):")
                    print((result.stderr or result.stdout or "").strip()[:500])
                else:
                    print(f"  {name} complete")
            except (subprocess.TimeoutExpired, OSError) as e:
                print(f"  Warning: {name} failed (non-fatal): {e}")

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

    @staticmethod
    def date_from_transcript(transcript_path):
        """Session date from the transcript filename (YYYY-MM-DD.md).

        This is the only trustworthy record of when a session happened, and
        extract_session_stats.py joins recaps to transcripts on it. Falls back
        to today only when a transcript is named something unexpected.
        """
        stem = Path(transcript_path).stem
        try:
            datetime.strptime(stem, "%Y-%m-%d")
            return stem
        except ValueError:
            today = datetime.now().strftime("%Y-%m-%d")
            print(f"  Could not parse date from filename {stem!r}, using today: {today}")
            return today

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

    def read_existing_podcast_link(self, filename):
        """Return the podcastlink already on this session's page, if any.

        run_automation() overwrites the page with a fresh template before
        generating, so a link a human pasted in earlier would otherwise be
        lost on a regeneration — and the model would happily invent a
        replacement (see _apply_generation_guardrails).
        """
        path = self.sessions_dir / filename
        if not path.exists():
            return ""
        return get_frontmatter_value(path.read_text(encoding="utf-8"), "podcastlink") or ""

    def create_session_template(self, session_number, is_interlude, transcript_date,
                                podcast_link=""):
        """Create a basic session template"""
        prefix = "Interlude" if is_interlude else ""
        title = f"{prefix}{' ' if prefix else ''}{session_number}"
        filename = f"{'interlude' if is_interlude else 'session'}-{session_number}.md"
        template = f"""---
title: "{title}: [Title To Be Generated]"
date: {transcript_date}
description: "[Description to be generated]"
summary: "[Summary to be generated]"
podcastlink: "{podcast_link}"
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
        return self._extract_text(response, model)

    @staticmethod
    def _extract_text(response, model):
        """Pull the assistant's text out of a Messages API response.

        `response.content` is a list of blocks, and text is not guaranteed to
        be first: models with adaptive thinking on by default (Sonnet 5 and
        the rest of the 5 family) put a thinking block at index 0, so
        `content[0].text` raises AttributeError. Concatenate every text block
        instead and ignore the rest.
        """
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text.strip():
            raise EmptyResponseError(
                f"{model} returned no text (stop_reason={response.stop_reason}, "
                f"blocks={[b.type for b in response.content]})"
            )
        if response.stop_reason == "max_tokens":
            print(f"  Warning: {model} hit max_tokens — output is truncated")
        return text

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
            except (anthropic.APIError, CLIError, EmptyResponseError) as e:
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

    def resolve_publication_context(self, session_number, is_interlude=False):
        """Resolve the publication meta-narrative context for a session.

        Reads data/publication-arc.json and returns a dict describing the
        authoring persona, storyline beat, and voice directives for this
        session — or None when the config is missing/invalid or the
        session predates the first beat, in which case generation behaves
        exactly as it did before the persona layer existed.

        Interludes have their own numbering sequence, so they inherit the
        beat of the campaign's latest real session and always use the
        beat's primary author (they never advance a rotation).
        """
        arc_path = self.project_root / "data" / "publication-arc.json"
        try:
            arc = json.loads(arc_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"  Warning: could not load {arc_path.name} ({e}); persona layer disabled")
            return None

        personas = arc.get("personas", {})
        dm_notes = (arc.get("notes") or "").strip()

        def _ctx(beat_id, author_id, co_author_id, directive, editorial_notes,
                 crush_level=None, anonymous=False):
            author = personas.get(author_id or "")
            if not author:
                print(f"  Warning: persona '{author_id}' not found in publication-arc.json; persona layer disabled")
                return None
            co_author = personas.get(co_author_id or "") if co_author_id else None
            crush_text = ""
            if crush_level is not None:
                crush_text = (author.get("quirks", {})
                              .get("silasCrush", {})
                              .get(str(crush_level), ""))
            byline = author.get("byline", author.get("name", ""))
            if anonymous:
                byline = "The masthead declines to state who compiled this account."
            return {
                "beat_id": beat_id,
                "publication": arc.get("publication", {}).get("name", "the publication"),
                "author_name": author.get("name", ""),
                "author_voice": author.get("voice", ""),
                "byline": byline,
                "signature": author.get("signature", ""),
                "co_author_name": co_author.get("name", "") if co_author else "",
                "co_author_voice": co_author.get("voice", "") if co_author else "",
                "co_signature": co_author.get("signature", "") if co_author else "",
                "directive": directive,
                "editorial_notes": editorial_notes,
                "crush_text": crush_text,
                "dm_notes": dm_notes,
            }

        finale = arc.get("finale", {})
        if finale.get("active"):
            directive = finale.get("directive", "")
            finale_notes = (finale.get("notes") or "").strip()
            if finale_notes:
                directive = f"{directive}\n\nDM NOTES ON THE RESOLUTION: {finale_notes}"
            return _ctx("finale", finale.get("author"), None, directive, "")

        # Beats auto-advance by session count: active beat = last beat whose
        # startSession has been reached. The final beat has no end — only
        # finale.active (flipped manually by the DM) ever supersedes it.
        beat_session = session_number
        if is_interlude:
            beat_session = self.get_next_session_number(False) - 1
        active = None
        for beat in sorted(arc.get("beats", []), key=lambda b: b.get("startSession", 0)):
            if beat_session >= beat.get("startSession", 0):
                active = beat
        if active is None:
            return None  # Pre-arc session: persona layer off.

        directive = active.get("directive", "")
        author_id = active.get("author")
        co_author_id = active.get("coAuthor")
        anonymous = False
        if active.get("authorRule") == "rotation":
            rotation = active.get("rotation", [])
            if not rotation:
                print("  Warning: rotation beat has no rotation entries; persona layer disabled")
                return None
            if is_interlude:
                entry = rotation[0]
            else:
                entry = rotation[(beat_session - active.get("startSession", 0)) % len(rotation)]
            author_id = entry.get("author")
            co_author_id = entry.get("coAuthor")
            anonymous = bool(entry.get("anonymous"))
            if entry.get("directive"):
                directive = f"{directive}\n\nTHIS SESSION'S CONTROL STATE: {entry['directive']}"

        return _ctx(active.get("id", "?"), author_id, co_author_id, directive,
                    active.get("editorialNotes", ""),
                    crush_level=active.get("crushLevel"), anonymous=anonymous)

    def build_system_prompt(self, exclude_filename=None, persona_ctx=None):
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

        # Persona layer (publication meta-narrative). When active, the recap
        # is written in-character by a fictional staff writer, the recent
        # sessions become structure-only references (their voice may belong
        # to a different author), and the byline/editorial-note conventions
        # are added to the format contract.
        if persona_ctx:
            style_heading = "## Structure Reference (from recent sessions)"
            style_caveat = ("\nThese show structure, section order, and factual style ONLY. "
                            "Their narrative voice may belong to a different author — the "
                            "Author Persona section below OVERRIDES the exemplar voice.\n")
            byline_format_item = "3. Byline line immediately after the date header (exact text given in the Author Persona section)\n"
            format_offset = 1
            editorial_format_item = "\n9. Editorial notes as specified in the Author Persona section"
            persona_section = self._build_persona_section(persona_ctx)
        else:
            style_heading = "## Style Reference (from recent sessions):"
            style_caveat = ""
            byline_format_item = ""
            format_offset = 0
            editorial_format_item = ""
            persona_section = ""

        return f"""You are an expert D&D session recap writer. You create engaging, detailed session notes for a campaign called "Moonfall Sessions."

## Your Task
Write a comprehensive session recap based on a transcript of the session. The recap should be written in third person, past tense, capturing the narrative flow, character development, and key plot points.

## Format
Follow this exact structure:
1. YAML frontmatter with title, date, description, summary, podcastlink
2. Date header (e.g. ***July 17, 2026***)
{byline_format_item}{3 + format_offset}. Players Present section
{4 + format_offset}. Plot Events section with ### subheadings
{5 + format_offset}. Notable Character Moments section
{6 + format_offset}. Themes section
{7 + format_offset}. Session MVP section{editorial_format_item}

## Campaign Knowledge Base (CRITICAL - use these names):
{kb_content}

## Campaign State & Running Memory:
{state_content}

{style_heading}
{style_caveat}{style_section}

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
- Write for readers who know the campaign but want to relive the session{persona_section}"""

    @staticmethod
    def _build_persona_section(ctx):
        """Render the Author Persona prompt section from a resolved context."""
        co_author_block = ""
        if ctx["co_author_name"]:
            co_author_block = (f"\nCO-PERSONA: {ctx['co_author_name']} (signature {ctx['co_signature']})\n"
                               f"Voice: {ctx['co_author_voice']}\n")
        crush_block = ""
        if ctx["crush_text"]:
            crush_block = f"\nQUIRK — the Archive's coverage of Silas Fairbanks: {ctx['crush_text']}\n"
        dm_block = ""
        if ctx["dm_notes"]:
            dm_block = f"\nDM DIRECTIVE FOR THIS SESSION (one-off, follow it): {ctx['dm_notes']}\n"
        return f"""

## Author Persona & Publication Storyline (CRITICAL)
This recap appears in "{ctx['publication']}", the in-world publication behind these
session notes. It is written in-character by a fictional staff writer. The persona
layer affects VOICE, the byline, and editorial notes ONLY — never invent, omit, or
distort actual session events, and never let the meta-narrative displace the recap
itself. The session's story always comes first; the publication's story lives in the
margins.

CURRENT AUTHOR: {ctx['author_name']} (signature {ctx['signature']})
Voice: {ctx['author_voice']}
{co_author_block}
STORYLINE BEAT ({ctx['beat_id']}): {ctx['directive']}
{crush_block}
BYLINE: the line immediately after the ***Date*** line must be exactly:
*{ctx['byline']}*

EDITORIAL NOTES CONVENTION: {ctx['editorial_notes'] or 'None this session.'}
Editorial notes are italic blockquotes placed between narrative sections, each ending
with the writer's signature, e.g.:
> *One notes the author's fondness for cataloguing what could simply be felt. — P.A.*
Notes comment on the WRITING and on each other — they never contradict or alter the
recorded events themselves.{dm_block}"""

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

Ignore any byline, editor's note, or publication-meta content in the recap (the notes
are framed as an in-world publication with fictional staff writers) — record only
in-world campaign events.

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
        except (anthropic.APIError, CLIError, EmptyResponseError) as e:
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

    @staticmethod
    def _strip_code_fence(text):
        """Unwrap model output enclosed in a markdown code fence.

        The local `claude` CLI backend sometimes wraps the entire recap in
        ```markdown ... ```, which would ship a broken page and defeats
        frontmatter detection in _apply_publication_metadata().
        """
        m = re.match(r"^\s*```[\w-]*\n(.*?)\n?```\s*$", text, re.S)
        return m.group(1) + "\n" if m else text

    def _apply_publication_metadata(self, recap_text, persona_ctx):
        """Deterministically stamp persona metadata onto a generated recap.

        The model writes the whole file, frontmatter included, and cannot be
        trusted to emit every requested key (session 57 dropped
        `podcastlink` despite instructions). So the prompt *asks* for the
        byline and this post-processor *guarantees* it, along with
        `author:`/`beat:` frontmatter keys. No-op when the persona layer is
        off.
        """
        if not persona_ctx:
            return recap_text

        # Frontmatter: replace any model-emitted author/beat keys with the
        # authoritative values from the resolved context.
        fm_match = re.match(r"^---\n(.*?\n)---", recap_text, re.S)
        if fm_match:
            fm = fm_match.group(1)
            fm = re.sub(r"^(author|beat):.*\n", "", fm, flags=re.M)
            fm += f'author: "{persona_ctx["author_name"]}"\nbeat: "{persona_ctx["beat_id"]}"\n'
            recap_text = f"---\n{fm}---" + recap_text[fm_match.end():]
        else:
            print("  Warning: no frontmatter block found; author/beat keys not injected")

        # Byline: if the line after the first ***date*** line isn't the
        # expected byline, insert it.
        byline_line = f"*{persona_ctx['byline']}*"
        if byline_line not in recap_text:
            lines = recap_text.split("\n")
            for i, line in enumerate(lines):
                if re.match(r"^\*\*\*.+\*\*\*\s*$", line):
                    lines.insert(i + 1, f"\n{byline_line}")
                    recap_text = "\n".join(lines)
                    print(f"  Byline inserted after date header ({persona_ctx['author_name']})")
                    break
            else:
                print("  Warning: no ***date*** line found; byline not inserted")

        return recap_text

    def _apply_generation_guardrails(self, recap_text, transcript_date, podcast_link,
                                     is_interlude=False):
        """Repair what the model cannot know, then validate what it wrote.

        The model authors the whole file, frontmatter included, so it has been
        filling in facts it has no access to: sessions 58 and 59 both dated
        themselves wrongly and both invented a Spotify episode URL, and 59
        printed "Brew" and a Google Meet handle despite the prompt's name
        rules. Each one shipped and needed a hand-written repair commit.

        So the date, the display date header, the podcast link, the canonical
        names, and internal links are all fixed here instead of asked for —
        and anything structural that cannot be repaired (missing frontmatter,
        no Players Present section, leftover template placeholders) is returned
        for the caller to fail the run on. Returns (recap_text, problems).
        """
        recap_text, notes, problems = postprocess_recap(
            recap_text,
            transcript_date=transcript_date,
            podcast_link=podcast_link,
            kb_path=self.project_root / "data" / "campaign-kb.md",
            docs_dir=self.project_root / "docs",
            is_interlude=is_interlude,
        )
        if notes:
            print("  Guardrails applied:")
            for note in notes:
                print(f"    - {note}")
        else:
            print("  Guardrails: nothing to correct")
        return recap_text, problems

    def generate_recap(self, transcript_path, session_number, is_interlude, timeout_minutes=10,
                       transcript_date=None, podcast_link=""):
        """Generate the session recap using the Anthropic API."""
        print("\n" + "=" * 60)
        print("GENERATING SESSION RECAP")
        print("=" * 60)

        # The transcript filename is the authoritative session date; fall back
        # to it when the caller did not pass one through.
        if transcript_date is None:
            transcript_date = self.date_from_transcript(Path(transcript_path))

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
        persona_ctx = self.resolve_publication_context(session_number, is_interlude)
        if persona_ctx:
            print(f"  Publication beat: {persona_ctx['beat_id']} — author: {persona_ctx['author_name']}")
        system_prompt = self.build_system_prompt(exclude_filename=own_filename, persona_ctx=persona_ctx)
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
                # Headroom: max_tokens caps thinking + response text together,
                # and Sonnet 5 thinks by default, so the old 8192 left the
                # recap itself at risk of truncation.
                max_tokens=16000,
                timeout=timeout_minutes * 60,
            )
            elapsed = time.time() - start_time
            print(f"  Generation complete ({elapsed:.1f}s, {len(recap_text):,} chars)")
        except anthropic.APITimeoutError:
            print(f"  Error: API call timed out after {timeout_minutes} minutes")
            return False
        except (anthropic.APIError, CLIError, EmptyResponseError) as e:
            print(f"  Error: generation call failed: {e}")
            return False

        # Unwrap any code fence, repair the fields the model cannot know, then
        # stamp persona metadata (author/beat frontmatter, byline fallback).
        # Guardrails run first: they guarantee the ***date*** header the byline
        # is inserted after.
        recap_text = self._strip_code_fence(recap_text)
        recap_text, problems = self._apply_generation_guardrails(
            recap_text, transcript_date, podcast_link, is_interlude=is_interlude)
        recap_text = self._apply_publication_metadata(recap_text, persona_ctx)

        # Write the recap file (even when invalid, so the output can be read).
        filename = own_filename
        session_path = self.sessions_dir / filename
        session_path.write_text(recap_text, encoding="utf-8")
        print(f"  Recap written to {session_path}")

        if problems:
            print("\n  ERROR: the generated recap failed validation:")
            for problem in problems:
                print(f"    - {problem}")
            print(f"  {session_path.name} was written for inspection, but the run is "
                  "failing rather than publishing it — the transcript stays queued "
                  "so a re-run picks it up.")
            return False

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
                print("\nNothing to generate: no new .srt transcript is waiting.")
                print("  Drop one in transcripts_raw/ to create a recap, or pass "
                      "--no-clean to regenerate from the existing cleaned transcript.")
                return NOTHING_TO_DO
            if not self.run_transcript_cleaner(srt_file):
                return False
        else:
            print("\n[Step 1/3] Skipping transcript cleaning...")

        print("\n[Step 2/3] Finding latest transcript...")
        latest_transcript = self.find_latest_transcript()
        if not latest_transcript:
            return False
        print(f"  Found transcript: {latest_transcript.name}")

        transcript_date = self.date_from_transcript(latest_transcript)

        if session_number is None:
            session_number = self.get_next_session_number(is_interlude)

        print(f"\n[Step 3/3] Creating {'interlude' if is_interlude else 'session'} {session_number}...")

        # Create template file, carrying over any podcast link already on the
        # page so a regeneration does not drop one a human pasted in.
        preset_filename = f"{'interlude' if is_interlude else 'session'}-{session_number}.md"
        podcast_link = self.read_existing_podcast_link(preset_filename)
        filename, template = self.create_session_template(
            session_number, is_interlude, transcript_date, podcast_link=podcast_link)
        session_path = self.sessions_dir / filename
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        session_path.write_text(template, encoding="utf-8")

        if invoke_api:
            success = self.generate_recap(latest_transcript, session_number, is_interlude,
                                          timeout_minutes, transcript_date=transcript_date,
                                          podcast_link=podcast_link)
            if success and srt_file and srt_file.exists():
                try:
                    srt_file.unlink()
                    print(f"\n  Deleted original SRT: {srt_file.name}")
                except Exception as e:
                    print(f"  Could not delete {srt_file.name}: {e}")
            if success:
                self.run_stats_extractor(transcript_date)
            return success
        else:
            # Just save the prompt without calling API.
            transcript_content = self._load_file(latest_transcript)
            user_prompt = self.build_generation_prompt(transcript_content, session_number, is_interlude, dry_run=True)
            persona_ctx = self.resolve_publication_context(session_number, is_interlude)
            if persona_ctx:
                print(f"  Publication beat: {persona_ctx['beat_id']} — author: {persona_ctx['author_name']}")
            system_prompt = self.build_system_prompt(exclude_filename=filename, persona_ctx=persona_ctx)
            prompt_file = self.project_root / "scripts" / "last_claude_prompt.txt"
            prompt_file.write_text(f"SYSTEM:\n{system_prompt}\n\nUSER:\n{user_prompt}", encoding="utf-8")
            print(f"\n  Prompt saved to {prompt_file}")
            print("  Skipping API call (use without --no-generate to auto-generate)")
            self.run_stats_extractor(transcript_date, include_llm=False)
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
    result = automation.run_automation(
        session_number=args.session_number,
        is_interlude=args.interlude,
        skip_cleaning=args.no_clean,
        invoke_api=not args.no_generate,
        timeout_minutes=args.timeout,
    )
    # "Nothing to do" exits 0 so a re-run with no waiting transcript still lets
    # the workflow build and deploy; only real failures exit non-zero.
    if result == NOTHING_TO_DO:
        sys.exit(0)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
