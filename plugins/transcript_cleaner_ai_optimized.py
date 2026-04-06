#!/usr/bin/env python3
"""
AI-Optimized Transcript Cleaner
Converts SRT transcript files to a clean, AI-friendly markdown format

This script:
- Groups consecutive statements by the same speaker
- Adds blank lines between speakers for readability
- Preserves natural conversation flow
- Outputs markdown-formatted text with bold speaker names
- Keeps approximate timestamps as section markers

Usage:
    python transcript_cleaner_ai_optimized.py input_file.srt [output_file.md]

If no output file is specified, it will create one with '.md' extension.
"""

import re
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta


JSON_SCHEMA_VERSION = "1.0"


def parse_timestamp(timestamp_str):
    """Convert SRT timestamp to seconds"""
    try:
        time_parts = timestamp_str.split(',')[0]  # Remove milliseconds
        h, m, s = map(int, time_parts.split(':'))
        return h * 3600 + m * 60 + s
    except:
        return 0


def format_time(seconds):
    """Format seconds into HH:MM:SS"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_aliases_field(aliases_field: str):
    """
    Parse a markdown table "Transcript Aliases" cell like:
    - "Silus", "Cyrus"
    into: ["Silus", "Cyrus"]
    """
    aliases_field = (aliases_field or "").strip()
    if not aliases_field:
        return []
    # Remove surrounding quotes for easier splitting.
    aliases_field = aliases_field.replace('"', '')
    return [a.strip() for a in aliases_field.split(',') if a.strip()]


def load_campaign_kb_mappings(kb_path: Path):
    """
    Returns:
      alias_to_canonical: maps transcript speaker/name aliases -> canonical character/NPC name
      known_transcription_replacements: maps common mis-transcriptions -> canonical spelling
    """
    if not kb_path.exists():
        return {}, {}

    kb_text = kb_path.read_text(encoding="utf-8")
    lines = kb_text.splitlines()

    alias_to_canonical = {}
    known_transcription_replacements = {}

    def parse_table_rows(start_heading: str, end_heading_prefix: str):
        """
        Parse a simple markdown table after a heading, until another heading starts.
        Returns the raw table row lines (starting with '|').
        """
        start_idx = None
        for i, line in enumerate(lines):
            if line.strip() == start_heading:
                start_idx = i
                break
        if start_idx is None:
            return []

        end_idx = len(lines)
        for j in range(start_idx + 1, len(lines)):
            if lines[j].startswith(end_heading_prefix):
                end_idx = j
                break

        return [ln for ln in lines[start_idx:end_idx] if ln.strip().startswith("|")]

    # --- DM mapping (e.g. "Christopher "Topher" Hooper" + Google Meet name) ---
    dm_start = None
    dm_end = len(lines)
    for i, line in enumerate(lines):
        if line.strip() == "### DM":
            dm_start = i
            break
    if dm_start is not None:
        for j in range(dm_start + 1, len(lines)):
            if lines[j].startswith("### Player Characters"):
                dm_end = j
                break
        dm_block = "\n".join(lines[dm_start:dm_end])
        dm_short = None
        dm_google_meet = None
        m_short = re.search(r'"([^"]+)"', dm_block)
        if m_short:
            dm_short = m_short.group(1).strip()
        m_meet = re.search(r"Google Meet:\s*([^)]+)\)", dm_block)
        if m_meet:
            dm_google_meet = m_meet.group(1).strip()

        if dm_short and dm_google_meet:
            alias_to_canonical[dm_google_meet] = dm_short
            # Also accept the plain short name.
            alias_to_canonical[dm_short] = dm_short

    # --- Player roster mapping (Active players) ---
    roster_rows = parse_table_rows(
        start_heading="### Player Characters (Active)",
        end_heading_prefix="### Player Characters (Departed/Inactive)",
    )
    for row in roster_rows:
        # Skip header + separator rows.
        if "---" in row:
            continue
        parts = [p.strip() for p in row.strip().strip("|").split("|")]
        if len(parts) < 6:
            continue
        character = parts[0]
        player_name = parts[1]
        google_meet_name = parts[2]
        transcript_aliases_field = parts[3]

        # Map Google Meet name + player name + transcript aliases.
        if google_meet_name:
            alias_to_canonical[google_meet_name] = character
        if player_name:
            alias_to_canonical[player_name] = character
        for alias in parse_aliases_field(transcript_aliases_field):
            alias_to_canonical[alias] = character

    # --- Known transcription errors mapping ---
    errors_rows = parse_table_rows(
        start_heading="## Known Transcription Errors",
        end_heading_prefix="## Active Plot Threads",
    )
    for row in errors_rows:
        if "---" in row:
            continue
        parts = [p.strip() for p in row.strip().strip("|").split("|")]
        if len(parts) < 3:
            continue
        transcript_says = parts[0]
        should_be = parts[1]
        if transcript_says and should_be:
            known_transcription_replacements[transcript_says] = should_be

    return alias_to_canonical, known_transcription_replacements


def apply_replacements(text: str, replacements: dict):
    """Apply robust (case-insensitive, whole-token) replacements."""
    if not replacements:
        return text
    out = text
    for says, should_be in replacements.items():
        if not says or says == should_be:
            continue
        # Replace whole word occurrences to avoid turning parts of longer strings.
        # This is intentionally conservative for names/aliases.
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(says) + r"(?![A-Za-z0-9_])"
        out = re.sub(pattern, should_be, out, flags=re.IGNORECASE)
    return out


def clean_transcript_ai_optimized(input_text, return_blocks: bool = False):
    """
    Processes SRT transcript and returns AI-friendly markdown format
    
    Key features for AI parsing:
    - Each speaker gets their own paragraph
    - Consecutive statements by same speaker are grouped
    - Blank lines between speakers for clear separation
    - Bold speaker names in markdown
    - Optional timestamp markers every ~10 minutes
    """
    lines = input_text.split('\n')
    
    entries = []
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        # Check if this is a subtitle number
        if re.match(r'^\d+$', line) and i + 1 < len(lines):
            # Next line should be timestamp
            timestamp_line = lines[i + 1].strip()
            if '-->' in timestamp_line:
                start_time = timestamp_line.split('-->')[0].strip()
                timestamp = parse_timestamp(start_time)
                
                # Collect all dialogue lines until we hit the next subtitle number or end
                dialogue_lines = []
                j = i + 2
                while j < len(lines):
                    next_line = lines[j].strip()
                    # Stop if we hit the next subtitle number
                    if re.match(r'^\d+$', next_line) and j + 1 < len(lines) and '-->' in lines[j + 1]:
                        break
                    dialogue_lines.append(lines[j])
                    j += 1
                
                # Join dialogue lines and process
                full_dialogue = '\n'.join(dialogue_lines)
                
                # Remove HTML tags
                full_dialogue = re.sub(r'<[^>]*>', '', full_dialogue)
                
                # Split by the speaker separator pattern (newline followed by dash and newline)
                speaker_parts = re.split(r'\n-\n', full_dialogue)
                
                for part in speaker_parts:
                    part = part.strip()
                    if not part:
                        continue
                    
                    # Extract speaker name in parentheses at the start
                    speaker_match = re.match(r'\(([^)]+)\)\s*(.*)', part, re.DOTALL)
                    if speaker_match:
                        speaker_name = speaker_match.group(1).strip()
                        dialogue = speaker_match.group(2).strip()
                        # Clean up extra whitespace
                        dialogue = ' '.join(dialogue.split())
                        
                        if dialogue:  # Only add if there's actual dialogue
                            entries.append({
                                'timestamp': timestamp,
                                'name': speaker_name,
                                'dialogue': dialogue
                            })
                
                # Move to next subtitle
                i = j
                continue
        
        i += 1
    
    if not entries:
        if return_blocks:
            return "No dialogue found in the transcript.", []
        return "No dialogue found in the transcript."
    
    # Group consecutive statements by the same speaker
    grouped_dialogue = []
    blocks = []
    current_speaker = None
    current_dialogue = []
    section_timestamp = 0
    block_start_seconds = None
    
    for entry in entries:
        timestamp = entry['timestamp']
        speaker = entry['name']
        dialogue = entry['dialogue']
        
        # Add timestamp marker every 600 seconds (10 minutes)
        if timestamp - section_timestamp >= 600:
            if grouped_dialogue:  # Only add if there's content
                grouped_dialogue.append("")  # Blank line before timestamp
                grouped_dialogue.append(f"### [{format_time(timestamp)}]")
                grouped_dialogue.append("")  # Blank line after timestamp
            section_timestamp = timestamp
        
        if speaker == current_speaker:
            # Same speaker, append to their dialogue
            current_dialogue.append(dialogue)
        else:
            # New speaker, save previous speaker's dialogue
            if current_speaker and current_dialogue:
                # Join all dialogue parts with space
                full_dialogue = ' '.join(current_dialogue)
                grouped_dialogue.append(f"**{current_speaker}:** {full_dialogue}")
                grouped_dialogue.append("")  # Blank line after each speaker
                blocks.append({
                    "start_seconds": block_start_seconds,
                    "speaker_raw": current_speaker,
                    "text_raw": full_dialogue,
                })
            
            # Start new speaker
            current_speaker = speaker
            current_dialogue = [dialogue]
            block_start_seconds = timestamp
    
    # Don't forget the last speaker
    if current_speaker and current_dialogue:
        full_dialogue = ' '.join(current_dialogue)
        grouped_dialogue.append(f"**{current_speaker}:** {full_dialogue}")
        blocks.append({
            "start_seconds": block_start_seconds,
            "speaker_raw": current_speaker,
            "text_raw": full_dialogue,
        })
    
    markdown = '\n'.join(grouped_dialogue)
    if return_blocks:
        return markdown, blocks
    return markdown


def extract_normalized_date(filename):
    """
    Extract date from filename and normalize to YYYY-MM-DD format
    Handles formats like: 
    - "DnD - 2025_10_03 19_00 CDT - Recording.srt"
    - "Session 2025-10-24.srt"
    - "2025_10_03_session.srt"
    """
    # Try to find date pattern YYYY_MM_DD or YYYY-MM-DD
    date_pattern = r'(\d{4})[_-](\d{2})[_-](\d{2})'
    match = re.search(date_pattern, filename)
    
    if match:
        year, month, day = match.groups()
        return f"{year}-{month}-{day}"
    
    # If no date found, return original stem
    return Path(filename).stem


def process_file(input_file, output_file=None):
    """
    Process an SRT transcript file and save the AI-optimized markdown version
    """
    input_path = Path(input_file)
    
    if not input_path.exists():
        print(f"Error: Input file '{input_file}' not found.")
        return False
    
    if not output_file:
        # Get the directory where the script is located
        script_dir = Path(__file__).parent
        # Go up one level to the project root, then into docs/transcripts
        transcripts_dir = script_dir.parent / 'docs' / 'transcripts'
        
        # Create the transcripts directory if it doesn't exist
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract and normalize the date from the filename
        normalized_name = extract_normalized_date(input_path.name)
        
        # Create output filename with .md extension in the transcripts folder
        output_file = transcripts_dir / f"{normalized_name}.md"
    
    output_path = Path(output_file)
    
    try:
        # Read input file
        with open(input_path, 'r', encoding='utf-8') as f:
            input_text = f.read()
        
        print(f"Processing '{input_file}'...")
        
        # Clean the transcript
        project_root = Path(__file__).parent.parent
        kb_path = project_root / "data" / "campaign-kb.md"
        alias_to_canonical, known_transcription_replacements = load_campaign_kb_mappings(kb_path)

        cleaned_text, blocks = clean_transcript_ai_optimized(input_text, return_blocks=True)
        
        # Write output file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(cleaned_text)

        # Also emit a structured JSON transcript for more reliable LLM grounding.
        json_output_path = output_path.with_suffix(".json")
        json_blocks = []
        for b in blocks:
            speaker_raw = b.get("speaker_raw", "")
            speaker_normalized = apply_replacements(speaker_raw, known_transcription_replacements)
            speaker_canonical = alias_to_canonical.get(speaker_normalized) or alias_to_canonical.get(speaker_raw)

            text_raw = b.get("text_raw", "")
            text_canonical = apply_replacements(text_raw, known_transcription_replacements)

            json_blocks.append({
                "start_seconds": b.get("start_seconds", 0),
                "speaker_raw": speaker_raw,
                "speaker_normalized": speaker_normalized,
                "speaker_canonical": speaker_canonical,
                "text_raw": text_raw,
                "text": text_canonical,
            })

        json_payload = {
            "schema_version": JSON_SCHEMA_VERSION,
            "source": {
                "input_file": str(input_path),
                "output_md": str(output_path),
            },
            "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "blocks": json_blocks,
        }
        with open(json_output_path, "w", encoding="utf-8") as f:
            json.dump(json_payload, f, ensure_ascii=True, indent=2)
        
        print(f"✓ AI-optimized transcript saved to '{output_file}'")
        print(f"✓ Structured JSON transcript saved to '{json_output_path}'")
        
        # Show some stats
        lines = [line for line in cleaned_text.split('\n') if line.strip() and not line.startswith('#')]
        speakers = set()
        word_count = 0
        
        for line in lines:
            if line.startswith('**') and ':**' in line:
                speaker_match = re.match(r'\*\*([^*]+)\*\*:', line)
                if speaker_match:
                    speaker = speaker_match.group(1)
                    speakers.add(speaker)
                    dialogue = line.split(':** ', 1)[1] if ':** ' in line else ''
                    word_count += len(dialogue.split())
        
        print(f"\nStats:")
        print(f"  - {len(speakers)} speakers: {', '.join(sorted(speakers))}")
        print(f"  - {len(lines)} dialogue blocks")
        print(f"  - ~{word_count:,} words total")
        print(f"\nFormat optimized for AI parsing:")
        print(f"  ✓ Grouped by speaker")
        print(f"  ✓ Blank lines between speakers")
        print(f"  ✓ Markdown bold formatting")
        print(f"  ✓ Timestamp section markers")
        
        return True
        
    except Exception as e:
        print(f"Error processing file: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """
    Main function to handle command line arguments
    """
    if len(sys.argv) < 2:
        print("AI-Optimized Transcript Cleaner")
        print("=" * 50)
        print("\nUsage: python transcript_cleaner_ai_optimized.py input_file.srt [output_file.md]")
        print("\nExample:")
        print("  python transcript_cleaner_ai_optimized.py session_transcript.srt")
        print("  python transcript_cleaner_ai_optimized.py session_transcript.srt cleaned.md")
        print("\nOutput format:")
        print("  - Markdown with bold speaker names")
        print("  - Grouped consecutive statements by same speaker")
        print("  - Blank lines between speakers for clarity")
        print("  - Timestamp markers every 10 minutes")
        print("  - Optimized for AI/LLM parsing")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    success = process_file(input_file, output_file)
    
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
