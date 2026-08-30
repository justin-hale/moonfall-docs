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
import shutil
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


def mark_stage(episode_number, stage, value=None):
    """Record that a stage completed for an episode.

    If *value* is given it is stored directly (e.g. a URL or file path).
    Otherwise a UTC timestamp is used as a fallback.
    """
    registry = load_registry()
    ep = str(episode_number)
    if ep not in registry:
        registry[ep] = {"drive_file_id": None, "session_date": None, "stages": {}}
    registry[ep]["stages"][stage] = value or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
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
    # fetch tag names *and* release names (title includes the session
    # date) so we can avoid creating a new release for a file whose date
    # already exists downstream.  The `name` field looks like
    # "Episode 12 - 2026-02-27".
    result = subprocess.run(
        ["gh", "release", "list", "--repo", "topherhooper/omelas-stories",
         "--limit", "200", "--json", "tagName,name"],
        capture_output=True, text=True
    )
    published_tags = set()
    existing_dates = set()
    if result.returncode == 0 and result.stdout.strip():
        releases = json.loads(result.stdout)
        for r in releases:
            tag = r.get("tagName", "")
            if tag.startswith("v"):
                try:
                    published_tags.add(int(tag[1:]))
                except ValueError:
                    pass
            name = r.get("name", "")
            # extract date from title using same regex as filenames
            d = extract_date_from_filename(name)
            if d:
                existing_dates.add(d.strftime("%Y-%m-%d"))
    print(f"  Published episodes: {sorted(published_tags)}")
    if existing_dates:
        print(f"  Existing session dates: {sorted(existing_dates)}")

    # --- Determine episode to process ---
    # If an episode override was provided, use it. Otherwise prefer the
    # most recent published release that isn't fully processed yet. This
    # allows repeated runs to catch up older unprocessed releases one by
    # one. If no suitable published release is found, fall back to the
    # auto-detect behavior (newest Drive file → next episode number).
    episode_number = None
    if episode_override:
        episode_number = int(episode_override)
        print(f"  Episode override: {episode_number}")
    else:
        # Find the most recent date in docs/transcripts/
        max_transcript_date = None
        transcripts_dir = os.path.join(os.getcwd(), "docs", "transcripts")
        if os.path.isdir(transcripts_dir):
            for entry in os.listdir(transcripts_dir):
                # Match folder names like "2026-02-06"
                d = extract_date_from_filename(entry)
                if d:
                    date_str = d.strftime("%Y-%m-%d")
                    if max_transcript_date is None or date_str > max_transcript_date:
                        max_transcript_date = date_str
        if max_transcript_date:
            print(f"  Most recent transcript date: {max_transcript_date}")

        # Build a list of releases with parsed dates and tag numbers
        releases_with_dates = []
        if result.returncode == 0 and result.stdout.strip():
            for r in json.loads(result.stdout):
                tag = r.get("tagName", "")
                name = r.get("name", "")
                if not tag.startswith("v"):
                    continue
                try:
                    tagnum = int(tag[1:])
                except ValueError:
                    continue
                d = extract_date_from_filename(name)
                date_str = d.strftime("%Y-%m-%d") if d else None
                # Only include releases after the most recent transcript date
                if max_transcript_date and date_str and date_str <= max_transcript_date:
                    continue
                releases_with_dates.append({"tag": tagnum, "name": name, "date": date_str})

        # Sort by release date ascending (oldest releases first). When date
        # is missing, fall back to tag number so ordering is deterministic.
        releases_with_dates.sort(key=lambda x: (x.get("date") or "", x["tag"]))

        # Find the first release that isn't fully processed according to registry
        registry = load_registry()
        selected_release = None
        for rel in releases_with_dates:
            ep = str(rel["tag"])
            stages = registry.get(ep, {}).get("stages", {})
            if "open-pr" in stages:
                continue
            # choose this release to attempt processing
            selected_release = rel
            episode_number = rel["tag"]
            print(f"  Selected published release to process: v{episode_number} ({rel['name']})")
            break

        if episode_number is None:
            # No unprocessed published releases — check registry for episodes
            # that haven't been released yet (e.g. episodes with drive_file_id
            # but empty stages).
            registry = registry if 'registry' in locals() else load_registry()
            for ep_key, ep_data in sorted(registry.items(), key=lambda x: x[0]):
                stages = ep_data.get("stages", {})
                if not stages.get("release"):
                    episode_number = int(ep_key)
                    print(f"  Found unprocessed episode in registry: {episode_number} ({ep_data.get('session_date')})")
                    # If registry already has drive_file_id and session_date,
                    # short-circuit directly — no need to scan Drive.
                    if ep_data.get("drive_file_id") and ep_data.get("session_date"):
                        print("Writing env vars:")
                        write_github_env("EPISODE_NUMBER", str(episode_number))
                        write_github_env("DRIVE_FILE_ID", ep_data["drive_file_id"])
                        write_github_env("SESSION_DATE", ep_data["session_date"])
                        return
                    break

        if episode_number is None:
            print(f"  No unprocessed episodes in registry — will scan Drive for new recordings.")
        selected_release = selected_release if 'selected_release' in locals() else None

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
        pageSize=200,  # fetch more files so we can search for matches
        fields="files(id, name, modifiedTime)"
    ).execute()

    files = result.get("files", [])
    if not files:
        print("  No video files found in Drive folder.")
        write_github_env("SKIP", "true")
        return

    # If we selected a specific published release, try to find a Drive file
    # matching its date. If not found, skip this release and don't process anything.
    newest = None
    if 'selected_release' in locals() and selected_release and selected_release.get("date"):
        target_date = selected_release.get("date")
        print(f"  Looking for Drive file matching release date {target_date}...")
        for f in files:
            d = extract_date_from_filename(f.get("name", ""))
            if d and d.strftime("%Y-%m-%d") == target_date:
                newest = f
                print(f"  Found matching file: {f['name']}")
                break
        if not newest:
            print(f"  No Drive file found for release {selected_release.get('name')} — skipping.")
            write_github_env("SKIP", "true")
            return
    else:
        # No selected release; use the most recent file
        newest = files[0]
    
    print(f"  Using file: {newest['name']}")

    # Check if this file is already in the registry
    registry = load_registry()
    for ep, data in registry.items():
        if data.get("drive_file_id") == newest["id"]:
            stages = data.get("stages", {})
            if stages.get("release") and not stages.get("release-deleted"):
                print(f"  File already processed as episode {ep} — nothing to do.")
                write_github_env("SKIP", "true")
                return
            else:
                # Partially processed or release was deleted and needs recreation
                # — resume from where we left off.
                print(f"  File partially processed as episode {ep} — resuming.")
                episode_number = int(ep)
                break

    d = extract_date_from_filename(newest["name"])
    if d is None:
        print(f"  Could not parse date from filename — skipping.")
        write_github_env("SKIP", "true")
        return

    session_date = date_override if date_override else d.strftime("%Y-%m-%d")

    # Check if this session date already exists in the registry
    if episode_number is None:
        for ep, data in registry.items():
            if data.get("session_date") == session_date:
                stages = data.get("stages", {})
                if stages.get("release"):
                    print(f"  Session date {session_date} already fully processed as episode {ep} — nothing to do.")
                    write_github_env("SKIP", "true")
                    return
                else:
                    print(f"  Session date {session_date} partially processed as episode {ep} — resuming.")
                    episode_number = int(ep)
                    break

    # Assign next episode number for a brand new recording
    if episode_number is None:
        existing_nums = [int(k) for k in registry.keys()]
        episode_number = max(existing_nums) + 1 if existing_nums else 1
        print(f"  New episode detected: assigning episode {episode_number}")

    # if we already have a release with this session date, mark that fact
    # and continue so downstream steps (download/extract) can still run.
    # The workflow will use `RELEASE_EXISTS` to avoid creating a duplicate
    # release while still allowing the SRT to be produced and committed.
    if session_date in existing_dates:
        print(f"  Session date {session_date} already released.")
        write_github_env("RELEASE_EXISTS", "true")

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
    mark_stage(episode_number, "download", drive_file_id)


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

    base_name = f"DnD_{session_date}"
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

    # If we extracted subtitles, decide whether to copy them into
    # `transcripts_raw/`. Only copy if there is no existing cleaned
    # transcript in `docs/transcripts/` that matches this session date.
    if srt_ok:
        transcripts_dir = Path("transcripts_raw")
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        dest = transcripts_dir / srt_path.name

        # Look for any file in docs/transcripts whose filename contains the
        # session date (YYYY-MM-DD). If one exists, we assume the cleaned
        # transcript is already present and skip copying into transcripts_raw.
        docs_transcripts = Path("docs") / "transcripts"
        should_copy = True
        if docs_transcripts.exists():
            pattern = session_date
            for f in docs_transcripts.rglob("*"):
                if f.is_file() and pattern in f.name:
                    print(f"  Found existing transcript in docs/transcripts: {f.name}; skipping copy to transcripts_raw")
                    should_copy = False
                    break

        if should_copy:
            try:
                shutil.copy2(srt_path, dest)
                print(f"  Copied subtitles to {dest}")
            except Exception as e:
                print(f"  Warning: failed to copy srt to transcripts_raw: {e}")

    # Update metadata with output paths
    meta["mp3_path"] = str(mp3_path)
    meta["srt_path"] = str(srt_path) if srt_ok else None
    METADATA_FILE.write_text(json.dumps(meta, indent=2))
    mark_stage(episode_number, "extract", mp3_path.name)


