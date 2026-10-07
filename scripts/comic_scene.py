#!/usr/bin/env python3
"""Turn one moment from a session into a single epic illustration.

Each image is one scene, shown full width under that scene's heading in the
recap, with nothing printed on the art: its title and an optional quote sit
in a band underneath. A session can have up to three. The usual flow writes
`script.json` by hand (or with Claude in a chat) and only uses this script
to draw it:

    python scripts/comic_scene.py --comic session-64-the-launch --draw            # every shot
    python scripts/comic_scene.py --comic session-64-the-launch --draw --shot 2   # just one
    python scripts/comic_scene.py --comic session-64-the-launch --letter-only     # band only
    python scripts/comic_scene.py --portraits Bru Silas  # draw reference portraits
    python scripts/comic_scene.py 64 [--scene "The Launch"]  # auto: Claude scripts it too

Three stages, each of which can be re-run on its own:

1. **Script.** `data/comics/<name>/script.json`: who is in it, a title, an
   optional quote lifted from what was said at the table, and one or more
   `shots`: alternative ways to frame the same instant, each written like a
   director's shot (camera, framing, depth, light). With several shots, every
   one is drawn as a preview; setting `chosen` to a shot's number publishes it. The name is `<recap stem>-<scene heading>`. Written by hand, or by
   Claude (`ANTHROPIC_API_KEY`) in auto mode from the recap and transcript.
2. **Art** (Gemini, `GEMINI_API_KEY`). One 16:9 image per shot, no text in it.
   Every character in it is described from `data/character-sheets.json` and,
   where the group has supplied a portrait, shown to the model as a reference
   image. Raw art is kept losslessly as `data/comics/<name>/art-<shot>.png`,
   so changing the title or quote never costs another generation.
3. **Band** (Pillow, no API). Adds the title, quote and session under the art.
   Image models misspell names, and the name rules in CLAUDE.md are not
   optional, so no text is ever drawn by the model. Each shot gets a preview
   at `data/comics/<name>/preview-<shot>.webp`; the chosen one goes to
   `static/img/comics/<name>.webp` and is embedded in the recap under the
   heading of the scene it shows.

Nothing here publishes on its own: the result is a working-tree change to
review, and the "Draw Comic" workflow commits it to a branch or opens a PR.
"""

import argparse
import json
import os
import re
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))

import recap_postprocess as rp  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = ROOT / "docs" / "sessions"
TRANSCRIPTS_DIR = ROOT / "docs" / "transcripts"
KB_PATH = ROOT / "data" / "campaign-kb.md"
SHEETS_PATH = ROOT / "data" / "character-sheets.json"
COMICS_DATA_DIR = ROOT / "data" / "comics"
COMICS_IMG_DIR = ROOT / "static" / "img" / "comics"
FONTS_DIR = Path(__file__).resolve().parent / "fonts"

SCRIPT_MODEL = "claude-opus-5-5"
# Gemini image model IDs churn; override without a code change.
IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3-pro-image-preview")
IMAGE_SIZE = os.environ.get("GEMINI_IMAGE_SIZE", "2K")
# A per-run ceiling on Gemini image requests, retries included: the backstop
# for the AI Studio spend cap, which Google enforces up to ~10 minutes late.
MAX_IMAGE_REQUESTS = int(os.environ.get("COMIC_MAX_IMAGES", "10"))
# Only for the cost estimate printed at the end. Nano Banana Pro at 1K-2K.
PRICE_PER_IMAGE = float(os.environ.get("GEMINI_PRICE_PER_IMAGE", "0.134"))

# Output geometry (pixels): the art at 16:9, then the band. 2048 wide stays
# sharp on high-density screens at the recap's column width.
PAGE_W = 2048
ART_H = PAGE_W * 9 // 16
SCALE = PAGE_W / 1600
BAND_PAD = round(28 * SCALE)
BAND_BG = "#14110F"

# Sent with every scene so the model stages a shot instead of an inventory.
COMPOSITION = (
    "Composition: stage this as a film director's shot of one peak instant. One clear focal "
    "point, placed off-centre; strong diagonals and leading lines; distinct foreground, "
    "midground and background for depth; the camera exactly as described; one dominant light "
    "source with deep shadows; visible motion and scale. Characters other than the focus may be "
    "small, partly hidden or in silhouette. Never a centred, eye-level, evenly lit product shot."
)


