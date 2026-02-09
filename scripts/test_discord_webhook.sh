#!/bin/bash
# Test script that mimics the Discord webhook notification from generate-session.yml
# Finds the latest session file, extracts the title, and posts to Discord.
#
# Usage:
#   DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." ./scripts/test_discord_webhook.sh
#
# Options:
#   --dry-run    Print the message without posting to Discord

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SESSIONS_DIR="$PROJECT_ROOT/docs/sessions"
DRY_RUN=false

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
fi

# Find the latest session or interlude file (by modification time, same as the workflow)
NEW_FILE=$(ls -t "$SESSIONS_DIR"/session-*.md "$SESSIONS_DIR"/interlude-*.md 2>/dev/null | head -1)

if [ -z "$NEW_FILE" ]; then
  echo "Error: No session files found in $SESSIONS_DIR"
  exit 1
fi

# Extract title and slug (same logic as the workflow)
TITLE=$(grep -m1 '^title:' "$NEW_FILE" | sed 's/^title: *"*//;s/"*$//')
SLUG=$(basename "$NEW_FILE" .md)
URL="https://moonfallsessions.com/sessions/$SLUG/"

echo "Session file: $NEW_FILE"
echo "Title:        $TITLE"
echo "Slug:         $SLUG"
echo "URL:          $URL"
echo ""
echo "Message:      New session posted: **$TITLE** - $URL"
echo ""

if [ "$DRY_RUN" = true ]; then
  echo "(dry run — not posting to Discord)"
  exit 0
fi

if [ -z "${DISCORD_WEBHOOK_URL:-}" ]; then
  echo "Error: DISCORD_WEBHOOK_URL environment variable is not set"
  echo "Usage: DISCORD_WEBHOOK_URL=\"https://discord.com/api/webhooks/...\" $0"
  exit 1
fi

echo "Posting to Discord..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Content-Type: application/json" \
  -d "{\"content\": \"New session posted: **$TITLE** - $URL\"}" \
  "$DISCORD_WEBHOOK_URL")

if [ "$HTTP_CODE" = "204" ] || [ "$HTTP_CODE" = "200" ]; then
  echo "Success! (HTTP $HTTP_CODE)"
else
  echo "Failed (HTTP $HTTP_CODE)"
  exit 1
fi
