#!/usr/bin/env python3
"""
Test script to verify the Anthropic API setup works correctly.
This tests the core functionality without processing a full transcript.
"""

import os
import sys
from pathlib import Path

try:
    import anthropic
    print("✓ anthropic package installed")
except ImportError:
    print("✗ anthropic package not installed. Run: pip install anthropic")
    sys.exit(1)

# Check for API key
if not os.getenv("ANTHROPIC_API_KEY"):
    print("✗ ANTHROPIC_API_KEY environment variable not set")
    print("  Set it with: export ANTHROPIC_API_KEY='your-key-here'")
    sys.exit(1)
print("✓ ANTHROPIC_API_KEY found")

# Test API connection with a simple call
try:
    client = anthropic.Anthropic()
    print("✓ Anthropic client initialized")
    
    # Test with Haiku (cheap model)
    print("\nTesting API with Haiku...")
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",  # same model automate_session.py uses for summarisation
        max_tokens=100,
        messages=[{"role": "user", "content": "Say 'API test successful' and nothing else."}]
    )
    print(f"  Response: {response.content[0].text}")
    print("✓ Haiku API call successful")
    
except anthropic.APIError as e:
    print(f"✗ API error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"✗ Unexpected error: {e}")
    sys.exit(1)

# Check file structure
project_root = Path(__file__).parent.parent
checks = [
    (project_root / "data" / "campaign-kb.md", "Campaign knowledge base"),
    (project_root / "data" / "campaign-state.md", "Campaign state"),
    (project_root / "docs" / "sessions", "Sessions directory"),
    (project_root / "docs" / "transcripts", "Transcripts directory"),
    (project_root / "scripts" / "automate_session.py", "Main automation script"),
]

print("\nChecking file structure...")
all_good = True
for path, desc in checks:
    if path.exists():
        print(f"✓ {desc} exists: {path.relative_to(project_root)}")
    else:
        print(f"✗ {desc} missing: {path.relative_to(project_root)}")
        all_good = False

if all_good:
    print("\n✅ All checks passed! The system is ready.")
    print("\nEstimated cost per recap with new setup:")
    print("  - Chunk summarization (Haiku): ~$0.01-0.02")
    print("  - Recap generation (Sonnet): ~$0.08-0.15")
    print("  - Total: ~$0.10-0.20 (down from $0.75-1.00)")
    print("\nTo run a test generation:")
    print("  python scripts/automate_session.py --no-clean --no-generate")
    print("\nTo run a full generation (costs money):")
    print("  python scripts/automate_session.py --no-clean")
else:
    print("\n⚠ Some files are missing. Please check the setup.")
    sys.exit(1)