# --------------------------------------------------------------------------
# Script schema
# --------------------------------------------------------------------------

class Quote(BaseModel):
    speaker: str = Field(description="Canonical character name, never a player's name")
    text: str = Field(description="What they said, trimmed from the transcript. 25 words at most")


class SceneImage(BaseModel):
    title: str = Field(description="Short punchy title for the image")
    section: str = Field(description="The recap's ### heading this scene falls under, copied exactly")
    why: str = Field(description="One sentence: why this is the moment worth drawing")
    transcript_evidence: list[str] = Field(
        description="Verbatim transcript lines that show this happened as drawn")
    characters: list[str] = Field(
        description="Everyone visible, using names from the character sheet where they appear there")
    shots: list[str] = Field(
        description="1-3 alternative ways to frame the same instant, each written as a director's shot: "
                    "the instant, camera position/angle/lens, where the focal subject sits, foreground/"
                    "midground/background, light source, motion and scale cues. Do not restate "
                    "appearances from the character sheet. No text in the image")
    chosen: int | None = Field(
        default=None, description="Which shot (1-based) to publish; leave empty to compare previews first")
    quote: Quote | None = Field(
        default=None, description="Optional line shown under the image, verbatim from the transcript")

    def chosen_shot(self):
        """The 1-based shot to publish, or None while previews are being compared."""
        return self.chosen or (1 if len(self.shots) == 1 else None)


SCRIPT_SYSTEM = """\
You turn one moment from a D&D campaign (Moonfall) into a single epic \
illustration that sits under its scene's heading in the session's published \
recap.

You get the session's published recap, its raw transcript, and the character \
sheet the artist works from. Pick the scene (or use the one you are given), \
then the one instant in it that makes the best image: a splash page, not a \
sequence.

The transcript is the source of truth. The recap is a guide to where things \
are, but it has been wrong before; never draw something the transcript does not \
support. Use only in-character play, not table talk about rules or snacks.

The optional quote is what a player or the DM actually said in character, \
trimmed of filler and false starts, never invented. Attribute it to the \
character, never to the player (the roster in the recap's Players Present \
section maps them). Leliana and Helisanna are one woman with two personas: \
name whichever persona is out at that moment.

Spelling is fixed: Bru (never Brew), Elspeth (never Ellsworth or Elizabeth), \
Leliana (never Liliana), Eldoran, Greyport, Astro.

Write each shot for an illustrator who has never heard of the campaign, as \
a director would: the one instant, where the camera is and how it is angled, \
where the focal subject sits in the wide frame, what is in the foreground, \
midground and background, the light, and the cues for motion and scale. Pick \
one or two heroes; everyone else can be small or in silhouette. Write two or \
three genuinely different shots (for example vertigo, heroic low angle, epic \
wide) so the group can choose. Appearances come from the character sheet, so \
name the characters in `characters` instead of describing them again.\
"""


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

def resolve_recap(ref):
    """'64', 'session-64', 'interlude-12', a path, or a moonfallsessions.com URL."""
    stem = str(ref).rstrip("/").split("/")[-1]
    stem = stem[:-3] if stem.endswith(".md") else stem
    if stem.isdigit():
        stem = f"session-{stem}"
    path = SESSIONS_DIR / f"{stem}.md"
    if not path.exists():
        raise SystemExit(f"No recap at {path.relative_to(ROOT)}")
    return path


def section_headings(recap_text):
    return re.findall(r"^### (.+?)\s*$", recap_text, flags=re.M)


def load_transcript(recap_text):
    date = rp.get_frontmatter_value(recap_text, "date")
    if not date:
        raise SystemExit("Recap has no date: frontmatter, so its transcript cannot be found")
    path = TRANSCRIPTS_DIR / f"{date}.md"
    if not path.exists():
        raise SystemExit(f"No transcript for {date} at {path.relative_to(ROOT)}")
    blocks_path = path.with_suffix(".json")
    blocks = []
    if blocks_path.exists():
        blocks = json.loads(blocks_path.read_text(encoding="utf-8")).get("blocks", [])
    return path.read_text(encoding="utf-8"), blocks


def load_sheets():
    return json.loads(SHEETS_PATH.read_text(encoding="utf-8"))


def find_character(sheets, name):
    """Look a name up by key or alias, case-insensitively."""
    wanted = name.strip().lower()
    for key, entry in sheets["characters"].items():
        names = [key, *entry.get("aliases", [])]
        if wanted in (n.lower() for n in names):
            return key, entry
    return None, None


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48].strip("-")


