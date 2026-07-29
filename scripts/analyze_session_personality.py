#!/usr/bin/env python3
"""
LLM Personality Analyzer for Moonfall sessions.

For each session transcript, scores every present player (DM included) on six
D&D-flavored personality axes (1-20, evidence quote required per axis) and
picks session superlatives (MVP moment, best joke, most chaotic call,
decision driver). Results are cached per session date in
data/personality-cache/<date>.json and merged into the dataset by
scripts/extract_session_stats.py.

The rubric below is FROZEN — scores are only comparable across sessions if
every session is scored against the same rubric. If you change it, rescore
everything with --force.

Usage:
    python3 scripts/analyze_session_personality.py --all [--local]
    python3 scripts/analyze_session_personality.py --date 2026-07-17 [--local]
    python3 scripts/analyze_session_personality.py --all --force

Backends (same convention as automate_session.py):
    default : direct Anthropic API (requires ANTHROPIC_API_KEY + anthropic pkg)
    --local : route calls through the local `claude` CLI, billed against your
              Claude subscription instead of metered API tokens.
If ANTHROPIC_API_KEY is absent and --local wasn't passed, the script falls
back to the CLI automatically (with a notice).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import extract_session_stats as ess  # noqa: E402

CACHE_SCHEMA_VERSION = "1.0"
# User-selected model for personality scoring: cheap, fast, and rubric
# scoring is well within its wheelhouse. 200K context fits every transcript.
MODEL = "claude-haiku-4-5"
CACHE_DIR = ess.PERSONALITY_CACHE_DIR

AXES = ["chaos", "heroism", "comedy", "immersion", "strategy", "curiosity"]

RUBRIC = """\
Score each player on six axes, 1-20, based ONLY on what they said and did in
THIS session's transcript. Anchors (do not drift from these):

CHAOS — appetite for mayhem and derailment.
  1 = always cautious and by-the-book; 10 = occasional wild impulses or risky
  detours; 20 = actively derails plans, embraces chaos, causes mayhem for fun.
HEROISM — selflessness and bravery.
  1 = self-interested or avoids danger; 10 = does the right thing when it's
  convenient; 20 = takes real personal risk to protect others or the mission.
COMEDY — humor generated at the table (in or out of character).
  1 = played it straight all night; 10 = a few solid jokes or funny moments;
  20 = repeatedly had the table laughing, comedic engine of the session.
IMMERSION — in-character engagement and roleplay depth.
  1 = mostly out-of-character table talk; 10 = solid in-character play in key
  scenes; 20 = deep sustained roleplay, voices, character-driven decisions.
STRATEGY — tactical and long-term thinking.
  1 = acts without planning; 10 = sensible tactics when prompted; 20 = drives
  the plan, thinks ahead, uses resources and information cleverly.
CURIOSITY — investigation and engagement with the world.
  1 = passive, waits to be led; 10 = asks questions when something is odd;
  20 = relentlessly pokes at lore, NPCs, mysteries, and shiny objects.

Rules:
- Score ONLY the players listed as present. The DM (Topher) is scored too —
  judge his chaos/comedy/etc. as a performer and narrator.
- Every score MUST have a short verbatim evidence quote from the transcript
  (the player's own words, or a short exchange). No quote, no score.
- Judge each axis independently. Use the full 1-20 range; 10 is a normal
  engaged player, not a failing grade.
- Speech-to-text is messy: quotes may have transcription noise. Prefer quotes
  that are coherent. Never invent or clean up quotes beyond trimming."""

PROMPT_TEMPLATE = """You are analyzing one session of a D&D campaign ("Moonfall") to score player
personalities. The transcript below has canonical speaker names.

{rubric}

Players present in this session (score exactly these, no others):
{players}

Also pick session superlatives (each with a verbatim quote):
- mvp: the player with the session's most valuable/heroic/clutch moment
- best_joke: the player who landed the funniest line
- most_chaotic: the player behind the most chaotic decision
- decision_driver: the player who most drove the group's decisions (no quote)

Return ONLY a JSON object, no markdown fences, exactly this shape:
{{
  "players": {{
    "<player name>": {{
      "scores": {{"chaos": N, "heroism": N, "comedy": N, "immersion": N, "strategy": N, "curiosity": N}},
      "evidence": {{"chaos": "quote", "heroism": "quote", "comedy": "quote", "immersion": "quote", "strategy": "quote", "curiosity": "quote"}}
    }}
  }},
  "superlatives": {{
    "mvp": {{"player": "<name>", "quote": "..."}},
    "best_joke": {{"player": "<name>", "quote": "..."}},
    "most_chaotic": {{"player": "<name>", "quote": "..."}},
    "decision_driver": "<name>"
  }}
}}

TRANSCRIPT:
{transcript}"""

SYSTEM_PROMPT = (
    "You are a precise, fair judge of tabletop RPG table dynamics. "
    "You output only valid JSON — no prose, no markdown fences."
)


class BackendError(Exception):
    pass


def call_api(system, user_content, timeout):
    try:
        import anthropic
    except ImportError:
        raise BackendError("anthropic package not installed (pip install anthropic), "
                           "or use --local for the claude CLI backend")
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        timeout=timeout,
    )
    return response.content[0].text


def call_cli(system, user_content, timeout):
    """Route through the local `claude` CLI (subscription billing). Same
    conventions as automate_session.py: no ANTHROPIC_API_KEY in the child env,
    tools disabled, scratch cwd so the repo's CLAUDE.md isn't pulled in."""
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    cmd = [
        "claude", "-p",
        "--output-format", "text",
        "--model", MODEL,
        "--tools", "",
        "--system-prompt", system,
    ]
    try:
        result = subprocess.run(
            cmd, input=user_content, capture_output=True, text=True,
            env=env, cwd=tempfile.gettempdir(), timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise BackendError(f"claude CLI timed out after {timeout}s")
    except FileNotFoundError:
        raise BackendError("`claude` CLI not found on PATH")
    if result.returncode != 0:
        raise BackendError(f"claude CLI exited {result.returncode}: "
                           f"{(result.stderr or '').strip()[:500]}")
    return result.stdout.strip()


def parse_json_response(text):
    """The model is told to return bare JSON; tolerate stray fences/prose."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in response")
    return json.loads(text[start:end + 1])


