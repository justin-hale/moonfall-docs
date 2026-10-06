#!/usr/bin/env python3
"""Turn a scene from a session into a comic-book page.

    python scripts/comic_scene.py 64                     # Claude picks the best scene
    python scripts/comic_scene.py 64 --scene "The Missile"
    python scripts/comic_scene.py 64 --script-only       # write the panel script, draw nothing
    python scripts/comic_scene.py 64 --redraw            # redraw from the (hand-edited) script
    python scripts/comic_scene.py 64 --redraw --panel 3  # redraw one panel only
    python scripts/comic_scene.py 64 --letter-only       # re-letter the existing art, no API calls
    python scripts/comic_scene.py --portraits Bru Silas  # draw reference portraits

Three stages, each of which can be re-run on its own:

1. **Script** (Claude, `ANTHROPIC_API_KEY`). Reads the recap and the session's
   transcript and writes a 3-6 panel script: what each panel shows, the
   narration caption, and dialogue lifted from what was said at the table.
   Saved to `data/comics/<slug>/script.json`, the file to hand-edit when a
   panel is wrong.
2. **Art** (Gemini, `GEMINI_API_KEY`). One image per panel, with no text in
   it. Every character in the panel is described from
   `data/character-sheets.json` and, once someone has approved a portrait,
   shown to the model as a reference image so they look the same from panel
   to panel. Raw panels are kept in `data/comics/<slug>/` so lettering
   changes never cost another generation.
3. **Lettering** (Pillow, no API). Lays the panels out, adds captions,
   balloons and sound effects in code. Image models misspell names, and the
   name rules in CLAUDE.md are not optional, so no text is ever drawn by the
   model. The page goes to `static/img/comics/<slug>.webp` and is embedded
   in the recap under the heading of the scene it shows.

Nothing here publishes on its own: the result is a working-tree change to
review, and the "Draw Comic" workflow opens it as a PR.
"""

import argparse
import json
import os
import re
import sys
from io import BytesIO
from pathlib import Path
from typing import Literal

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
# A per-run ceiling on Gemini image requests, retries included: the backstop
# for the AI Studio spend cap, which Google enforces up to ~10 minutes late.
# The default fits a full 6-panel page plus a few retries.
MAX_IMAGE_REQUESTS = int(os.environ.get("COMIC_MAX_IMAGES", "10"))
# Only for the cost estimate printed at the end. Nano Banana Pro at 1K-2K.
PRICE_PER_IMAGE = float(os.environ.get("GEMINI_PRICE_PER_IMAGE", "0.134"))

MIN_PANELS, MAX_PANELS = 3, 6

# Page geometry (pixels).
PAGE_W = 1600
MARGIN = 40
GUTTER = 24
BORDER = 6
HEADER_H = 150
FOOTER_H = 60
WIDE_ASPECT = (16, 9)
HALF_ASPECT = (4, 5)


# --------------------------------------------------------------------------
# Script schema
# --------------------------------------------------------------------------

class Line(BaseModel):
    speaker: str = Field(description="Canonical character name, never a player's name")
    text: str = Field(description="What they said, trimmed from the transcript. 25 words at most")
    position: Literal["left", "center", "right"] = Field(
        description="Where the speaker stands in the frame; the balloon tail points there")


class Panel(BaseModel):
    size: Literal["wide", "half"] = Field(
        description="wide = full page width, 16:9. half = half width, portrait; halves sit side by side in pairs")
    characters: list[str] = Field(
        description="Everyone visible, using names from the character sheet where they appear there")
    visual: str = Field(
        description="What the artist draws: setting, action, camera angle, who is where, expressions, "
                    "lighting. Do not restate appearances from the character sheet. No text in the image")
    caption: str = Field(description="Narration box, present tense, 20 words at most. Empty string for none")
    dialogue: list[Line] = Field(description="At most two balloons, in reading order")
    sfx: str = Field(description="Sound effect lettering such as KRA-KOOM!, or empty string")


