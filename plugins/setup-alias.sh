#!/bin/bash
# Setup script - Run this once to create an easy command alias

echo "Setting up 'process-transcript' command..."
echo ""

# Get the absolute path to the script
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/process-transcript.sh"

# Determine which shell config file to use
if [ -f "$HOME/.zshrc" ]; then
    SHELL_CONFIG="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_CONFIG="$HOME/.bashrc"
elif [ -f "$HOME/.bash_profile" ]; then
    SHELL_CONFIG="$HOME/.bash_profile"
else
    echo "Could not find shell configuration file"
    echo "Please add this line manually to your shell config:"
    echo "alias process-transcript='$SCRIPT_PATH'"
    exit 1
fi

# Check if alias already exists
if grep -q "alias process-transcript=" "$SHELL_CONFIG"; then
    echo "Alias already exists in $SHELL_CONFIG"
    echo "Updating it..."
    # Remove old alias
    sed -i.bak '/alias process-transcript=/d' "$SHELL_CONFIG"
fi

# Add alias to shell config
echo "" >> "$SHELL_CONFIG"
echo "# Moonfall Transcript Processor" >> "$SHELL_CONFIG"
echo "alias process-transcript='$SCRIPT_PATH'" >> "$SHELL_CONFIG"

echo "✓ Added 'process-transcript' command to $SHELL_CONFIG"
echo ""
echo "To use it immediately, run:"
echo "  source $SHELL_CONFIG"
echo ""
echo "Or just open a new terminal window."
echo ""
echo "Then you can simply type:"
echo "  process-transcript"
echo ""
echo "from anywhere, and it will automatically process the .srt file in transcripts_raw!"