def validate_result(result, expected_players):
    problems = []
    players = result.get("players")
    if not isinstance(players, dict) or not players:
        return ["missing/empty 'players'"]
    for name, entry in players.items():
        if name not in expected_players:
            problems.append(f"unexpected player {name!r}")
            continue
        scores = entry.get("scores", {})
        evidence = entry.get("evidence", {})
        for axis in AXES:
            score = scores.get(axis)
            if not isinstance(score, (int, float)) or not (1 <= score <= 20):
                problems.append(f"{name}.{axis}: bad score {score!r}")
            if not (evidence.get(axis) or "").strip():
                problems.append(f"{name}.{axis}: missing evidence quote")
    superlatives = result.get("superlatives", {})
    for key in ("mvp", "best_joke", "most_chaotic"):
        value = superlatives.get(key)
        if not isinstance(value, dict) or not value.get("player"):
            problems.append(f"superlatives.{key} malformed")
    return problems


def build_transcript_text(date, tpath, alias_to_canonical, replacements, roster):
    if tpath.suffix == ".json":
        blocks, _, _ = ess.parse_json_transcript(tpath, date, alias_to_canonical, replacements)
    else:
        blocks, _, _ = ess.parse_md_transcript(tpath, date, alias_to_canonical, replacements)
    lines = []
    present = []
    for b in blocks:
        info = roster.get(b["canonical"])
        display = info["display"] if info else b["canonical"]
        if display not in present:
            present.append(display)
        lines.append(f"{display}: {b['text']}")
    return "\n".join(lines), present


def analyze_session(date, tpath, alias_to_canonical, replacements, roster,
                    use_local_cli, timeout):
    transcript_text, present = build_transcript_text(
        date, tpath, alias_to_canonical, replacements, roster)
    prompt = PROMPT_TEMPLATE.format(
        rubric=RUBRIC,
        players="\n".join(f"- {p}" for p in present),
        transcript=transcript_text,
    )
    call = call_cli if use_local_cli else call_api

    last_error = None
    for attempt in range(1, 3):
        raw = call(SYSTEM_PROMPT, prompt, timeout)
        try:
            result = parse_json_response(raw)
        except (ValueError, json.JSONDecodeError) as e:
            last_error = f"attempt {attempt}: unparseable JSON ({e})"
            print(f"    {last_error}; retrying...")
            continue
        problems = validate_result(result, set(present))
        # Drop hallucinated players rather than failing the whole session.
        result["players"] = {k: v for k, v in (result.get("players") or {}).items()
                             if k in present}
        hard_problems = [p for p in problems if "unexpected player" not in p]
        if not hard_problems and result["players"]:
            return result
        last_error = f"attempt {attempt}: validation failed ({'; '.join(hard_problems[:5])})"
        print(f"    {last_error}; retrying...")
    raise BackendError(f"could not get a valid result for {date}: {last_error}")


def main():
    parser = argparse.ArgumentParser(description="Score session personalities via Claude")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Analyze every transcript")
    group.add_argument("--date", help="Analyze one session date (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true", help="Rescore even if cached")
    parser.add_argument("--local", action="store_true",
                        help="Use the local `claude` CLI instead of the API")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Per-call timeout in seconds (default 600)")
    args = parser.parse_args()

    use_local_cli = args.local
    if not use_local_cli and not os.environ.get("ANTHROPIC_API_KEY"):
        print("  ANTHROPIC_API_KEY not set — falling back to the local `claude` CLI backend")
        use_local_cli = True

    alias_to_canonical, replacements = ess.load_campaign_kb_mappings(ess.KB_PATH)
    roster, _, _, _ = ess.load_campaign_entities()

    transcripts = {}
    for path in sorted(ess.TRANSCRIPTS_DIR.glob("*.md")):
        transcripts[path.stem] = path
    for path in sorted(ess.TRANSCRIPTS_DIR.glob("*.json")):
        transcripts[path.stem] = path

    if args.date:
        if args.date not in transcripts:
            print(f"Error: no transcript found for {args.date}")
            raise SystemExit(1)
        dates = [args.date]
    else:
        dates = sorted(transcripts)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    done = skipped = failed = 0
    for i, date in enumerate(dates, 1):
        cache_path = CACHE_DIR / f"{date}.json"
        if cache_path.exists() and not args.force:
            skipped += 1
            continue
        print(f"[{i}/{len(dates)}] Scoring {date} ({transcripts[date].name})...")
        start = time.time()
        try:
            result = analyze_session(date, transcripts[date], alias_to_canonical,
                                     replacements, roster, use_local_cli, args.timeout)
        except BackendError as e:
            print(f"    FAILED: {e}")
            failed += 1
            continue
        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "date": date,
            "model": MODEL,
            "players": result["players"],
            "superlatives": result.get("superlatives", {}),
        }
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        print(f"    done in {time.time() - start:.0f}s "
              f"({len(result['players'])} players scored)")
        done += 1

    print(f"\nScored {done}, cached/skipped {skipped}, failed {failed}.")
    if done or args.force:
        print("Run `python3 scripts/extract_session_stats.py --all` to merge into the dataset.")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