class ComicScript(BaseModel):
    title: str = Field(description="Short punchy title for the page")
    section: str = Field(description="The recap's ### heading this scene falls under, copied exactly")
    why: str = Field(description="One sentence: why this is the scene worth drawing")
    transcript_evidence: list[str] = Field(
        description="Verbatim transcript lines that show this happened as drawn")
    panels: list[Panel]


SCRIPT_SYSTEM = """\
You adapt moments from a D&D campaign (Moonfall) into a single comic-book page.

You get the session's published recap, its raw transcript, and the character \
sheet the artist works from. Pick the scene (or use the one you are given) and \
script it as {min}-{max} panels.

The transcript is the source of truth. The recap is a guide to where things \
are, but it has been wrong before; never draw something the transcript does not \
support. Use only in-character play, not table talk about rules or snacks.

Dialogue is what the players and DM actually said in character, trimmed of \
filler and false starts and shortened where needed, never invented. Attribute \
it to the character, never to the player (the roster in the recap's Players \
Present section maps them). Leliana and Helisanna are one woman with two \
personas: name whichever persona is out at that moment.

Spelling is fixed: Bru (never Brew), Elspeth (never Ellsworth or Elizabeth), \
Leliana (never Liliana), Eldoran, Greyport, Astro.

Write each panel's `visual` for an illustrator who has never heard of the \
campaign: make it concrete and stageable in one image. Appearances come from \
the character sheet, so name the characters in `characters` instead of \
describing them again. Build to the scene's payoff and land it in the last \
panel. Usually open wide to establish where we are. Halves come in pairs.\
""".format(min=MIN_PANELS, max=MAX_PANELS)


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
           else "Pick the single most comic-worthy scene in this session and script it.")
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
        output_format=ComicScript,
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
    """Enforce the guardrails the model is only asked to follow."""
    def fix(text):
        return rp.apply_name_corrections(text, corrections)[0]

    script.title = fix(script.title)
    panels = script.panels[:MAX_PANELS]
    if len(panels) < MIN_PANELS:
        print(f"  Warning: only {len(panels)} panels scripted")
    for panel in panels:
        panel.visual = fix(panel.visual)
        panel.caption = fix(panel.caption)
        panel.sfx = fix(panel.sfx)
        panel.characters = [fix(c) for c in panel.characters]
        panel.dialogue = panel.dialogue[:2]
        for line in panel.dialogue:
            line.speaker = fix(line.speaker)
            line.text = fix(line.text)
    script.panels = pair_halves(panels)
    return script


def pair_halves(panels):
    """A half panel without a neighbouring half becomes wide."""
    out = list(panels)
    i = 0
    while i < len(out):
        if out[i].size == "half":
            if i + 1 < len(out) and out[i + 1].size == "half":
                i += 2
                continue
            out[i].size = "wide"
        i += 1
    return out


_WORD = re.compile(r"[a-z0-9']+")


def unverified_lines(script, blocks, window=6, threshold=0.7):
    """Dialogue whose words don't turn up together anywhere in the transcript.

    The transcript's caption blocks split sentences across speakers, so this
    looks for most of a line's words inside a few consecutive blocks rather
    than for an exact match. A hit is not proof, a miss is worth a look.
    """
    texts = [b.get("text", "") for b in blocks]
    windows = [set(_WORD.findall(" ".join(texts[i:i + window]).lower()))
               for i in range(0, max(len(texts) - window + 1, 1))]
    missing = []
    for panel in script.panels:
        for line in panel.dialogue:
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
            f"{MAX_IMAGE_REQUESTS}. Draw fewer (--panel N, or name fewer portraits) or "
            f"raise COMIC_MAX_IMAGES.")


def image_cost_summary():
    return (f"Gemini image requests this run: {image_requests} "
            f"(about ${image_requests * PRICE_PER_IMAGE:.2f} at ${PRICE_PER_IMAGE} each)")


