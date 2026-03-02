#!/usr/bin/env python3
"""
CI orchestration script for Adventure Archivist GitHub Actions pipeline.

Subcommands:
  detect       - Find newest unprocessed Drive file; write env vars to $GITHUB_ENV
  download     - Download source video from Drive to workspace/
  extract      - ffmpeg: MP3 + SRT from workspace/source_video.*
  release      - Create GitHub release with MP3 on topherhooper/omelas-stories
  update-feed  - Clone omelas-stories, add episode to feed.xml, push
  open-pr      - Push branch + open PR on moonfall-docs with SRT in transcripts_raw/

All configuration comes from environment variables (no config.json dependency).
"""

import json
import os
import re
import subprocess
import sys
import tempfile  # used by cmd_update_feed
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import formatdate
from pathlib import Path
from time import mktime


# ── Paths ──────────────────────────────────────────────────────────────────

WORKSPACE = Path("workspace")
METADATA_FILE = WORKSPACE / "metadata.json"
REGISTRY_FILE = Path("data/episodes.json")


# ── Env helpers ────────────────────────────────────────────────────────────

def env(key, required=True):
    """Get an environment variable, raising if required and missing."""
    val = os.environ.get(key, "").strip()
    if required and not val:
        print(f"ERROR: Required env var {key} is not set.", file=sys.stderr)
        sys.exit(1)
    return val


def write_github_env(key, value):
    """Append KEY=VALUE to $GITHUB_ENV so subsequent steps see it."""
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a") as f:
            f.write(f"{key}={value}\n")
    # Also export into the current process so later functions can read it.
    os.environ[key] = value
    print(f"  {key}={value}")


# ── Episode registry ──────────────────────────────────────────────────────

def load_registry():
    """Load the episode registry, or return empty dict."""
    if REGISTRY_FILE.exists():
        return json.loads(REGISTRY_FILE.read_text())
    return {}


def save_registry(registry):
    """Write the registry back to disk."""
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(registry, indent=2) + "\n")


def mark_stage(episode_number, stage):
    """Record that a stage completed for an episode."""
    registry = load_registry()
    ep = str(episode_number)
    if ep not in registry:
        registry[ep] = {"drive_file_id": None, "session_date": None, "stages": {}}
    registry[ep]["stages"][stage] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    save_registry(registry)
    print(f"  Registry: marked {stage} complete for episode {episode_number}")


def stage_done(episode_number, stage):
    """Check if a stage is already recorded as complete."""
    registry = load_registry()
    ep = str(episode_number)
    return ep in registry and stage in registry[ep].get("stages", {})


# ── Date parsing ────────────────────────────────────────────────────────────

def extract_date_from_filename(filename):
    """Extract date from filename like 'DnD - 2026_01_23.mp4'."""
    match = re.search(r"(\d{4})[/_-](\d{2})[/_-](\d{2})", filename)
    if match:
        year, month, day = match.groups()
        return datetime(int(year), int(month), int(day))
    return None


# ── Google Drive auth (service account) ────────────────────────────────────

