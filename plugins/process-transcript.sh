#!/bin/bash
# Transcript Processor - Quick command to process the latest SRT file
# This script finds the most recent .srt file in transcripts_raw/ and processes it

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
RAW_DIR="$PROJECT_ROOT/transcripts_raw"
PYTHON_SCRIPT="$SCRIPT_DIR/transcript_cleaner_ai_optimized.py"

# Check if transcripts_raw directory exists
if [ ! -d "$RAW_DIR" ]; then
    echo "Error: transcripts_raw directory not found at $RAW_DIR"
    exit 1
fi

# Find the most recent .srt file
SRT_FILE=$(find "$RAW_DIR" -name "*.srt" -type f -print0 | xargs -0 ls -t | head -n 1)

if [ -z "$SRT_FILE" ]; then
    echo "Error: No .srt files found in $RAW_DIR"
    echo ""
    echo "Please place your transcript .srt file in the transcripts_raw folder"
    exit 1
fi

echo "Found transcript: $(basename "$SRT_FILE")"
echo "Processing..."
echo ""

# Run the Python script
python3 "$PYTHON_SCRIPT" "$SRT_FILE"

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ Success! Transcript processed and saved to docs/transcripts/"
    echo ""
    echo "You can now:"
    echo "  1. View it in your Docusaurus site"
    echo "  2. Use it to create session notes"
else
    echo ""
    echo "✗ Error processing transcript"
    exit 1
fi