# ── Subcommand: release ─────────────────────────────────────────────────────

def cmd_release():
    """Create GitHub release v{N} with MP3 on topherhooper/omelas-stories."""
    print("=== release ===")

    meta = json.loads(METADATA_FILE.read_text())
    episode_number = meta["episode_number"]
    session_date = meta["session_date"]

    # defensive check: if any existing release already uses this date in its
    # title, skip creation to avoid duplicates (same logic as cmd_detect).
    result = subprocess.run([
        "gh", "release", "list", "--repo", "topherhooper/omelas-stories",
        "--limit", "200", "--json", "name"
    ], capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        releases = json.loads(result.stdout)
        for r in releases:
            name = r.get("name", "")
            d = extract_date_from_filename(name)
            if d and d.strftime("%Y-%m-%d") == session_date:
                print(f"  Release for date {session_date} already exists ({name}) — skipping.")
                mark_stage(episode_number, "release", name)
                return

    if stage_done(episode_number, "release"):
        print(f"  Already done — skipping release.")
        return
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
    mark_stage(episode_number, "release", audio_url)
    # signal that we created a release in this run so cleanup knows to
    # delete it if something fails later
    write_github_env("RELEASE_CREATED_THIS_RUN", "true")


def cmd_delete_release():
    """Remove the GitHub release (and its tag) for the current episode.

    This is intended to be called from the CI workflow if a later step fails
    after we've already created the release, so the pipeline can roll back
    the erroneous artifact.  We use `gh release delete` which handles both
    the release and the associated git tag.
    """
    print("=== delete-release ===")
    meta = json.loads(METADATA_FILE.read_text())
    episode_number = meta["episode_number"]
    repo = "topherhooper/omelas-stories"
    tag = f"v{episode_number}"

    print(f"  Deleting release {tag} on {repo}")
    result = subprocess.run([
        "gh", "release", "delete", tag,
        "--repo", repo,
        "--yes"
    ], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"WARNING: could not delete release: {result.stderr}", file=sys.stderr)
    else:
        print(f"  Release {tag} deleted")
        mark_stage(episode_number, "release-deleted", tag)


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
    title = f"Episode {episode_number}: {date_str}"
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
    mark_stage(episode_number, "update-feed", audio_url)


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

    # GH CLI requires GH_TOKEN; if the workflow didn't set it copy from
    # GITHUB_TOKEN (always available in Actions) so the first gh call works.
    if not os.environ.get("GH_TOKEN"):
        github_token = os.environ.get("GITHUB_TOKEN")
        if github_token:
            os.environ["GH_TOKEN"] = github_token

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

    # Create (or reset) branch from current HEAD.
    # -B resets the branch if it already exists locally, which happens when a
    # previous CI run created the branch but failed before marking the stage done.
    result = subprocess.run(
        ["git", "checkout", "-B", branch],
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
        # --force handles the case where a previous CI run already pushed this
        # branch but failed before marking the stage done (would otherwise be
        # rejected with "fetch first").
        ["git", "push", "--force", "--set-upstream", "origin", branch],
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

    def run_pr(env=None):
        return subprocess.run(
            [
                "gh", "pr", "create",
                "--title", pr_title,
                "--body", pr_body,
                "--head", branch,
                "--base", "main",
            ],
            capture_output=True,
            text=True,
            env=env,
        )

    try:
        print(f"  Opening PR: {pr_title}")
        result = run_pr()
        if result.returncode != 0:
            stderr = result.stderr or ""
            if "Resource not accessible by personal access token" in stderr:
                print(
                    "ERROR: The token in GH_TOKEN cannot access this repository.\n"
                    "If you've overridden GH_TOKEN with a PAT, make sure the token has full repo\n"
                    "permissions for this repo. Otherwise the workflow's built-in GITHUB_TOKEN\n"
                    "might work once the repository setting to allow Actions‑created PRs is\n"
                    "enabled.\n",
                    file=sys.stderr,
                )
                # attempt retry without GH_TOKEN so gh falls back to GITHUB_TOKEN
                print("  Retrying PR creation without GH_TOKEN…")
                env = os.environ.copy()
                env.pop("GH_TOKEN", None)
                retry = run_pr(env=env)
                if retry.returncode == 0:
                    pr_url = retry.stdout.strip()
                    print(f"  PR opened: {pr_url}")
                    mark_stage(episode_number, "open-pr", pr_url)
                    result = None
                else:
                    stderr = retry.stderr or ""
                    print(f"ERROR: Retry also failed: {stderr}", file=sys.stderr)
                    result = retry
            elif "createPullRequest" in stderr or "not permitted" in stderr:
                print(
                    "ERROR: PR creation failed due to insufficient token permissions.\n"
                    "Make sure the token provided in GH_TOKEN has rights to create pull requests\n"
                    "or adjust the repository setting \"Allow GitHub Actions to create and approve \"\n"
                    "pull requests.\n",
                    file=sys.stderr,
                )
            if result:
                print(f"ERROR: PR creation failed: {stderr}", file=sys.stderr)
                sys.exit(1)
        else:
            pr_url = result.stdout.strip()
            print(f"  PR opened: {pr_url}")
            mark_stage(episode_number, "open-pr", pr_url)
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
    # cleanup helper, invoked by workflow on failure
    "delete-release": cmd_delete_release,
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