def gemini_image(contents, aspect, attempts=3):
    global image_requests
    from google import genai
    from google.genai import types

    client = genai.Client()  # reads GEMINI_API_KEY
    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio=aspect),
    )
    last = None
    for attempt in range(1, attempts + 1):
        if image_requests >= MAX_IMAGE_REQUESTS:
            raise SystemExit(
                f"Stopped at COMIC_MAX_IMAGES={MAX_IMAGE_REQUESTS} image requests. "
                f"Panels already drawn are saved; finish with --redraw --panel N.")
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


def panel_prompt(panel, sheets):
    lines = [sheets["style"], "", "Characters in this panel:"]
    for name in panel.characters:
        key, entry = find_character(sheets, name)
        lines.append(f"- {key}: {entry['description']}" if entry else f"- {name}")
    lines += [
        "",
        f"Panel: {panel.visual}",
        "",
        "Draw ONLY the artwork. No text, letters, speech balloons, captions, sound "
        "effects, signatures, watermarks or panel borders anywhere in the image. "
        "Keep the top fifth of the frame free of faces and key action, because "
        "lettering will be laid over it.",
    ]
    return "\n".join(lines)


def reference_parts(panel, sheets, previous=None):
    """Interleaved labels and images for every reference the panel has."""
    parts = []
    for name in panel.characters:
        key, entry = find_character(sheets, name)
        ref = entry and entry.get("reference")
        if ref and (ROOT / ref).exists():
            parts += [f"Reference image for {key} - match this design exactly:",
                      Image.open(ROOT / ref).convert("RGB")]
    if previous is not None:
        parts += ["The previous panel on this page - keep the art style, palette and "
                  "costumes consistent with it:", previous]
    return parts


def draw_panels(script, sheets, comic_dir, only=None):
    comic_dir.mkdir(parents=True, exist_ok=True)
    check_image_budget(1 if only is not None else len(script.panels))
    previous = None
    for number, panel in enumerate(script.panels, 1):
        path = comic_dir / f"panel-{number}.webp"
        if only is not None and number != only:
            if path.exists():
                previous = Image.open(path).convert("RGB")
            continue
        aspect = "16:9" if panel.size == "wide" else "4:5"
        print(f"  Drawing panel {number}/{len(script.panels)} ({panel.size})")
        contents = [*reference_parts(panel, sheets, previous), panel_prompt(panel, sheets)]
        image = gemini_image(contents, aspect)
        image.save(path, "WEBP", quality=90)
        previous = image


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
# Stage 3: lettering
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


def layout(panels):
    """Panel boxes (x, y, w, h) below the header, and the page height."""
    inner = PAGE_W - 2 * MARGIN
    half_w = (inner - GUTTER) // 2
    boxes, y, i = [], MARGIN + HEADER_H, 0
    while i < len(panels):
        if panels[i].size == "half" and i + 1 < len(panels) and panels[i + 1].size == "half":
            h = half_w * HALF_ASPECT[1] // HALF_ASPECT[0]
            boxes += [(MARGIN, y, half_w, h), (MARGIN + half_w + GUTTER, y, half_w, h)]
            i += 2
        else:
            h = inner * WIDE_ASPECT[1] // WIDE_ASPECT[0]
            boxes.append((MARGIN, y, inner, h))
            i += 1
        y += h + GUTTER
    return boxes, y - GUTTER + FOOTER_H + MARGIN


def draw_caption(draw, x, y, max_w, text):
    fnt = font("ComicNeue-Bold.ttf", 26)
    lines = wrap(text.upper(), fnt, max_w - 28)
    line_h = 32
    w = int(max(fnt.getlength(l) for l in lines)) + 28
    h = line_h * len(lines) + 20
    draw.rectangle([x, y, x + w, y + h], fill="#FFE8A3", outline="black", width=3)
    for n, line in enumerate(lines):
        draw.text((x + 14, y + 10 + n * line_h), line, font=fnt, fill="black")
    return h


