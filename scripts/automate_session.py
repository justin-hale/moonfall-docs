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
import time
from pathlib import Path
from datetime import datetime
import re


# Transcript size thresholds.
# Each chunk is sent as a separate Claude call; must be under ~55k chars
# (~18k tokens) to stay within the 30k input-tokens-per-minute rate limit.
CHUNK_SIZE = 55_000
# Transcripts smaller than this are sent as-is; larger ones are summarised
# chunk-by-chunk first, then the combined summaries are used in the main prompt.
MAX_DIRECT_CHARS = 60_000


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
            
        # Sort by modification time, most recent first
        srt_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
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
            
        # Sort by modification time, most recent first
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
        
        # Sort by modification time, most recent first
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
                ["claude", "-p", "--output-format", "text"],
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

    def generate_claude_prompt(self, transcript_path, recent_sessions, session_number, is_interlude):
        """Generate a prompt for Claude to create the session notes"""
        prefix = "interlude" if is_interlude else "session"
        session_type = "interlude" if is_interlude else "session"
        
        # Always use the markdown transcript.  The JSON sibling file is
        # significantly larger (4–5×) due to per-block metadata fields and
        # pretty-printing, and would exceed the API rate limit.
        print(f"Reading transcript content from {transcript_path}...")
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                transcript_content = f.read()
            print(f"✓ Transcript loaded ({len(transcript_content):,} chars)")
        except Exception as e:
            print(f"⚠ Error reading transcript: {e}")
            transcript_content = f"[Error loading transcript from {transcript_path}]"

        # If the transcript is too large to send in one request (would exceed
        # the 30k input-tokens-per-minute rate limit), summarise it first.
        if len(transcript_content) > MAX_DIRECT_CHARS:
            transcript_content = self._summarize_long_transcript(transcript_content)
            transcript_label = "TRANSCRIPT SUMMARY (condensed from full transcript):"
        else:
            transcript_label = "TRANSCRIPT CONTENT:"
        
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

    def invoke_claude(self, prompt, timeout_minutes=15):
        """Invoke Claude Code with the generated prompt in fully autonomous mode,
        streaming output in real-time via --output-format stream-json."""
        print("\n" + "=" * 60)
        print("INVOKING CLAUDE CODE")
        print("=" * 60)

        try:
            cmd = [
                "claude",
                "-p",
                "--verbose",
                "--output-format", "stream-json",
                "--allowedTools", "Read,Write,Edit,Glob,Grep",
            ]

            process = subprocess.Popen(
                cmd,
                cwd=str(self.project_root),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
                text=True,
            )

            process.stdin.write(prompt)
            process.stdin.close()

            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    self._display_stream_event(event)
                except json.JSONDecodeError:
                    print(line, flush=True)

            process.wait(timeout=timeout_minutes * 60)

            if process.returncode == 0:
                print("\n✓ Claude invocation completed")
                return True
            else:
                print(f"\n⚠ Claude exited with code {process.returncode}")
                return False

        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            print(f"\n✗ Claude timed out after {timeout_minutes} minutes — aborting")
            return False
        except FileNotFoundError:
            print("\n✗ Error: 'claude' command not found")
            print("Make sure Claude Code CLI is installed and in your PATH")
            return False
        except Exception as e:
            print(f"\n✗ Error invoking Claude: {e}")
            return False
    
    def run_automation(self, session_number=None, is_interlude=False, skip_cleaning=False, invoke_claude_auto=True, timeout_minutes=15):
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
                return False
            
            if not self.run_transcript_cleaner(srt_file):
                return False
        else:
            print("\n[Step 1/3] Skipping transcript cleaning...")
        
        print("\n[Step 2/3] Finding latest transcript...")
        latest_transcript = self.find_latest_transcript()
        if not latest_transcript:
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
        
        claude_prompt = self.generate_claude_prompt(
            latest_transcript,
            recent_sessions,
            session_number,
            is_interlude
        )
        
        print("\n" + "=" * 60)
        print("READY FOR CLAUDE")
        print("=" * 60)
        print(f"\nTranscript: {latest_transcript}")
        print(f"Target: {session_path}")
        print(f"Session Number: {session_number}")
        print(f"Type: {'Interlude' if is_interlude else 'Session'}")
        print(f"Date: {transcript_date}")
        print(f"Prompt size: {len(claude_prompt):,} characters")
        
        prompt_file = self.project_root / "scripts" / "last_claude_prompt.txt"
        with open(prompt_file, 'w') as f:
            f.write(claude_prompt)
        print(f"\nPrompt saved to: {prompt_file}")
        
        if invoke_claude_auto:
            if self.invoke_claude(claude_prompt, timeout_minutes=timeout_minutes):
                if srt_file and srt_file.exists():
                    print("\n" + "=" * 60)
                    print("CLEANING UP")
                    print("=" * 60)
                    try:
                        srt_file.unlink()
                        print(f"✓ Deleted original transcript: {srt_file.name}")
                    except Exception as e:
                        print(f"⚠ Could not delete {srt_file.name}: {e}")
        else:
            print("\n⚠ Skipping Claude invocation (use without --no-claude to auto-invoke)")
        
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
    
    args = parser.parse_args()
    
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    automation = SessionAutomation(project_root)
    success = automation.run_automation(
        session_number=args.session_number,
        is_interlude=args.interlude,
        skip_cleaning=args.no_clean,
        invoke_claude_auto=not args.no_claude,
        timeout_minutes=args.timeout
    )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