# --------------------------------------------------------------------------
# Stage 1: script
# --------------------------------------------------------------------------

def write_script(recap_text, transcript_text, sheets, scene=None):
    import anthropic

    roster = "\n".join(
        f"- {name}: {entry['description']}" for name, entry in sheets["characters"].items())
    headings = section_headings(recap_text)
    ask = (f'Script the scene under the recap heading "{scene}".' if scene
           else "Pick the single most epic moment in this session and script it.")
    user = (
        f"<character_sheet>\n{roster}\n</character_sheet>\n\n"
        f"<recap_headings>\n" + "\n".join(headings) + "\n</recap_headings>\n\n"
        f"<recap>\n{recap_text}\n</recap>\n\n"
        f"<transcript>\n{transcript_text}\n</transcript>\n\n{ask}"
    )

    client = anthropic.Anthropic()
    response = client.beta.messages.parse(
        model=SCRIPT_MODEL,
        max_tokens=16000,
        system=SCRIPT_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "high"},
        output_format=SceneImage,
        # On a safety decline, re-run on a fallback model instead of failing
        # (campaign combat reads as violence often enough to matter).
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise SystemExit(f"{SCRIPT_MODEL} declined to script this scene: {response.stop_details}")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise SystemExit(f"{SCRIPT_MODEL} returned no usable script (stop_reason={response.stop_reason})")

    script = response.parsed_output
    if script.section not in headings:
        raise SystemExit(f'Script names section "{script.section}", which is not a heading in the recap')
    return script


def normalize_script(script, corrections):
    """Enforce the guardrails the model (or a hand edit) is only asked to follow."""
    def fix(text):
        return rp.apply_name_corrections(text, corrections)[0]

    script.title = fix(script.title)
    script.shots = [fix(s) for s in script.shots if s.strip()]
    if not script.shots:
        raise SystemExit("The script has no shots")
    if script.chosen is not None and not 1 <= script.chosen <= len(script.shots):
        raise SystemExit(f"chosen is {script.chosen}, but the script has {len(script.shots)} shot(s)")
    script.characters = [fix(c) for c in script.characters]
    if script.quote and not script.quote.text.strip():
        script.quote = None
    if script.quote:
        script.quote.speaker = fix(script.quote.speaker)
        script.quote.text = fix(script.quote.text)
    return script


_WORD = re.compile(r"[a-z0-9']+")


def unverified_lines(script, blocks, window=6, threshold=0.7):
    """A quote whose words don't turn up together anywhere in the transcript.

    The transcript's caption blocks split sentences across speakers, so this
    looks for most of the quote's words inside a few consecutive blocks rather
    than for an exact match. A hit is not proof, a miss is worth a look.
    """
    texts = [b.get("text", "") for b in blocks]
    windows = [set(_WORD.findall(" ".join(texts[i:i + window]).lower()))
               for i in range(0, max(len(texts) - window + 1, 1))]
    missing = []
    for line in [script.quote] if script.quote else []:
        words = [w for w in _WORD.findall(line.text.lower()) if len(w) > 2]
        if not words:
            continue
        best = max((sum(w in win for w in words) / len(words) for win in windows), default=0)
        if best < threshold:
            missing.append(f'{line.speaker}: "{line.text}"')
    return missing


# --------------------------------------------------------------------------
# Stage 2: art
# --------------------------------------------------------------------------

image_requests = 0


def check_image_budget(needed):
    """Refuse a run that cannot finish within the cap before it spends anything."""
    if needed > MAX_IMAGE_REQUESTS:
        raise SystemExit(
            f"This run needs at least {needed} image requests but COMIC_MAX_IMAGES is "
            f"{MAX_IMAGE_REQUESTS}. Name fewer portraits or "
            f"raise COMIC_MAX_IMAGES.")


def image_cost_summary():
    return (f"Gemini image requests this run: {image_requests} "
            f"(about ${image_requests * PRICE_PER_IMAGE:.2f} at ${PRICE_PER_IMAGE} each)")


