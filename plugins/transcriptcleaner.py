#!/usr/bin/env python3
"""
Transcript Cleaner - Converts formatted transcript files to clean speaker:dialogue format

Usage:
    python transcript_cleaner.py input_file.txt [output_file.txt]

If no output file is specified, it will create one with '_cleaned' suffix.
"""

import re
import sys
import os
from pathlib import Path


def clean_transcript(input_text):
    """
    Processes a formatted transcript and returns clean speaker:dialogue format
    """
    lines = input_text.split('\n')
    cleaned_entries = []
    current_speaker = None
    current_dialogue = ""
    
    for line in lines:
        line = line.strip()
        
        # Skip empty lines, numbers, and timestamps
        if not line or re.match(r'^\d+$', line) or re.match(r'^\d{2}:\d{2}:\d{2}', line):
            continue
        
        # Remove HTML tags
        line = re.sub(r'<[^>]*>', '', line)
        line = line.strip()
        
        if not line:
            continue
        
        # Look for speaker names in parentheses
        speaker_matches = re.findall(r'\(([^)]+)\)', line)
        
        if speaker_matches:
            # Process each speaker found in the line
            for speaker_name in speaker_matches:
                speaker_name = speaker_name.strip()
                
                # If we have a current speaker and dialogue, save it
                if current_speaker and current_dialogue.strip():
                    cleaned_entries.append(f"{current_speaker}: {current_dialogue.strip()}")
                
                # Extract dialogue for this speaker
                # Remove all speaker parentheses and clean up
                dialogue_line = re.sub(r'\([^)]+\)', '', line)
                dialogue_line = re.sub(r'^[-\s]+|[-\s]+$', '', dialogue_line).strip()
                
                # Start new speaker entry
                current_speaker = speaker_name
                current_dialogue = dialogue_line
        else:
            # This line might be a continuation of previous speaker's dialogue
            if current_speaker:
                # Clean up the line
                continuation = re.sub(r'^[-\s]+|[-\s]+$', '', line).strip()
                if continuation:
                    if current_dialogue:
                        current_dialogue += " " + continuation
                    else:
                        current_dialogue = continuation
    
    # Don't forget the last speaker
    if current_speaker and current_dialogue.strip():
        cleaned_entries.append(f"{current_speaker}: {current_dialogue.strip()}")
    
    # Group consecutive entries by the same speaker
    if not cleaned_entries:
        return "No dialogue found in the transcript."
    
    grouped_entries = []
    current_group_speaker = None
    current_group_dialogue = ""
    
    for entry in cleaned_entries:
        speaker, dialogue = entry.split(': ', 1)
        
        if speaker == current_group_speaker:
            # Same speaker, append dialogue
            current_group_dialogue += " " + dialogue
        else:
            # New speaker, save previous group if exists
            if current_group_speaker:
                grouped_entries.append(f"{current_group_speaker}: {current_group_dialogue}")
            
            # Start new group
            current_group_speaker = speaker
            current_group_dialogue = dialogue
    
    # Add the last group
    if current_group_speaker:
        grouped_entries.append(f"{current_group_speaker}: {current_group_dialogue}")
    
    return ' | '.join(grouped_entries)


def process_file(input_file, output_file=None):
    """
    Process a transcript file and save the cleaned version
    """
    input_path = Path(input_file)
    
    if not input_path.exists():
        print(f"Error: Input file '{input_file}' not found.")
        return False
    
    if not output_file:
        # Create output filename with '_cleaned' suffix
        output_file = input_path.stem + '_cleaned' + input_path.suffix
        if input_path.suffix.lower() not in ['.txt', '.srt', '.vtt']:
            output_file += '.txt'
    
    output_path = Path(output_file)
    
    try:
        # Read input file
        with open(input_path, 'r', encoding='utf-8') as f:
            input_text = f.read()
        
        print(f"Processing '{input_file}'...")
        
        # Clean the transcript
        cleaned_text = clean_transcript(input_text)
        
        # Write output file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(cleaned_text)
        
        print(f"✓ Cleaned transcript saved to '{output_file}'")
        
        # Show some stats
        lines = [line for line in cleaned_text.split('\n') if line.strip()]
        speakers = set()
        word_count = 0
        
        for line in lines:
            if ': ' in line:
                speaker = line.split(': ')[0]
                speakers.add(speaker)
                dialogue = line.split(': ', 1)[1]
                word_count += len(dialogue.split())
        
        print(f"  - {len(speakers)} speakers found")
        print(f"  - {len(lines)} dialogue entries")
        print(f"  - {word_count} words total")
        
        return True
        
    except Exception as e:
        print(f"Error processing file: {e}")
        return False


def main():
    """
    Main function to handle command line arguments
    """
    if len(sys.argv) < 2:
        print("Usage: python transcript_cleaner.py input_file.txt [output_file.txt]")
        print("\nExample:")
        print("  python transcript_cleaner.py my_transcript.txt")
        print("  python transcript_cleaner.py my_transcript.txt cleaned_version.txt")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    success = process_file(input_file, output_file)
    
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()