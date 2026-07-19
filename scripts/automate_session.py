#!/usr/bin/env python3
"""
Session Automation Script for Docusaurus D&D Campaign

This script automates the workflow of creating session notes from transcript files:
1. Finds the latest SRT file in transcripts_raw/
2. Runs the transcript cleaner script to convert it to markdown
3. Creates a new session note file based on the processed transcript
4. Uses Claude to generate the session content by analyzing the transcript
   and referencing previous session notes

Usage:
    python automate_session.py [--session-number N] [--interlude] [--no-clean] [--no-claude]

Arguments:
    --session-number N : Specify session number (default: auto-detect next number)
    --interlude        : Create an interlude instead of a regular session
    --no-clean         : Skip transcript cleaning (use existing transcript)
    --no-claude        : Don't automatically invoke Claude (just save prompt)
"""

import os
import sys
import subprocess
import argparse
import json
import threading
import time
from pathlib import Path
from datetime import datetime
import re

sys.path.insert(0, str(Path(__file__).parent.parent / "plugins"))
from transcript_cleaner_ai_optimized import extract_normalized_date  # noqa: E402


# Note generation runs single-pass against the full transcript on Opus —
# the Opus rate pool (500k input tokens/min at tier 1) comfortably fits a
# whole session transcript (~45-80k tokens) in one request.
GENERATION_MODEL = "claude-opus-4-8"
# Chunk summaries (rate-limit fallback only) and validation passes use Sonnet.
CHUNK_MODEL = "claude-sonnet-4-6"

# Fallback-path chunking: each chunk is sent as a separate Claude call; must be
# under ~55k chars (~18k tokens) to stay within the Sonnet 30k
# input-tokens-per-minute rate limit.
CHUNK_SIZE = 55_000

# Placeholder strings from the session template; their presence in a "generated"
# note means generation did not actually complete.
TEMPLATE_PLACEHOLDERS = (
    "[Title To Be Generated]",
    "[Description to be generated",
    "[Summary to be generated",
    "[Content to be generated",
)