def get_drive_service():
    """Build a Drive service using service account key from env."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    key_json = env("GOOGLE_SERVICE_ACCOUNT_KEY")
    key_data = json.loads(key_json)

    scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    creds = service_account.Credentials.from_service_account_info(key_data, scopes=scopes)
    return build("drive", "v3", credentials=creds)


# ── Subcommand: detect ─────────────────────────────────────────────────────

def cmd_detect():
    """
    Default: grab the most recent Drive file and assign the next episode number.
    Skips if that episode is already published.
    With overrides (DRIVE_FILE_ID, EPISODE_NUMBER, SESSION_DATE): use those
    exact values — this is how backfill works.
    Writes EPISODE_NUMBER, DRIVE_FILE_ID, SESSION_DATE to $GITHUB_ENV.
    Writes SKIP=true if nothing new.
    """
    print("=== detect ===")

    # --- Resolve overrides first ---
    file_id_override = env("DRIVE_FILE_ID", required=False)
    episode_override = env("EPISODE_NUMBER", required=False)
    date_override = env("SESSION_DATE", required=False)

    # --- Get published releases from omelas-stories ---
    print("Fetching published releases from topherhooper/omelas-stories...")
    result = subprocess.run(
        ["gh", "release", "list", "--repo", "topherhooper/omelas-stories",
         "--limit", "200", "--json", "tagName"],
        capture_output=True, text=True
    )
    published_tags = set()
    if result.returncode == 0 and result.stdout.strip():
        releases = json.loads(result.stdout)
        for r in releases:
            tag = r.get("tagName", "")
            if tag.startswith("v"):
                try:
                    published_tags.add(int(tag[1:]))
                except ValueError:
                    pass
    print(f"  Published episodes: {sorted(published_tags)}")

    # --- Determine episode number ---
    if episode_override:
        episode_number = int(episode_override)
        print(f"  Episode override: {episode_number}")
    else:
        episode_number = max(published_tags) + 1 if published_tags else 1
        print(f"  Auto-detected episode: {episode_number}")

    # --- Short-circuit if file_id override given ---
    if file_id_override:
        print(f"  Drive file ID override: {file_id_override}")
        drive_file_id = file_id_override

        if not date_override:
            # Need to fetch filename to extract date
            service = get_drive_service()
            meta = service.files().get(fileId=drive_file_id, fields="name").execute()
            filename = meta["name"]
            print(f"  Filename: {filename}")
            d = extract_date_from_filename(filename)
            session_date = d.strftime("%Y-%m-%d") if d else datetime.now().strftime("%Y-%m-%d")
        else:
            session_date = date_override

        # Register override episode
        registry = load_registry()
        ep_key = str(episode_number)
        if ep_key not in registry:
            registry[ep_key] = {"drive_file_id": drive_file_id, "session_date": session_date, "stages": {}}
        save_registry(registry)

        print("Writing env vars:")
        write_github_env("EPISODE_NUMBER", str(episode_number))
        write_github_env("DRIVE_FILE_ID", drive_file_id)
        write_github_env("SESSION_DATE", session_date)
        return

    # --- Auto-detect: grab most recent Drive file, assign next episode ---
    drive_folder_id = env("DRIVE_FOLDER_ID")
    print(f"Scanning Drive folder {drive_folder_id}...")
    service = get_drive_service()

    result = service.files().list(
        q=f"'{drive_folder_id}' in parents and mimeType contains 'video/' and trashed = false",
        orderBy="modifiedTime desc",
        pageSize=1,
        fields="files(id, name, modifiedTime)"
    ).execute()

    files = result.get("files", [])
    if not files:
        print("  No video files found in Drive folder.")
        write_github_env("SKIP", "true")
        return

    newest = files[0]
    print(f"  Most recent file: {newest['name']}")

    # Check if this file is already fully processed
    registry = load_registry()
    for ep, data in registry.items():
        if data.get("drive_file_id") == newest["id"]:
            stages = data.get("stages", {})
            if "open-pr" in stages:
                print(f"  File already fully processed as episode {ep} — nothing to do.")
                write_github_env("SKIP", "true")
                return
            else:
                # Partially processed — resume from where we left off
                print(f"  File partially processed as episode {ep} — resuming.")
                episode_number = int(ep)
                break

    d = extract_date_from_filename(newest["name"])
    if d is None:
        print(f"  Could not parse date from filename — skipping.")
        write_github_env("SKIP", "true")
        return

    session_date = date_override if date_override else d.strftime("%Y-%m-%d")

    # Register this episode
    ep_key = str(episode_number)
    if ep_key not in registry:
        registry[ep_key] = {"drive_file_id": newest["id"], "session_date": session_date, "stages": {}}
    save_registry(registry)

    print(f"  Selected: {newest['name']} → episode {episode_number}, date {session_date}")
    print("Writing env vars:")
    write_github_env("EPISODE_NUMBER", str(episode_number))
    write_github_env("DRIVE_FILE_ID", newest["id"])
    write_github_env("SESSION_DATE", session_date)


# ── Subcommand: download ────────────────────────────────────────────────────

def cmd_download():
    """Download source video from Drive to workspace/source_video.{ext}."""
    print("=== download ===")
    from googleapiclient.http import MediaIoBaseDownload

    drive_file_id = env("DRIVE_FILE_ID")
    episode_number = env("EPISODE_NUMBER")
    session_date = env("SESSION_DATE")

    if stage_done(episode_number, "download"):
        if METADATA_FILE.exists():
            print(f"  Already done — skipping download.")
            return
        else:
            print(
                "  Warning: download stage already recorded but metadata.json is missing. "
                "Re-running download to regenerate metadata.",
                file=sys.stderr,
            )

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    service = get_drive_service()

    # Get metadata
    meta = service.files().get(fileId=drive_file_id, fields="name,size").execute()
    filename = meta["name"]
    file_size = int(meta.get("size", 0))
    ext = Path(filename).suffix or ".mp4"

    print(f"  File: {filename} ({file_size / (1024*1024):.1f} MB)")

    # Infer session_date from filename if not provided
    resolved_date = session_date
    if not resolved_date:
        d = extract_date_from_filename(filename)
        resolved_date = d.strftime("%Y-%m-%d") if d else datetime.now().strftime("%Y-%m-%d")
        write_github_env("SESSION_DATE", resolved_date)

    source_path = WORKSPACE / f"source_video{ext}"
    print(f"  Downloading to {source_path}...")

    request = service.files().get_media(fileId=drive_file_id)
    with open(source_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f"  Progress: {int(status.progress() * 100)}%", end="\r")
    print(f"\n  Downloaded: {source_path}")

    # Write metadata for subsequent steps
    metadata = {
        "original_filename": filename,
        "source_path": str(source_path),
        "episode_number": int(episode_number),
        "session_date": resolved_date,
    }
    METADATA_FILE.write_text(json.dumps(metadata, indent=2))
    print(f"  Metadata written: {METADATA_FILE}")
    mark_stage(episode_number, "download")


# ── Subcommand: extract ─────────────────────────────────────────────────────

def cmd_extract():
    """Run ffmpeg to produce MP3 + SRT from workspace/source_video.*."""
    print("=== extract ===")

    if not METADATA_FILE.exists():
        print(
            "ERROR: workspace/metadata.json not found. "
            "This usually means the download step has not run or previously failed.\n"
            "Make sure you run `ci_process.py download` (or allow the workflow to run the full sequence),\n"
            "then try extract again.",
            file=sys.stderr,
        )
        sys.exit(1)

    meta = json.loads(METADATA_FILE.read_text())
    source_path = Path(meta["source_path"])
    episode_number = meta["episode_number"]

    if stage_done(episode_number, "extract"):
        print(f"  Already done — skipping extract.")
        return
    session_date = meta["session_date"]

    base_name = f"C4E{episode_number}_{session_date}"
    mp3_path = WORKSPACE / f"{base_name}.mp3"
    srt_path = WORKSPACE / f"{base_name}.srt"

    # Extract audio
    print(f"  Extracting audio → {mp3_path}")
    result = subprocess.run([
        "ffmpeg", "-i", str(source_path),
        "-vn", "-c:a", "libmp3lame", "-b:a", "192k",
        "-y", str(mp3_path)
    ], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: Audio extraction failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    print(f"  Audio saved: {mp3_path}")

    # Extract subtitles (try stream 2, then s:0)
    print(f"  Extracting subtitles → {srt_path}")
    srt_ok = False
    for stream in ["0:2", "0:s:0"]:
        r = subprocess.run([
            "ffmpeg", "-i", str(source_path),
            "-map", stream, "-y", str(srt_path)
        ], capture_output=True, text=True)
        if r.returncode == 0 and srt_path.exists():
            srt_ok = True
            print(f"  Subtitles saved: {srt_path}")
            break
    if not srt_ok:
        print("  Warning: No subtitles found in video.")

    # Update metadata with output paths
    meta["mp3_path"] = str(mp3_path)
    meta["srt_path"] = str(srt_path) if srt_ok else None
    METADATA_FILE.write_text(json.dumps(meta, indent=2))
    mark_stage(episode_number, "extract")


# ── Subcommand: release ─────────────────────────────────────────────────────

def cmd_release():
    """Create GitHub release v{N} with MP3 on topherhooper/omelas-stories."""
    print("=== release ===")

    meta = json.loads(METADATA_FILE.read_text())
    episode_number = meta["episode_number"]

    if stage_done(episode_number, "release"):
        print(f"  Already done — skipping release.")
        return
    session_date = meta["session_date"]
    mp3_path = Path(meta["mp3_path"])
    repo = "topherhooper/omelas-stories"
    tag = f"v{episode_number}"
    title = f"Episode {episode_number} - {session_date}"

    print(f"  Creating release {tag} on {repo}")
    result = subprocess.run([
        "gh", "release", "create", tag,
        "--repo", repo,
        "--title", title,
        "--notes", f"Audio for episode {episode_number}",
        str(mp3_path)
    ], capture_output=True, text=True)

    if result.returncode != 0:
        if "already exists" in result.stderr:
            print(f"  Release {tag} exists — uploading asset with --clobber")
            result = subprocess.run([
                "gh", "release", "upload", tag,
                "--repo", repo,
                "--clobber",
                str(mp3_path)
            ], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"ERROR: {result.stderr}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"ERROR: {result.stderr}", file=sys.stderr)
            sys.exit(1)

    audio_url = (
        f"https://github.com/{repo}/releases/download/{tag}/{mp3_path.name}"
    )
    print(f"  Release URL: {audio_url}")
    meta["audio_url"] = audio_url
    METADATA_FILE.write_text(json.dumps(meta, indent=2))
    mark_stage(episode_number, "release")


# ── Helpers for RSS ─────────────────────────────────────────────────────────

def get_audio_duration(audio_path):
    """Return duration in seconds via ffprobe, or 0 on failure."""
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path)
    ], capture_output=True, text=True)
    try:
        return int(float(result.stdout.strip()))
    except (ValueError, AttributeError):
        return 0


# ── Subcommand: update-feed ─────────────────────────────────────────────────

def cmd_update_feed():
    """Clone omelas-stories, insert episode into feed.xml, push."""
    print("=== update-feed ===")

    meta = json.loads(METADATA_FILE.read_text())
    episode_number = meta["episode_number"]

    if stage_done(episode_number, "update-feed"):
        print(f"  Already done — skipping feed update.")
        return
    session_date_str = meta["session_date"]
    mp3_path = Path(meta["mp3_path"])
    audio_url = meta["audio_url"]
    season = 4  # Could be read from config.json if needed

    omelas_pat = env("OMELAS_PAT")
    repo_slug = "topherhooper/omelas-stories"
    clone_url = f"https://x-access-token:{omelas_pat}@github.com/{repo_slug}.git"

    session_date = datetime.strptime(session_date_str, "%Y-%m-%d")
    date_str = session_date.strftime("%B %d").replace(" 0", " ")
    title = f"C4E{episode_number}: {date_str}"
    pub_date = formatdate(timeval=mktime(session_date.timetuple()), localtime=True)

    file_size = mp3_path.stat().st_size
    duration_secs = get_audio_duration(mp3_path)
    duration_str = (
        f"{duration_secs // 3600}:"
        f"{(duration_secs % 3600) // 60:02d}:"
        f"{duration_secs % 60:02d}"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "omelas-stories"

        print(f"  Cloning {repo_slug}...")
        result = subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, str(repo_path)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"ERROR: Clone failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)

        feed_path = repo_path / "feed.xml"
        if not feed_path.exists():
            print(f"ERROR: feed.xml not found in {repo_slug}", file=sys.stderr)
            sys.exit(1)

        # Register namespaces
        namespaces = {
            "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
            "atom": "http://www.w3.org/2005/Atom",
            "content": "http://purl.org/rss/1.0/modules/content/",
        }
        for prefix, uri in namespaces.items():
            ET.register_namespace(prefix, uri)
        ET.register_namespace("", "")

        tree = ET.parse(feed_path)
        root = tree.getroot()
        channel = root.find("channel")
        if channel is None:
            print("ERROR: No <channel> in feed.xml", file=sys.stderr)
            sys.exit(1)

        # Build item
        item = ET.Element("item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "description").text = title

        enc = ET.SubElement(item, "enclosure")
        enc.set("url", audio_url)
        enc.set("length", str(file_size))
        enc.set("type", "audio/mpeg")

        guid = ET.SubElement(item, "guid")
        guid.set("isPermaLink", "false")
        guid.text = f"omelas-stories-e{episode_number}"

        ET.SubElement(item, "pubDate").text = pub_date

        ns = "http://www.itunes.com/dtds/podcast-1.0.dtd"
        ET.SubElement(item, f"{{{ns}}}title").text = title
        ET.SubElement(item, f"{{{ns}}}episode").text = str(episode_number)
        ET.SubElement(item, f"{{{ns}}}season").text = str(season)
        ET.SubElement(item, f"{{{ns}}}duration").text = duration_str
        ET.SubElement(item, f"{{{ns}}}explicit").text = "false"

        # Insert before existing items
        first_item = channel.find("item")
        if first_item is not None:
            channel.insert(list(channel).index(first_item), item)
        else:
            channel.append(item)

        # Update lastBuildDate
        last_build = channel.find("lastBuildDate")
        if last_build is not None:
            last_build.text = formatdate(localtime=True)

        tree.write(feed_path, encoding="UTF-8", xml_declaration=True)
        print(f"  feed.xml updated")

        # Configure git identity for CI
        subprocess.run(
            ["git", "config", "user.email", "actions@github.com"],
            cwd=repo_path, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "GitHub Actions"],
            cwd=repo_path, capture_output=True
        )

        subprocess.run(["git", "add", "feed.xml"], cwd=repo_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"Add episode {episode_number}: {title}"],
            cwd=repo_path, capture_output=True
        )

        print(f"  Pushing...")
        result = subprocess.run(
            ["git", "push"],
            cwd=repo_path, capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"ERROR: Push failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)

    print(f"  RSS feed updated: https://topherhooper.github.io/omelas-stories/feed.xml")
    mark_stage(episode_number, "update-feed")


# ── Subcommand: open-pr ─────────────────────────────────────────────────────

def cmd_open_pr():
    """
    Add SRT to transcripts_raw/ in the current checkout (moonfall-docs),
    push a new branch, and open a PR against main.
    moonfall-docs generate-session.yml triggers on merge.
    Uses GITHUB_TOKEN (auto-provided in Actions) — no separate PAT needed.
    """
    print("=== open-pr ===")

    meta = json.loads(METADATA_FILE.read_text())
    episode_number = meta["episode_number"]

    if stage_done(episode_number, "open-pr"):
        print(f"  Already done — skipping PR.")
        return
    session_date_str = meta["session_date"]
    srt_path = meta.get("srt_path")

    if not srt_path or not Path(srt_path).exists():
        print("  No SRT file found — skipping notes PR.")
        return

    srt_file = Path(srt_path)
    branch = f"srt/episode-{episode_number}"

    # Configure git identity (CI environment)
    subprocess.run(
        ["git", "config", "user.email", "actions@github.com"],
        capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "GitHub Actions"],
        capture_output=True
    )

    # Create branch from current HEAD
    result = subprocess.run(
        ["git", "checkout", "-b", branch],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ERROR: Branch creation failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Copy SRT into transcripts_raw/
    transcripts_dir = Path("transcripts_raw")
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    dest = transcripts_dir / srt_file.name
    dest.write_bytes(srt_file.read_bytes())
    print(f"  Copied {srt_file.name} → transcripts_raw/")

    subprocess.run(["git", "add", str(dest)], capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", f"Add SRT for Episode {episode_number}"],
        capture_output=True
    )

    print(f"  Pushing branch {branch}...")
    result = subprocess.run(
        # push with upstream so subsequent git commands know about this branch
        ["git", "push", "--set-upstream", "origin", branch],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ERROR: Push failed: {result.stderr}", file=sys.stderr)
        # fall through so we still try to checkout main below
        sys.exit(1)

    # Open PR — gh uses GH_TOKEN from the environment automatically
    pr_title = f"Add SRT for Episode {episode_number}"
    pr_body = (
        f"Session {episode_number} ({session_date_str}) — "
        f"merge triggers automated notes generation and site deploy."
    )
    print(f"  Opening PR: {pr_title}")
    try:
        result = subprocess.run([
            "gh", "pr", "create",
            "--title", pr_title,
            "--body", pr_body,
            "--head", branch,
            "--base", "main",
        ], capture_output=True, text=True)
        if result.returncode != 0:
            # improve diagnostics for the common permission failure
            stderr = result.stderr or ""
            if "createPullRequest" in stderr or "not permitted" in stderr:
                print(
                    "ERROR: PR creation failed due to insufficient token permissions.\n"
                    "Make sure the token provided in GH_TOKEN has rights to create pull requests\n"
                    "or adjust the repository setting \"Allow GitHub Actions to create and approve \"\n"
                    "pull requests. You can also provide a personal access token via a secret.\n",
                    file=sys.stderr,
                )
            print(f"ERROR: PR creation failed: {stderr}", file=sys.stderr)
            sys.exit(1)
        pr_url = result.stdout.strip()
        print(f"  PR opened: {pr_url}")
        mark_stage(episode_number, "open-pr")
    finally:
        # always return to main branch so later steps (like registry commit) run on
        # the expected branch; ignore failures since we're already in CI.
        subprocess.run(["git", "checkout", "main"], capture_output=True)


# ── Entry point ─────────────────────────────────────────────────────────────

SUBCOMMANDS = {
    "detect": cmd_detect,
    "download": cmd_download,
    "extract": cmd_extract,
    "release": cmd_release,
    "update-feed": cmd_update_feed,
    "open-pr": cmd_open_pr,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in SUBCOMMANDS:
        print(f"Usage: ci_process.py <subcommand>")
        print(f"Subcommands: {', '.join(SUBCOMMANDS)}")
        sys.exit(1)

    subcommand = sys.argv[1]
    SUBCOMMANDS[subcommand]()


if __name__ == "__main__":
    main()