def gemini_image(contents, aspect, attempts=3, size=None):
    global image_requests
    from google import genai
    from google.genai import types

    client = genai.Client()  # reads GEMINI_API_KEY
    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio=aspect, image_size=size),
    )
    last = None
    for attempt in range(1, attempts + 1):
        if image_requests >= MAX_IMAGE_REQUESTS:
            raise SystemExit(
                f"Stopped at COMIC_MAX_IMAGES={MAX_IMAGE_REQUESTS} image requests. "
                f"Raise it to finish.")
        image_requests += 1
        response = client.models.generate_content(model=IMAGE_MODEL, contents=contents, config=config)
        for candidate in response.candidates or []:
            for part in (candidate.content.parts if candidate.content else None) or []:
                if part.inline_data and part.inline_data.data:
                    return Image.open(BytesIO(part.inline_data.data)).convert("RGB")
        last = getattr(response, "prompt_feedback", None) or [
            c.finish_reason for c in response.candidates or []]
        print(f"    no image returned (attempt {attempt}/{attempts}): {last}")
    raise SystemExit(f"{IMAGE_MODEL} returned no image after {attempts} attempts: {last}")


def art_path(comic_dir, shot):
    return comic_dir / f"art-{shot}.png"


def image_prompt(script, sheets, shot):
    lines = [sheets["style"], "", "Characters in this image:"]
    for name in script.characters:
        key, entry = find_character(sheets, name)
        lines.append(f"- {key}: {entry['description']}" if entry else f"- {name}")
    lines += [
        "",
        f"Shot: {script.shots[shot - 1]}",
        "",
        COMPOSITION,
        "",
        "A single wide cinematic illustration that fills the whole frame. Draw ONLY the "
        "artwork: no text, letters, speech balloons, captions, sound effects, signatures, "
        "watermarks, borders or panels anywhere in the image.",
    ]
    return "\n".join(lines)


def reference_parts(script, sheets):
    """Interleaved labels and images for every character portrait available."""
    parts = []
    for name in script.characters:
        key, entry = find_character(sheets, name)
        ref = entry and entry.get("reference")
        if ref and (ROOT / ref).exists():
            parts += [f"Reference image for {key} - match this character's design exactly:",
                      Image.open(ROOT / ref).convert("RGB")]
    return parts


def shots_to_draw(script, only=None):
    """--shot N, else the chosen shot, else every shot (to compare)."""
    if only is not None:
        if not 1 <= only <= len(script.shots):
            raise SystemExit(f"--shot {only}, but the script has {len(script.shots)} shot(s)")
        return [only]
    chosen = script.chosen_shot()
    return [chosen] if chosen else list(range(1, len(script.shots) + 1))


def draw_art(script, sheets, comic_dir, shots):
    comic_dir.mkdir(parents=True, exist_ok=True)
    check_image_budget(len(shots))
    refs = reference_parts(script, sheets)
    for shot in shots:
        print(f"  Drawing shot {shot}/{len(script.shots)} (16:9, {IMAGE_SIZE})")
        image = gemini_image([*refs, image_prompt(script, sheets, shot)], "16:9", size=IMAGE_SIZE)
        image.save(art_path(comic_dir, shot), "PNG")