def draw_balloon(draw, box, y, line, label):
    px, py, pw, ph = box
    name_font = font("Bangers-Regular.ttf", 24)
    text_font = font("ComicNeue-Bold.ttf", 28)
    lines = wrap(line.text.upper(), text_font, min(pw * 0.62, 560))
    line_h = 34
    text_w = max([text_font.getlength(l) for l in lines] + [name_font.getlength(label)])
    w, h = int(text_w) + 56, line_h * len(lines) + 30 + 28
    anchor = {"left": 0.08, "center": 0.5, "right": 0.92}[line.position]
    bx = int(min(max(px + 16, px + pw * anchor - w / 2), px + pw - w - 16))
    by = y
    radius = min(h // 2, 40)

    # Tail toward where the speaker stands.
    base_x = bx + w * {"left": 0.3, "center": 0.5, "right": 0.7}[line.position]
    tip_x = base_x + {"left": -40, "center": 0, "right": 40}[line.position]
    tip_y = by + h + 46
    outer = [(base_x - 22, by + h - 8), (base_x + 22, by + h - 8), (tip_x, tip_y)]
    inner = [(base_x - 17, by + h - 12), (base_x + 17, by + h - 12), (tip_x, tip_y - 7)]

    draw.rounded_rectangle([bx - 3, by - 3, bx + w + 3, by + h + 3], radius=radius + 3, fill="black")
    draw.polygon(outer, fill="black")
    draw.rounded_rectangle([bx, by, bx + w, by + h], radius=radius, fill="white")
    draw.polygon(inner, fill="white")
    draw.text((bx + 28, by + 14), label.upper(), font=name_font, fill="#B3261E")
    for n, text in enumerate(lines):
        draw.text((bx + 28, by + 42 + n * line_h), text, font=text_font, fill="black")
    return h + 56


def draw_sfx(page, box, text):
    px, py, pw, ph = box
    size = max(48, pw // 8)
    fnt = font("Bangers-Regular.ttf", size)
    stroke = max(4, size // 14)
    tw = int(fnt.getlength(text)) + 4 * stroke
    layer = Image.new("RGBA", (tw, size + 4 * stroke), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((2 * stroke, stroke), text, font=fnt, fill="#FFD23F",
                               stroke_width=stroke, stroke_fill="black")
    layer = layer.rotate(8, expand=True, resample=Image.BICUBIC)
    if layer.width > pw - 32:
        scale = (pw - 32) / layer.width
        layer = layer.resize((int(layer.width * scale), int(layer.height * scale)), Image.LANCZOS)
    page.alpha_composite(layer, (px + pw - layer.width - 16, py + ph - layer.height - 16))


def speaker_label(sheets, name):
    key, entry = find_character(sheets, name)
    return (entry or {}).get("label") or (key or name).split()[0]


def letter_page(script, sheets, comic_dir, session_title):
    boxes, page_h = layout(script.panels)
    page = Image.new("RGBA", (PAGE_W, page_h), "#FBF7EE")
    draw = ImageDraw.Draw(page)

    title_font = font("Bangers-Regular.ttf", 96)
    kicker_font = font("Bangers-Regular.ttf", 32)
    draw.text((MARGIN, MARGIN - 6), "MOONFALL SESSIONS", font=kicker_font, fill="#B3261E")
    draw.text((MARGIN, MARGIN + 30), script.title.upper(), font=title_font, fill="black",
              stroke_width=2, stroke_fill="black")

    for number, (panel, box) in enumerate(zip(script.panels, boxes), 1):
        px, py, pw, ph = box
        art = Image.open(comic_dir / f"panel-{number}.webp").convert("RGBA")
        page.alpha_composite(ImageOps.fit(art, (pw, ph), Image.LANCZOS), (px, py))
        draw.rectangle([px, py, px + pw, py + ph], outline="black", width=BORDER)

        y = py + BORDER + 10
        if panel.caption:
            y += draw_caption(draw, px + BORDER + 10, y, int(pw * 0.6), panel.caption) + 14
        for line in panel.dialogue:
            y += draw_balloon(draw, box, y, line, speaker_label(sheets, line.speaker))
        if panel.sfx:
            draw_sfx(page, box, panel.sfx.upper())

    footer_font = font("ComicNeue-Bold.ttf", 24)
    draw.text((MARGIN, page_h - MARGIN - 30), session_title, font=footer_font, fill="#555555")
    return page.convert("RGB")


# --------------------------------------------------------------------------
# Recap embed
# --------------------------------------------------------------------------

def embed_in_recap(recap_text, section, image_url, alt):
    """Put the comic directly under its scene's heading. Idempotent by URL."""
    if image_url in recap_text:
        return recap_text, False
    heading = re.compile(rf"^### {re.escape(section)}\s*$", flags=re.M)
    match = heading.search(recap_text)
    if not match:
        raise SystemExit(f'Heading "### {section}" not found in the recap')
    alt = alt.replace("[", "(").replace("]", ")")
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("session", nargs="?", help="Session number, recap stem, or page URL")
    parser.add_argument("--scene", help="Recap ### heading to draw (default: Claude picks)")
    parser.add_argument("--comic", help="Existing comic slug, for --redraw/--letter-only")
    parser.add_argument("--script-only", action="store_true", help="Write the script, draw nothing")
    parser.add_argument("--redraw", action="store_true", help="Redraw art from the existing script")
    parser.add_argument("--panel", type=int, help="With --redraw: only this panel")
    parser.add_argument("--letter-only", action="store_true", help="Re-letter existing art, no API")
    parser.add_argument("--no-embed", action="store_true", help="Don't add the page to the recap")
    parser.add_argument("--portraits", nargs="*", metavar="NAME",
                        help="Draw reference portraits (all characters without one if no names)")
    parser.add_argument("--force", action="store_true", help="With --portraits: redraw existing ones")
    args = parser.parse_args(argv)

    if args.portraits is not None:
        draw_portraits(args.portraits, force=args.force)
        return
    if not args.session:
        parser.error("session is required")

    recap_path = resolve_recap(args.session)
    recap_text = recap_path.read_text(encoding="utf-8")
    sheets = load_sheets()
    corrections = rp.load_name_corrections(KB_PATH)

    if args.redraw or args.letter_only:
        comic_dir = existing_comic(recap_path.stem, args.comic)
        data = json.loads((comic_dir / "script.json").read_text(encoding="utf-8"))
        script = normalize_script(ComicScript.model_validate(data), corrections)
    else:
        transcript_text, blocks = load_transcript(recap_text)
        print(f"Scripting {recap_path.stem} with {SCRIPT_MODEL}...")
        script = normalize_script(
            write_script(recap_text, transcript_text, sheets, args.scene), corrections)
        comic_dir = COMICS_DATA_DIR / f"{recap_path.stem}-{slugify(script.section)}"
        comic_dir.mkdir(parents=True, exist_ok=True)
        print(f'  "{script.title}" — {script.section} ({len(script.panels)} panels)')
        print(f"  Why: {script.why}")
        for line in unverified_lines(script, blocks):
            print(f"  Check against the transcript (not found there): {line}")

    (comic_dir / "script.json").write_text(
        json.dumps(script.model_dump(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  Script: {(comic_dir / 'script.json').relative_to(ROOT)}")
    if args.script_only:
        return

    if not args.letter_only:
        draw_panels(script, sheets, comic_dir, only=args.panel if args.redraw else None)
        print(f"  {image_cost_summary()}")

    session_title = rp.get_frontmatter_value(recap_text, "title") or recap_path.stem
    page = letter_page(script, sheets, comic_dir, f"Session {session_title}")
    COMICS_IMG_DIR.mkdir(parents=True, exist_ok=True)
    out = COMICS_IMG_DIR / f"{comic_dir.name}.webp"
    page.save(out, "WEBP", quality=88)
    print(f"  Page: {out.relative_to(ROOT)}")

    if not args.no_embed:
        url = f"/img/comics/{out.name}"
        alt = f"Comic: {script.title}. " + " ".join(p.visual.split(".")[0] + "." for p in script.panels)
        updated, changed = embed_in_recap(recap_text, script.section, url, alt)
        if changed:
            recap_path.write_text(updated, encoding="utf-8")
            print(f"  Embedded under '### {script.section}' in {recap_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