class SessionAutomation:
    def __init__(self, project_root):
        self.project_root = Path(project_root)
        self.raw_dir = self.project_root / "transcripts_raw"
        self.transcripts_dir = self.project_root / "docs" / "transcripts"
        self.sessions_dir = self.project_root / "docs" / "sessions"
        self.plugins_dir = self.project_root / "plugins"
        self.cleaner_script = self.plugins_dir / "transcript_cleaner_ai_optimized.py"
        
    def find_latest_srt(self):
        """Find the most recent .srt file in transcripts_raw/"""
        if not self.raw_dir.exists():
            print(f"Error: transcripts_raw directory not found at {self.raw_dir}")
            return None
            
        srt_files = list(self.raw_dir.glob("*.srt"))
        if not srt_files:
            print(f"Error: No .srt files found in {self.raw_dir}")
            return None

        # Sort by the session date embedded in the filename — file mtimes are
        # meaningless in CI (fresh checkout). Fall back to mtime for undated names.
        srt_files.sort(
            key=lambda x: (extract_normalized_date(x.name), x.stat().st_mtime),
            reverse=True,
        )
        return srt_files[0]
    
    def run_transcript_cleaner(self, srt_file):
        """Run the transcript cleaner script on the SRT file"""
        print(f"Processing transcript: {srt_file.name}")
        print("Running transcript cleaner...")
        
        try:
            result = subprocess.run(
                ["python3", str(self.cleaner_script), str(srt_file)],
                capture_output=True,
                text=True,
                check=True
            )
            print(result.stdout)
            print("✓ Transcript cleaned successfully")
            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ Error running transcript cleaner: {e}")
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

        # Filenames are YYYY-MM-DD.md, so a lexical sort is chronological.
        # File mtimes are meaningless in CI (fresh checkout).
        transcript_files.sort(key=lambda x: x.name, reverse=True)
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
            
        # Extract numbers from filenames
        numbers = []
        for f in session_files:
            match = re.search(rf"{prefix}-(\d+)\.md", f.name)
            if match:
                numbers.append(int(match.group(1)))
        
        return max(numbers) + 1 if numbers else 1
    
    def get_recent_sessions(self, count=5):
        """Get the most recent session files for context"""
        if not self.sessions_dir.exists():
            return []

        session_files = list(self.sessions_dir.glob("session-*.md"))
        session_files.extend(list(self.sessions_dir.glob("interlude-*.md")))

        # Sort by frontmatter date, then file number — file mtimes are
        # meaningless in CI (fresh checkout gives every file the same mtime).
        def sort_key(path):
            date = ""
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for _ in range(10):
                        line = f.readline()
                        m = re.match(r"^date:\s*(\d{4}-\d{2}-\d{2})", line)
                        if m:
                            date = m.group(1)
                            break
            except OSError:
                pass
            num_match = re.search(r"-(\d+)\.md$", path.name)
            number = int(num_match.group(1)) if num_match else 0
            return (date, number)

        session_files.sort(key=sort_key, reverse=True)

        return session_files[:count]
    
    def create_session_template(self, session_number, is_interlude, transcript_date):
        """Create a basic session template"""
        prefix = "Interlude" if is_interlude else ""
        title = f"{prefix}{' ' if prefix else ''}{session_number}"
        filename = f"{'interlude' if is_interlude else 'session'}-{session_number}.md"
        
        template = f"""---
title: "{title}: [Title To Be Generated]"
date: {transcript_date}
description: "[Description to be generated by Claude]"
summary: "[Summary to be generated by Claude]"
podcastlink: ""
---

**🎧 Podcast coming soon • *{transcript_date}***

## [Section Title]

[Content to be generated by Claude based on the transcript]

---

*Note: This is a draft template. Use Claude to analyze the transcript and generate the full session notes.*
"""
        return filename, template

    def _invoke_claude_text(self, prompt, context="chunk summary"):
        """Run claude -p in plain-text mode, retrying on 429 rate-limit errors."""
        for attempt in range(5):
            result = subprocess.run(
                ["claude", "-p", "--output-format", "text", "--model", CHUNK_MODEL],
                input=prompt,
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
            )
            if result.returncode == 0:
                return result.stdout.strip()
            stderr = result.stderr or ""
            if "429" in stderr or "rate_limit" in stderr:
                wait_secs = 65 * (attempt + 1)
                print(f"  Rate limited on {context}, waiting {wait_secs}s before retry…")
                time.sleep(wait_secs)
            else:
                print(f"  Warning: {context} failed (exit {result.returncode}): {stderr[:200]}")
                return ""
        print(f"  Warning: {context} gave up after 5 attempts — returning empty.")
        return ""

    def _summarize_long_transcript(self, text):
        """Split a large transcript into chunks and summarise each via Claude.

        Each chunk is kept under CHUNK_SIZE chars (~18k tokens) so it stays
        within the 30k input-tokens-per-minute API rate limit.  The summaries
        are much smaller and can be combined into a single generation prompt.
        """
        chunks = [text[i:i + CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE)]
        print(f"  Transcript is {len(text):,} chars — summarising {len(chunks)} chunks to fit rate limit…")
        summaries = []
        for i, chunk in enumerate(chunks, 1):
            print(f"  Summarising chunk {i}/{len(chunks)} ({len(chunk):,} chars)…")
            summary = self._invoke_claude_text(
                f"""You are summarising chunk {i} of {len(chunks)} from a D&D session transcript.

Extract and list in bullet-point form:
- Key plot events and story developments
- Important character actions and decisions
- Significant dialogue and memorable quotes
- New information, revelations, or lore
- Combat encounters and their outcomes

Be concise but thorough — every meaningful event should appear.
Do NOT invent anything not present in the transcript.

TRANSCRIPT CHUNK:
{chunk}""",
                context=f"chunk {i}/{len(chunks)}",
            )
            if summary:
                summaries.append(f"--- CHUNK {i}/{len(chunks)} SUMMARY ---\n{summary}")
            # Pause between chunks to respect the per-minute token budget.
            if i < len(chunks):
                print(f"  Waiting 65s before next chunk to respect rate limit…")
                time.sleep(65)

        combined = "\n\n".join(summaries)
        print(f"  Combined summaries: {len(combined):,} chars (down from {len(text):,})")
        return combined

    def generate_claude_prompt(self, transcript_path, recent_sessions, session_number,
                               is_interlude, transcript_content=None,
                               transcript_label="TRANSCRIPT CONTENT:"):
        """Generate a prompt for Claude to create the session notes.

        By default the FULL markdown transcript is embedded — generation runs
        single-pass on Opus, whose rate pool fits a whole session. The
        ``transcript_content``/``transcript_label`` overrides exist for the
        rate-limit fallback path, which substitutes chunk summaries.
        (The JSON sibling transcript is not used here: it is 4-5x larger due
        to per-block metadata and pretty-printing.)
        """
        prefix = "interlude" if is_interlude else "session"
        session_type = "interlude" if is_interlude else "session"

        if transcript_content is None:
            print(f"Reading transcript content from {transcript_path}...")
            try:
                with open(transcript_path, "r", encoding="utf-8") as f:
                    transcript_content = f.read()
                print(f"✓ Transcript loaded ({len(transcript_content):,} chars)")
            except Exception as e:
                print(f"⚠ Error reading transcript: {e}")
                transcript_content = f"[Error loading transcript from {transcript_path}]"

        prompt = f"""IMPORTANT: You are running in fully autonomous mode. Do NOT ask any questions or request clarification. If you encounter an issue you cannot resolve, output a clear error message explaining the problem and stop immediately. Make your best judgment for any ambiguous decisions.

I need you to create a comprehensive {session_type} note for {session_type} {session_number} based on the transcript below.

For context, here are the most recent session notes you should reference for style and format:
"""
        for session_file in recent_sessions:
            prompt += f"- {session_file.relative_to(self.project_root)}\n"
        
        # Inject campaign knowledge base if available
        kb_path = self.project_root / "data" / "campaign-kb.md"
        if kb_path.exists():
            try:
                with open(kb_path, 'r', encoding='utf-8') as f:
                    kb_content = f.read()
                print(f"✓ Campaign KB loaded ({len(kb_content):,} chars)")
                prompt += f"""
The following campaign knowledge base contains canonical character names, known transcription
errors, and important context. Use this as your PRIMARY reference for correct names and spellings.
When the transcript uses a name listed in "Known Transcription Errors", ALWAYS use the corrected
version. When the transcript uses player names, map them to character names using the Character
Roster.

CAMPAIGN KNOWLEDGE BASE:
{kb_content}

---
"""
            except Exception as e:
                print(f"⚠ Could not load campaign KB: {e}")

        prompt += f"""
Please create a detailed session note following the format and style of the previous sessions.

FACTS & GROUNDING RULES (very important):
- Only use concrete details that appear in the provided transcript.
- Do NOT invent events, characters, names, or locations that are not supported by the transcript.
- Every blockquote must be a near-verbatim line from the transcript — light cleanup of
  filler words ("um", "uh", repeated words) only. Never paraphrase, splice, or invent
  quotes. Attribute each quote to the canonical character name.

TIMESTAMP ANCHORS (required):
- Immediately after each `## ` section heading that narrates events, emit an HTML
  comment of the form `<!-- transcript: HH:MM:SS -->` giving the timestamp where that
  section's events begin in the transcript. Use the nearest preceding `### [HH:MM:SS]`
  marker in the transcript. Anchors must increase through the note. These comments are
  invisible on the published site and are used by automated verification.
- Synthesis sections (e.g. Themes, Session MVP, Players Present) do not need anchors.

The session note should include:
1. A descriptive title that captures the main event or theme
2. A compelling description and summary
3. Well-organized sections with clear headings
4. Key events, character moments, and story beats
5. Important quotes where relevant

Do NOT include links to any other file or entry.

Create the session note file at: docs/sessions/{prefix}-{session_number}.md

Use the same markdown formatting style and level of detail as the previous sessions. Make sure to capture the narrative flow, character development, and key plot points.

---

{transcript_label}

{transcript_content}
"""
        
        return prompt
    
    def _display_stream_event(self, event):
        """Parse a stream-json event and print human-readable progress."""
        event_type = event.get("type")

        if event_type == "assistant":
            pass

        elif event_type == "content_block_start":
            block = event.get("content_block", {})
            if block.get("type") == "tool_use":
                tool = block.get("name", "unknown")
                print(f"\n[tool] {tool}", end="", flush=True)

        elif event_type == "content_block_delta":
            delta = event.get("delta", {})
            if delta.get("type") == "text_delta":
                print(delta.get("text", ""), end="", flush=True)
            elif delta.get("type") == "input_json_delta":
                pass

        elif event_type == "content_block_stop":
            pass

        elif event_type == "message_start":
            pass

        elif event_type == "message_delta":
            pass

        elif event_type == "message_stop":
            pass

        elif event_type == "result":
            cost = event.get("cost_usd")
            duration = event.get("duration_ms")
            subtype = event.get("subtype")
            parts = []
            if duration is not None:
                parts.append(f"{duration / 1000:.1f}s")
            if cost is not None:
                parts.append(f"${cost:.4f}")
            if subtype:
                parts.append(subtype)
            if parts:
                print(f"\n[result] {' | '.join(parts)}", flush=True)
            if subtype == "error" or event.get("is_error"):
                print(f"[result detail] {json.dumps(event, indent=2)}", flush=True)

        elif event_type == "tool":
            tool_name = event.get("tool", "")
            tool_input = event.get("input", {})

            if isinstance(tool_input, dict):
                path = (tool_input.get("file_path")
                        or tool_input.get("path")
                        or tool_input.get("pattern")
                        or tool_input.get("command", ""))
                print(f" → {path}", flush=True)

        elif event_type == "error":
            error = event.get("error", {})
            msg = error.get("message", str(error))
            print(f"\n[error] {msg}", flush=True)

    def invoke_claude(self, prompt, model=GENERATION_MODEL, timeout_minutes=15):
        """Invoke Claude Code with the generated prompt in fully autonomous mode,
        streaming output in real-time via --output-format stream-json.

        Returns "ok", "rate_limited", or "failed" so the caller can decide
        whether to retry or fall back to chunked summarization.
        """
        print("\n" + "=" * 60)
        print(f"INVOKING CLAUDE CODE ({model})")
        print("=" * 60)

        error_blobs = []
        stderr_chunks = []

        try:
            cmd = [
                "claude",
                "-p",
                "--verbose",
                "--output-format", "stream-json",
                "--model", model,
                "--allowedTools", "Read,Write,Edit,Glob,Grep",
            ]

            process = subprocess.Popen(
                cmd,
                cwd=str(self.project_root),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            def _drain_stderr():
                for chunk in process.stderr:
                    stderr_chunks.append(chunk)

            stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
            stderr_thread.start()

            process.stdin.write(prompt)
            process.stdin.close()

            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    self._display_stream_event(event)
                    if event.get("type") == "error" or event.get("is_error") \
                            or event.get("subtype") == "error":
                        error_blobs.append(json.dumps(event))
                except json.JSONDecodeError:
                    print(line, flush=True)

            process.wait(timeout=timeout_minutes * 60)
            stderr_thread.join(timeout=5)

            if process.returncode == 0:
                print("\n✓ Claude invocation completed")
                return "ok"

            error_text = "".join(stderr_chunks) + " ".join(error_blobs)
            print(f"\n⚠ Claude exited with code {process.returncode}")
            if error_text.strip():
                print(error_text[:500])
            if any(marker in error_text for marker in
                   ("429", "rate_limit", "rate limit", "overloaded")):
                return "rate_limited"
            return "failed"

        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            print(f"\n✗ Claude timed out after {timeout_minutes} minutes — aborting")
            return "failed"
        except FileNotFoundError:
            print("\n✗ Error: 'claude' command not found")
            print("Make sure Claude Code CLI is installed and in your PATH")
            return "failed"
        except Exception as e:
            print(f"\n✗ Error invoking Claude: {e}")
            return "failed"

    def _note_was_generated(self, session_path):
        """True only if the note file exists and is not a leftover template."""
        if not session_path.exists():
            print(f"✗ Expected note {session_path} was not created")
            return False
        content = session_path.read_text(encoding="utf-8")
        if len(content) < 500:
            print(f"✗ Note {session_path} is suspiciously short ({len(content)} chars)")
            return False
        for placeholder in TEMPLATE_PLACEHOLDERS:
            if placeholder in content:
                print(f"✗ Note {session_path} still contains template placeholder "
                      f"{placeholder!r}")
                return False
        return True

    def _save_prompt(self, prompt):
        prompt_file = self.project_root / "scripts" / "last_claude_prompt.txt"
        with open(prompt_file, "w") as f:
            f.write(prompt)
        print(f"Prompt saved to: {prompt_file} ({len(prompt):,} chars)")

    def generate_with_fallback(self, transcript_path, recent_sessions, session_number,
                               is_interlude, session_path, timeout_minutes=15):
        """Single-pass Opus generation, with chunked summarization as a
        rate-limit fallback only.

        Returns (status, generation_mode) where status is "ok"/"failed" and
        generation_mode is "single_pass" or "chunked_fallback".
        """
        prompt = self.generate_claude_prompt(
            transcript_path, recent_sessions, session_number, is_interlude
        )
        self._save_prompt(prompt)

        generation_mode = "single_pass"
        status = self.invoke_claude(prompt, timeout_minutes=timeout_minutes)

        if status == "rate_limited":
            print("\nRate limited — waiting 65s and retrying single-pass once…")
            time.sleep(65)
            status = self.invoke_claude(prompt, timeout_minutes=timeout_minutes)

        if status == "rate_limited":
            print("\nStill rate limited — falling back to chunked summarization.")
            generation_mode = "chunked_fallback"
            with open(transcript_path, "r", encoding="utf-8") as f:
                full_transcript = f.read()
            summaries = self._summarize_long_transcript(full_transcript)
            fallback_prompt = self.generate_claude_prompt(
                transcript_path, recent_sessions, session_number, is_interlude,
                transcript_content=summaries,
                transcript_label="TRANSCRIPT SUMMARY (condensed from full transcript):",
            )
            self._save_prompt(fallback_prompt)
            status = self.invoke_claude(fallback_prompt, timeout_minutes=timeout_minutes)

        if status == "rate_limited":
            status = "failed"
        if status == "ok" and not self._note_was_generated(session_path):
            status = "failed"
        return status, generation_mode
    
    def _write_meta(self, **fields):
        """Write automation_output/session-meta.json — the contract the CI
        workflow gates on (it reads this file, not the exit code)."""
        out_dir = self.project_root / "automation_output"
        out_dir.mkdir(parents=True, exist_ok=True)
        meta_path = out_dir / "session-meta.json"
        meta_path.write_text(json.dumps(fields, indent=2) + "\n", encoding="utf-8")
        print(f"Meta written: {meta_path} -> {fields.get('status')}/{fields.get('verdict')}")
        return meta_path

    def _note_frontmatter_title(self, session_path):
        try:
            head = session_path.read_text(encoding="utf-8")[:1000]
            m = re.search(r'^title:\s*"?(.*?)"?\s*$', head, re.M)
            return m.group(1) if m else session_path.stem
        except OSError:
            return session_path.stem

    def run_validation(self, session_path, transcript_path, skip_kb_update=False):
        """Run lint -> verify -> kb-update against a note/transcript pair.

        Returns (verdict, verifier_status). Lint and verify failures surface in
        the verdict; a KB-update failure is logged but never blocks.
        """
        out_dir = self.project_root / "automation_output"
        out_dir.mkdir(parents=True, exist_ok=True)
        lint_report = out_dir / "lint-report.json"
        session_report = out_dir / "session-report.json"
        kb_path = self.project_root / "data" / "campaign-kb.md"
        scripts_dir = self.project_root / "scripts"

        print("\n" + "=" * 60)
        print("VALIDATING NOTE")
        print("=" * 60)

        subprocess.run(
            [sys.executable, str(scripts_dir / "lint_session.py"),
             "--note", str(session_path), "--transcript", str(transcript_path),
             "--kb", str(kb_path), "--json-out", str(lint_report)],
            cwd=str(self.project_root),
        )

        verify = subprocess.run(
            [sys.executable, str(scripts_dir / "verify_session.py"),
             "--note", str(session_path), "--transcript", str(transcript_path),
             "--kb", str(kb_path), "--report", str(session_report),
             "--lint-report", str(lint_report)],
            cwd=str(self.project_root),
        )

        verdict = "FAIL"
        verifier_status = "error"
        if session_report.exists():
            try:
                report = json.loads(session_report.read_text(encoding="utf-8"))
                verdict = report.get("verdict", "FAIL")
                verifier_status = report.get("verifier_status", "error")
            except json.JSONDecodeError:
                pass
        if verify.returncode == 2:
            # Verifier infrastructure failure — fail closed, never publish
            # an unverified note.
            verdict = "FAIL"

        if not skip_kb_update:
            kb_update = subprocess.run(
                [sys.executable, str(scripts_dir / "update_kb.py"),
                 "--note", str(session_path), "--transcript", str(transcript_path),
                 "--kb", str(kb_path), "--report", str(session_report)],
                cwd=str(self.project_root),
            )
            if kb_update.returncode != 0:
                print("⚠ KB update failed — continuing (non-blocking)")

        return verdict, verifier_status

    def run_automation(self, session_number=None, is_interlude=False, skip_cleaning=False,
                       invoke_claude_auto=True, timeout_minutes=15,
                       skip_validation=False, force_fail_verdict=False):
        """Run the full automation workflow"""
        print("=" * 60)
        print("Session Automation Workflow")
        print("=" * 60)

        latest_transcript = None
        srt_file = None
        if not skip_cleaning:
            print("\n[Step 1/3] Finding and cleaning transcript...")
            srt_file = self.find_latest_srt()
            if not srt_file:
                # Not an error: the workflow also triggers on SRT *deletions*
                # (e.g. merging a review PR). Nothing to do.
                print("No SRT to process — NOOP.")
                self._write_meta(status="noop", verdict="NOOP")
                return True

            if not self.run_transcript_cleaner(srt_file):
                self._write_meta(status="clean_failed", verdict="FAIL")
                return False
        else:
            print("\n[Step 1/3] Skipping transcript cleaning...")

        print("\n[Step 2/3] Finding latest transcript...")
        latest_transcript = self.find_latest_transcript()
        if not latest_transcript:
            self._write_meta(status="no_transcript", verdict="FAIL")
            return False

        print(f"✓ Found transcript: {latest_transcript.name}")

        try:
            transcript_date = latest_transcript.stem
            datetime.strptime(transcript_date, "%Y-%m-%d")
        except ValueError:
            transcript_date = datetime.now().strftime("%Y-%m-%d")
            print(f"⚠ Could not parse date from transcript filename, using today: {transcript_date}")

        if session_number is None:
            session_number = self.get_next_session_number(is_interlude)

        print(f"\n[Step 3/3] Creating {'interlude' if is_interlude else 'session'} {session_number}...")

        recent_sessions = self.get_recent_sessions()

        filename, template = self.create_session_template(session_number, is_interlude, transcript_date)
        session_path = self.sessions_dir / filename

        print("\n" + "=" * 60)
        print("READY FOR CLAUDE")
        print("=" * 60)
        print(f"\nTranscript: {latest_transcript}")
        print(f"Target: {session_path}")
        print(f"Session Number: {session_number}")
        print(f"Type: {'Interlude' if is_interlude else 'Session'}")
        print(f"Date: {transcript_date}")

        if not invoke_claude_auto:
            prompt = self.generate_claude_prompt(
                latest_transcript, recent_sessions, session_number, is_interlude
            )
            self._save_prompt(prompt)
            print("\n⚠ Skipping Claude invocation (use without --no-claude to auto-invoke)")
            self._write_meta(status="prompt_only", verdict="NOOP")
            return True

        status, generation_mode = self.generate_with_fallback(
            latest_transcript, recent_sessions, session_number, is_interlude,
            session_path, timeout_minutes=timeout_minutes,
        )
        if status != "ok":
            self._write_meta(status="generation_failed", verdict="FAIL",
                             generation_mode=generation_mode)
            return False

        if skip_validation:
            verdict, verifier_status = "PASS", "skipped"
            print("\n⚠ Skipping validation (--skip-validation)")
        else:
            verdict, verifier_status = self.run_validation(session_path, latest_transcript)

        if force_fail_verdict:
            print("\n⚠ --force-fail-verdict: overriding verdict to FAIL")
            verdict = "FAIL"

        if srt_file and srt_file.exists():
            print("\n" + "=" * 60)
            print("CLEANING UP")
            print("=" * 60)
            try:
                srt_file.unlink()
                print(f"✓ Deleted original transcript: {srt_file.name}")
            except Exception as e:
                print(f"⚠ Could not delete {srt_file.name}: {e}")

        self._write_meta(
            status="ok",
            verdict=verdict,
            verifier_status=verifier_status,
            note_path=str(session_path.relative_to(self.project_root)),
            slug=session_path.stem,
            title=self._note_frontmatter_title(session_path),
            date=transcript_date,
            generation_mode=generation_mode,
        )
        return True


def main():
    parser = argparse.ArgumentParser(
        description="Automate D&D session note creation from transcripts"
    )
    parser.add_argument(
        "--session-number",
        type=int,
        help="Specify session number (default: auto-detect next number)"
    )
    parser.add_argument(
        "--interlude",
        action="store_true",
        help="Create an interlude instead of a regular session"
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Skip transcript cleaning (use existing transcript)"
    )
    parser.add_argument(
        "--no-claude",
        action="store_true",
        help="Don't automatically invoke Claude (just save prompt to file)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Timeout in minutes for each Claude invocation (default: 15)"
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip lint/verify/KB-update after generation (local debugging)"
    )
    parser.add_argument(
        "--force-fail-verdict",
        action="store_true",
        help="Force the final verdict to FAIL (CI escape hatch to exercise the review-PR path)"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only run lint/verify/KB-update against --note/--transcript; no generation"
    )
    parser.add_argument("--note", help="Note path for --validate-only")
    parser.add_argument("--transcript", help="Transcript path for --validate-only")

    args = parser.parse_args()

    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    automation = SessionAutomation(project_root)

    if args.validate_only:
        if not args.note or not args.transcript:
            parser.error("--validate-only requires --note and --transcript")
        verdict, verifier_status = automation.run_validation(
            Path(args.note).resolve(), Path(args.transcript).resolve()
        )
        automation._write_meta(
            status="ok", verdict=verdict, verifier_status=verifier_status,
            note_path=args.note, slug=Path(args.note).stem,
            title=automation._note_frontmatter_title(Path(args.note)),
        )
        sys.exit(0)

    success = automation.run_automation(
        session_number=args.session_number,
        is_interlude=args.interlude,
        skip_cleaning=args.no_clean,
        invoke_claude_auto=not args.no_claude,
        timeout_minutes=args.timeout,
        skip_validation=args.skip_validation,
        force_fail_verdict=args.force_fail_verdict,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