def draw_portraits(names, force=False):
    sheets = load_sheets()
    todo = []
    for name in names or list(sheets["characters"]):
        key, entry = find_character(sheets, name)
        if not entry:
            raise SystemExit(f"{name} is not in {SHEETS_PATH.relative_to(ROOT)}")
        ref = entry.get("reference") or f"static/img/characters/{slugify(key)}.webp"
        if (ROOT / ref).exists() and not force:
            print(f"  {key}: {ref} exists (use --force to redraw)")
            continue
        todo.append((key, entry, ref))
    check_image_budget(len(todo))
    for key, entry, ref in todo:
        path = ROOT / ref
        print(f"  Drawing reference portrait for {key}")
        prompt = (
            f"{sheets['style']}\n\nCharacter reference sheet for {key}: {entry['description']}\n\n"
            "Full body, standing in a neutral three-quarter pose on a plain light background, "
            "so an artist can match this design in every later panel. No text or labels."
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        gemini_image([prompt], "3:4").save(path, "WEBP", quality=90)
        entry["reference"] = ref
        # Saved per portrait, so hitting the image cap keeps the ones drawn.
        SHEETS_PATH.write_text(json.dumps(sheets, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
    print(f"  {image_cost_summary()}")


# --------------------------------------------------------------------------
# Stage 3: the band under the art
# --------------------------------------------------------------------------

def font(name, size):
    return ImageFont.truetype(str(FONTS_DIR / name), size)


def wrap(text, fnt, max_width):
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and fnt.getlength(trial) > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def speaker_label(sheets, name):
    key, entry = find_character(sheets, name)
    return (entry or {}).get("label") or (key or name).split()[0]


def compose(script, sheets, comic_dir, shot, meta):
    """The shot's art full width, with the title, quote and session in a band below it."""
    art = Image.open(art_path(comic_dir, shot)).convert("RGB")
    art = ImageOps.fit(art, (PAGE_W, ART_H), Image.LANCZOS)

    s = SCALE
    title_font = font("Bangers-Regular.ttf", round(56 * s))
    quote_font = font("ComicNeue-Bold.ttf", round(30 * s))
    meta_font = font("ComicNeue-Bold.ttf", round(22 * s))
    title_lh, quote_lh = round(62 * s), round(40 * s)
    right_w = int(PAGE_W * 0.55)
    title_lines = wrap(script.title.upper(), title_font, PAGE_W - 2 * BAND_PAD - right_w - round(40 * s))
    quote_lines = []
    if script.quote:
        text = f"\u201c{script.quote.text}\u201d \u2014 {speaker_label(sheets, script.quote.speaker)}"
        quote_lines = wrap(text, quote_font, right_w)
    title_h = title_lh * len(title_lines)
    right_h = quote_lh * len(quote_lines) + round(30 * s)
    band_h = max(title_h, right_h) + 2 * BAND_PAD

    page = Image.new("RGB", (PAGE_W, ART_H + band_h), BAND_BG)
    page.paste(art, (0, 0))
    draw = ImageDraw.Draw(page)
    for n, line in enumerate(title_lines):
        draw.text((BAND_PAD, ART_H + BAND_PAD - round(6 * s) + n * title_lh), line, font=title_font,
                  fill="#FFD23F")
    y = ART_H + BAND_PAD
    for line in quote_lines:
        draw.text((PAGE_W - BAND_PAD - quote_font.getlength(line), y), line, font=quote_font,
                  fill="#F3EEE4")
        y += quote_lh
    draw.text((PAGE_W - BAND_PAD - meta_font.getlength(meta), y + round(4 * s)), meta, font=meta_font,
              fill="#9A9184")
    return page


# --------------------------------------------------------------------------
# Recap embed
# --------------------------------------------------------------------------

def alt_text(script, shot, limit=320):
    text = f"{script.title}: {script.shots[shot - 1]}"
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return cut[:cut.rfind(". ") + 1] if ". " in cut else cut.rsplit(" ", 1)[0] + "\u2026"


def embed_in_recap(recap_text, section, image_url, alt):
    """Put the image directly under its scene's heading; on a redraw, refresh its alt text."""
    alt = alt.replace("[", "(").replace("]", ")")
    existing = re.compile(rf"!\[[^\]\n]*\]\({re.escape(image_url)}\)")
    if existing.search(recap_text):
        updated = existing.sub(lambda m: f"![{alt}]({image_url})", recap_text, count=1)
        return updated, updated != recap_text
    heading = re.compile(rf"^### {re.escape(section)}\s*$", flags=re.M)
    match = heading.search(recap_text)
    if not match:
        raise SystemExit(f'Heading "### {section}" not found in the recap')
    insert = f"\n\n![{alt}]({image_url})\n"
    return recap_text[:match.end()] + insert + recap_text[match.end():], True


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def existing_comic(stem, slug=None):
    if slug:
        path = COMICS_DATA_DIR / slug
        if not (path / "script.json").exists():
            raise SystemExit(f"No script at {path.relative_to(ROOT)}/script.json")
        return path
    found = sorted(p.parent for p in COMICS_DATA_DIR.glob(f"{stem}-*/script.json"))
    if len(found) != 1:
        names = ", ".join(p.name for p in found) or "none"
        raise SystemExit(f"Pass --comic to pick one of this session's comics ({names})")
    return found[0]


def recap_ref_from_slug(slug):
    """'session-64-the-missile' -> 'session-64' (the recap the comic belongs to)."""
    match = re.match(r"((?:session|interlude)-\d+)-", slug)
    if not match:
        raise SystemExit(f"Comic name {slug!r} should start with its recap, e.g. session-64-...")
    return match.group(1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("session", nargs="?", help="Auto mode: session number, recap stem, or page URL")
    parser.add_argument("--scene", help="Auto mode: recap ### heading to draw (default: Claude picks)")
    parser.add_argument("--comic", help="Image folder under data/comics, e.g. session-64-the-launch")
    parser.add_argument("--script-only", action="store_true", help="Auto mode: write the script, draw nothing")
    parser.add_argument("--draw", "--redraw", dest="redraw", action="store_true",
                        help="Draw (or redraw) the art from the image's script.json, then add the band")
    parser.add_argument("--shot", type=int, help="With --draw: only this shot number")
    parser.add_argument("--letter-only", action="store_true",
                        help="Rebuild the band (title, quote) on the existing art, no API")
    parser.add_argument("--no-embed", action="store_true", help="Don't add the image to the recap")
    parser.add_argument("--portraits", nargs="*", metavar="NAME",
                        help="Draw reference portraits (all characters without one if no names)")
    parser.add_argument("--force", action="store_true", help="With --portraits: redraw existing ones")
    args = parser.parse_args(argv)

    if args.portraits is not None:
        draw_portraits(args.portraits, force=args.force)
        return
    if args.comic and not args.session:
        args.session = recap_ref_from_slug(args.comic)
    if not args.session:
        parser.error("give a session number (auto mode) or --comic NAME")
    if args.comic and not (args.redraw or args.letter_only):
        parser.error("--comic needs --draw or --letter-only")

    recap_path = resolve_recap(args.session)
    recap_text = recap_path.read_text(encoding="utf-8")
    sheets = load_sheets()
    corrections = rp.load_name_corrections(KB_PATH)

    if args.redraw or args.letter_only:
        comic_dir = existing_comic(recap_path.stem, args.comic)
        data = json.loads((comic_dir / "script.json").read_text(encoding="utf-8"))
        script = normalize_script(SceneImage.model_validate(data), corrections)
    else:
        transcript_text, blocks = load_transcript(recap_text)
        print(f"Scripting {recap_path.stem} with {SCRIPT_MODEL}...")
        script = normalize_script(
            write_script(recap_text, transcript_text, sheets, args.scene), corrections)
        comic_dir = COMICS_DATA_DIR / f"{recap_path.stem}-{slugify(script.section)}"
        comic_dir.mkdir(parents=True, exist_ok=True)
        print(f'  "{script.title}" \u2014 {script.section}')
        print(f"  Why: {script.why}")
        for line in unverified_lines(script, blocks):
            print(f"  Check against the transcript (not found there): {line}")

    (comic_dir / "script.json").write_text(
        json.dumps(script.model_dump(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  Script: {(comic_dir / 'script.json').relative_to(ROOT)}")
    if args.script_only:
        return

    if not args.letter_only:
        draw_art(script, sheets, comic_dir, shots_to_draw(script, args.shot))
        print(f"  {image_cost_summary()}")

    number = re.sub(r"\D", "", recap_path.stem)
    kind = "Interlude" if recap_path.stem.startswith("interlude") else "Session"
    meta = f"{kind} {number} \u00b7 {script.section}"
    drawn = [n for n in range(1, len(script.shots) + 1) if art_path(comic_dir, n).exists()]
    for shot in drawn:
        compose(script, sheets, comic_dir, shot, meta).save(
            comic_dir / f"preview-{shot}.webp", "WEBP", quality=85)
        print(f"  Preview: {(comic_dir / f'preview-{shot}.webp').relative_to(ROOT)}")

    chosen = script.chosen_shot()
    if chosen is None:
        print(f"  {len(script.shots)} shots: compare the previews, set \"chosen\" in script.json, "
              f"then run --letter-only to publish (free).")
        return
    if chosen not in drawn:
        raise SystemExit(f"Shot {chosen} is chosen but has no art yet; run --draw --shot {chosen}")
    COMICS_IMG_DIR.mkdir(parents=True, exist_ok=True)
    out = COMICS_IMG_DIR / f"{comic_dir.name}.webp"
    compose(script, sheets, comic_dir, chosen, meta).save(out, "WEBP", quality=92)
    print(f"  Image (shot {chosen}): {out.relative_to(ROOT)}")

    if not args.no_embed:
        updated, changed = embed_in_recap(recap_text, script.section, f"/img/comics/{out.name}",
                                          alt_text(script, chosen))
        if changed:
            recap_path.write_text(updated, encoding="utf-8")
            print(f"  Embedded under '### {script.section}' in {recap_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
