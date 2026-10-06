# Session Automation Scripts

This directory contains automation scripts for the D&D campaign documentation workflow.

## automate_session.py

A comprehensive Python script that automates the workflow of creating session notes from transcript files.

### What It Does

1. **Finds the latest SRT file** in `transcripts_raw/` directory
2. **Runs the transcript cleaner** (`plugins/transcript_cleaner_ai_optimized.py`) to convert SRT to markdown
3. **Determines the next session number** by analyzing existing session files
4. **Generates a Claude prompt** with context from recent sessions
5. **Prepares everything** for Claude Code to create the full session notes
6. **Updates the wiki pages** (NPCs, locations, organizations, items) the new recap involves (see [Wiki Pages](#wiki-pages-wiki_updatepy))

### Usage

#### Basic Usage (Most Common)

```bash
# Process the latest transcript and prepare for the next session
generate-session
```

This will:
- Find the newest .srt file in `transcripts_raw/`
- Clean it and save to `docs/transcripts/`
- Auto-detect the next session number
- Generate a prompt for Claude Code
- **Automatically invoke Claude Code to create the session notes**

#### Create an Interlude

```bash
# Create an interlude instead of a regular session
generate-session --interlude
```

#### Specify Session Number

```bash
# Manually specify the session number
generate-session --session-number 42
```

#### Skip Transcript Cleaning

```bash
# Use existing transcript (skip cleaning step)
generate-session --no-clean
```

#### Save Prompt Only (Don't Call the API)

```bash
# Generate the prompt but don't call the model
generate-session --no-generate
```

#### Alternative: Full Python Command

If the `generate-session` alias isn't working, you can use the full command:

```bash
python3 scripts/automate_session.py
```

### Workflow Example

1. Place your new SRT file in `transcripts_raw/`
2. Run: `generate-session`
3. The script will:
   - Clean the transcript
   - Generate a detailed prompt
   - **Automatically invoke Claude Code to create the session notes**
4. Review the generated session note in `docs/sessions/`

### Setup

The `generate-session` command is an alias that was automatically added to your `~/.zshrc` file. If you need to set it up again or on a different machine, add this line to your shell config:

```bash
alias generate-session='python3 ~/Dev/docusaurus/scripts/automate_session.py'
```

Then reload your shell: `source ~/.zshrc`

### Generation Guardrails

The model writes the whole recap file, frontmatter included — so it used to
write fields it has no way to know, and those shipped. Session 58 dated itself
2026-06-26 (Session 56's date), Session 59 dated itself three weeks into the
future, both invented a Spotify episode URL, and Session 59 printed "Brew" and
a Google Meet handle despite the prompt's name rules. Each one needed a
hand-written repair commit, and a wrong date is worse than it looks:
`extract_session_stats.py` joins a recap to its transcript on that date, so a
hallucinated one silently drops the session out of the stats dataset.

`recap_postprocess.py` now takes those fields away from the model. After every
generation it:

- **stamps the date** — both the `date:` key and the `***Month D, YYYY***`
  header — from the transcript filename, which is the authoritative record
- **strips `podcastlink`** — the campaign no longer publishes a podcast, so
  the key is removed outright. The model writes one anyway, because every
  session it reads for style still has one. A recap that already carried a
  real episode URL keeps it, so regenerating an older session does not
  destroy its link
- **applies the canonical names** from the tables in `data/campaign-kb.md` —
  Known Transcription Errors plus the alias columns of the roster, NPC and
  location tables. Every row `/fix-notes` adds there immunises future recaps
  automatically
- **unwraps dead internal links**, keeping the label. A generated link to a
  page nobody had written (`/npcs/scarlet/`) once failed `npm run build` and
  blocked a deploy
- **validates what is left** — frontmatter keys, leftover template
  placeholders, the `Players Present` and `Plot Events` sections (interludes
  are exempt; they have their own shape), and a plausible body length

Everything repaired is printed in the run log. Anything that cannot be
repaired fails the run: the recap is still written so it can be inspected, but
nothing is committed and the SRT stays in `transcripts_raw/` so a re-run picks
it up.

Run the tests with `python -m pytest scripts/tests/ -q`.

### Wiki Pages (`wiki_update.py`)

The NPC, location, organization and item pages (`docs/npcs/`,
`docs/locations/`, `docs/organizations/`, `docs/items/`) are kept current by
this step. The first three were written once, around Session 36, and nothing
ever updated them again. After each recap is published, the generator now:

1. **Finds the pages the recap involves**: a link to the page, or the page's
   `title` or one of its `aliases` appearing in the recap body. Matching is
   case-sensitive (these are proper nouns), and it ignores the frontmatter,
   editorial notes and correction notices.
2. **Asks Haiku for one factual sentence per page** about what that entity did,
   what happened there, or who used, gained or lost an item, *in this recap*. A passing mention gets nothing.
3. **Writes it as that session's bullet** under the page's `## Session History`
   section: `- **[Session 64](/sessions/session-64)** — …`. A regenerated recap
   replaces its own bullet rather than adding a second one.

Recurring characters, places, groups and items that have no page yet are listed in the
run log and the Actions job summary. They are **never created automatically**:
whether something deserves a page is an editorial call.

The recap prompt also lists every existing wiki page, so new recaps link them
by their real paths.

To make a page easier to match, give it aliases in its frontmatter:

```yaml
aliases: ["Viper", "Elizandra Legrand"]
```

The step only warns on failure. A published recap never waits on the wiki.

### Output

The script generates:
- Cleaned transcript in `docs/transcripts/YYYY-MM-DD.md`
- A detailed prompt for Claude Code
- Saves the prompt to `scripts/last_claude_prompt.txt` for reference

### Command Line Options

| Option | Description |
|--------|-------------|
| `--session-number N` | Specify session number (default: auto-detect) |
| `--interlude` | Create an interlude instead of regular session |
| `--no-clean` | Skip transcript cleaning (use existing transcript) |
| `--no-generate` | Don't call the API (just save the prompt) |
| `--timeout MIN` | API timeout in minutes (default: 10) |
| `--local` | Route model calls through the local `claude` CLI |
| `-h, --help` | Show help message |

### Requirements

- Python 3.6+
- The `transcript_cleaner_ai_optimized.py` script must exist in `plugins/`
- SRT files should be in `transcripts_raw/`

### File Structure

```
docusaurus/
├── transcripts_raw/          # Place .srt files here
├── docs/
│   ├── transcripts/          # Cleaned transcripts output here
│   └── sessions/             # Session notes created here
├── plugins/
│   └── transcript_cleaner_ai_optimized.py
└── scripts/
    ├── automate_session.py   # This script
    └── last_claude_prompt.txt # Last generated prompt
```

### Tips

- The script automatically detects the next session number by looking at existing files
- It analyzes the 5 most recent sessions to provide context to Claude
- The generated prompt includes references to recent sessions for consistency
- The transcript date is extracted from the filename (YYYY-MM-DD.md format)

### Troubleshooting

**No .srt files found:**
- Make sure your transcript file is in `transcripts_raw/` directory
- Check that the file has a `.srt` extension

**Transcript cleaning fails:**
- Verify that `plugins/transcript_cleaner_ai_optimized.py` exists
- Try running the cleaner script manually to see detailed errors

**Wrong session number:**
- Use `--session-number N` to manually specify the correct number
- The script looks at existing files in `docs/sessions/` to auto-detect

## ci_process.py

The intake pipeline: Google Drive recording → MP3 + SRT → GitHub release →
podcast feed → an SRT pull request on this repo. Driven a stage at a time by
`.github/workflows/process-episode.yml`, which runs Saturday 14:00 UTC and can
be dispatched by hand.

```
detect → download → extract → release → update-feed → open-pr
```

`detect` picks the oldest published release that has no `open-pr` recorded, so
a run that stops halfway is picked up by the next one. Nothing else about the
pipeline is worth understanding before this:

### Where recordings come from

`DRIVE_FOLDER_ID` is a **comma-separated list of root folder ids**, and each
root is walked recursively — not listed flat.

Google Meet changed its filing layout on 2026-09-19. It used to drop every
recording straight into `My Drive/Meet Recordings/`; it now creates
`My Drive/Google Meet/<meeting name>/` and nests them a level down. The old
folder still exists and still holds the back catalogue, but nothing new will
ever land in it again. `detect` was listing that one folder, non-recursively,
so the 2026-09-18 recording was invisible to it: three scheduled runs in a row
finished green having reported "No new episodes found", and the episode simply
never entered the pipeline.

**Every root must be shared with the service account.** `GOOGLE_SERVICE_ACCOUNT_KEY`
is a service account with `drive.readonly` — a separate identity from the
recordings' owner, so it sees only what has been shared with it. Drive reports
a folder that identity cannot read as an *empty listing*, not an error, which
is indistinguishable from an empty folder. That is the second half of how
Session 62 went missing: the recursive scan did reach the new `Google Meet`
root and got nothing back, because the folder Meet had just created had never
been shared. The scan now prints a per-root tally and warns by id when a root
returns no entries at all, so the next time this happens the run says so
instead of reporting "No new episodes found".

The identity to share with is

    justin-hale-moonfall-docs-gh-a@fluted-citizen-269819.iam.gserviceaccount.com

**Viewer** is the right role. The pipeline requests only `drive.readonly` and
never writes to Drive — `Delete source video` removes the copy in `workspace/`
on the runner, not the recording.

That address is an identifier, not a credential: it grants nothing without the
key, which exists only in the `GOOGLE_SERVICE_ACCOUNT_KEY` repository secret.
To confirm it first-hand, read the `client_email` field of that secret's JSON,
or open the share dialog on a folder the pipeline already reads.

Share the **tree root**, not an individual meeting folder — Drive permissions
inherit, so each new per-meeting subfolder Meet creates is covered without
further action. Share a leaf and you are back here next week.

Sharing the tree root is not always enough either: Meet can create a whole new
root. On 2026-09-26 it made a *second* `My Drive/Google Meet/` folder
(`1YV_vLeKzQwEPJDv7Ogc2O9MyQHWdLPMk`) next to the first, and filed Session 63
(recorded 2026-09-25) there. That run found only Session 62 in the roots it
knew about, and reported "No new episodes found". When a session goes missing,
search Drive for `DnD - <date> - Recording` and check which folder it is in.
If that folder is not in `DRIVE_FOLDER_ID`, add it there and share it.

`detect` probes every root with `files.get` before walking it, so the log says
which of the two things went wrong:

- `Root <id>: NOT ACCESSIBLE` — the grant is missing, or the id is wrong.
  Drive answers a request for a folder you cannot see with *404 not found*
  rather than *403 forbidden*, so those two look identical from the outside;
  check the id against the one in the folder's URL before re-sharing.
- `WARNING: root <id> is readable but has no children` — the grant worked and
  the folder really is empty, which usually means the recordings are in a
  subfolder that was shared separately rather than in the tree root.

**An unreadable root fails the run.** This is the difference between "nothing
new this week" and "the pipeline is blind", and the two must not look alike:
`detect` exits non-zero and the job goes red. Session 62 is the argument —
three consecutive scheduled runs reported `No new episodes found` and finished
**green** while the recording sat unreachable, and nothing anywhere said so.
The failure also writes to `$GITHUB_STEP_SUMMARY`, so the run page states the
problem and the remedy without anyone opening the log — which matters more now
that a red run is the only signal there is.

A root that is readable but empty only warns: an empty folder is a state the
pipeline can legitimately be in, so it does not go red. Note that a transient
Drive error on the probe also fails the run rather than being swallowed —
deliberate, since a re-run costs a minute and silence cost three weeks.

Both roots are therefore in the workflow's default, and subfolders are
followed, so a further reshuffle inside either tree needs no code change. A
`DRIVE_FOLDER_ID` repository variable overrides the default; it takes the same
comma-separated form. Overlapping roots are de-duplicated, and the walk stops
after 200 folders so a cycle cannot run away.

### Where the speaker names come from

The transcript has never been speech-to-text. `extract` pulls the caption
track Meet bakes into the recording (`ffmpeg -map 0:2`), and that track used
to name every speaker — Episode 61's had five, with no unattributed cues.

Episode 62's did not. 2,167 of its 3,581 cues carried an empty `()` tag and
the only name present was the host's. `plugins/transcript_cleaner_ai_optimized.py`
folds an unnamed cue into whoever spoke last, so the entire session collapsed
into **one 44,318-character block attributed to a single person**, the recap
model was handed a wall of unattributed text, hit `max_tokens`, and emitted no
frontmatter. The validation gate caught it and refused to publish.

Meet had not lost the attribution — it moved it, in the same reorganisation
that moved the recordings into `Google Meet/<meeting name>/`. Each meeting now
also produces a **`… - Transcript` document** beside the recording, and that
document still names everyone: 1,927 attributed lines across four speakers for
the session the caption track had reduced to one.

`scripts/meet_transcript.py` converts that document back into the SRT shape the
cleaner reads, so nothing downstream changes. Rebuilt from the document, the
same session cleans to 126,772 characters across 1,585 dialogue blocks and four
speakers.

`extract` prefers that document automatically. When one exists beside the
recording it is exported, converted, and used — and the caption track is **not
pulled at all**, rather than pulled and discarded. Meet names the pair
identically apart from the final word, so the document is derived from the
recording's own name rather than searched for blindly. Audio extraction is
untouched: the release needs the MP3 either way.

Every fallback is deliberate. No document, an export that fails, or a document
holding no attributed lines all fall back to the caption track, because a
worse transcript still beats losing the episode. Drive being unreachable does
too — that step did not need Drive before this, and a network blip must not
cost an extraction the video alone can satisfy.

Whichever source wins, the run reports how well attributed it is, and warns on
stderr when only one speaker is named. That is the Episode 62 shape exactly:
something was produced, but no recap can come from it.

The document marks time only every five minutes, so cues are spread evenly
across each section. That is accurate to within the window and never out of
order — coarser than a caption track, and finer than the recap needs, since
timestamps anchor narrative sections rather than quote to the second.

### Two files hold all the state

- **`workspace/metadata.json`** — per-run scratch, thrown away with the runner.
  The stages hand each other paths and URLs through it.
- **`data/episodes.json`** — the durable registry, committed to `main` at the
  end of every run, successful or not. It records which stages an episode has
  completed and is the *only* thing standing between a re-run and a duplicate
  release, a duplicate podcast entry, or a second SRT PR.

### Every stage has to be safe to run twice

Because the registry is committed at the end of the job, a run that dies —
or whose final push loses a race — leaves work done that the registry does not
know about. Episode 60 hit exactly that: release, feed and PR all succeeded,
the registry push was rejected by a PR that merged mid-job, and the record was
discarded. The next run then found the release already published, skipped the
release step, and died on `KeyError: 'audio_url'` after re-downloading 1.2 GB.

So each stage resolves its own state from the world rather than trusting the
registry to be complete:

| Stage | Already-done check | Result |
|-------|--------------------|--------|
| `extract` | the MP3 is still in `workspace/` — the registry alone is not enough, `workspace/` dies with the runner | re-extracts, and republishes the paths either way |
| `release` | a published release whose title carries this session date | reuses it and reads its MP3 asset URL back off GitHub |
| `update-feed` | an `<item>` in `feed.xml` with this episode's guid | leaves the feed alone |
| `open-pr` | an open PR whose head is `srt/episode-N`, or an SRT already on `main` | reuses the PR, or opens none |

The workflow reflects the same rule. The release step is **not** gated on
whether a release exists — it is the step that resolves the audio URL, and
skipping it is what broke the resume path. Only a release this run actually
created sets `RELEASE_CREATED_THIS_RUN`, so the delete-on-failure cleanup can
never remove an artifact belonging to an earlier run.

### Failures are announced

The registry commit rebases onto `origin/main` and retries rather than dropping
its changes, and a broken intake ends the run non-zero so it shows red, with
the problem and its remedy on the run page.

**There is no push notification for a failed intake.** The Discord failure
notice was removed on request; a red run in the Actions tab is the whole
signal. The 2026-08-22 run is what that costs when nobody looks: it died 24
seconds in and sat unnoticed until Monday, turning a four-minute failure into
a missed week of publishing. Anyone relying on this pipeline should watch the
Actions tab, or subscribe to failed-run notifications for the repository.

### After the pipeline

`open-pr` leaves a PR titled `Add SRT for Episode N`. Merging it lands an
`.srt` in `transcripts_raw/` on `main`, which fires **Generate Session Notes**
— the recap, the site build, the deploy and the Discord post. The pipeline
deliberately stops at the PR: nothing is published until someone merges.

Run the tests with `python -m pytest scripts/tests/ -q`.

## comic_scene.py

Turns a scene from a session into a comic-book page and embeds it in that
session's recap, directly under the scene's `###` heading. Run on demand,
never automatically: the group picks the moments worth drawing.

### Easiest: the Draw Comic workflow

Actions → **Draw Comic** → Run workflow from `main` with the session number
(leave *scene* blank to let Claude choose, or paste a recap heading). It opens
a "Comic for session N" PR; merging it publishes the page. To fix a panel,
edit `data/comics/<slug>/script.json` on the PR branch and run Draw Comic
again **from that branch** with mode `redraw` (add a panel number to redraw
just one) or `letter-only` for wording changes, which costs nothing.

Needs a `GEMINI_API_KEY` repository secret next to `ANTHROPIC_API_KEY`; see
**Gemini key and budget** below. The image model defaults to
`gemini-3-pro-image-preview`; set a `GEMINI_IMAGE_MODEL` repository variable
to change it without a code change.

### Gemini key and budget

Comics are billed to whoever owns the Gemini key, and Gemini's image models
have no free tier. So the key lives in its own Google project with a hard
monthly cap, and the script has a per-run cap of its own. Google's menu
names move around; if a label below has changed, the
[billing docs](https://ai.google.dev/gemini-api/docs/billing) have the
current one.

**What it costs** (Google's list prices as of October 2026; check the
[pricing page](https://ai.google.dev/gemini-api/docs/pricing)):

| Run | Gemini image requests | Approx. cost |
|-----|-----------------------|--------------|
| One 3-panel comic | 3 | $0.40 |
| One 6-panel comic | 6 | $0.80 |
| Redraw one panel | 1 | $0.13 |
| One reference portrait | 1 | $0.13 |
| Portraits for the whole sheet (15) | 15 | $2.00 |
| `--letter-only` | 0 | free |

That is about $0.134 per image for Nano Banana Pro at the default resolution,
plus a fraction of a cent for the reference images it reads. A retry after
a blocked image is another request. The Claude call that writes the script
is billed separately, to `ANTHROPIC_API_KEY`: one call that reads the whole
transcript, roughly $0.25–0.50 per comic.

**1. Create the key in its own project**
1. Sign in at [Google AI Studio](https://aistudio.google.com) with the Google
   account that will pay.
2. Open **Get API key** (or **API keys**) → **Create API key** → **Create in a
   new project**, and name the project something like `moonfall-comics`. A
   project of its own keeps comic spend out of anything else on the account,
   and gives it its own cap.
3. Next to the new key, choose **Set up billing** and attach a billing account.
   Image generation fails until you do.

**2. Cap the spend** (the actual budget limit)
1. In AI Studio open **Spend**, pick the `moonfall-comics` project, then
   **Monthly spend cap** → **Edit spend cap**. Setting it needs the project's
   owner, editor or admin role.
2. **$10/month** is a sensible start: about ten full comics with redraws, or
   every portrait several times over. Once the project reaches the cap, Gemini
   refuses requests (HTTP 429) until the month rolls over or someone raises it.
3. Google enforces the cap up to **about 10 minutes late**, and you pay for
   whatever runs in that window. That is why the script also stops itself at
   `COMIC_MAX_IMAGES` requests per run (default 10, retries included). It
   refuses a run that needs more than that before making a single request,
   and every run ends by printing its request count and estimated cost.
4. Optional: in the Google Cloud console under **Billing → Budgets & alerts**,
   add a budget for the same amount to get emails at 50/90/100%. Budgets only
   warn; the AI Studio cap is what actually stops spending.

**3. Lock the key down** (optional, recommended)

In the [Google Cloud console](https://console.cloud.google.com) for that
project: **APIs & Services → Credentials** → the key → **API restrictions →
Restrict key** → only **Generative Language API**. A leaked key then can't be
used for any other Google service.

**4. Give it to GitHub**
1. On GitHub open `justin-hale/moonfall-docs` → **Settings → Secrets and
   variables → Actions**. Only a repository admin sees **Settings**.
2. **New repository secret**, name `GEMINI_API_KEY`, paste the key, save.
   Never paste the key into an issue, PR, commit or chat; the secret store is
   the only place it goes.
3. Optional, on the **Variables** tab: `COMIC_MAX_IMAGES` to change the
   per-run cap, `GEMINI_IMAGE_MODEL` to switch models (a Flash image model is
   cheaper per image; update `GEMINI_PRICE_PER_IMAGE` locally if you want the
   printed estimate to match).

**5. Check it with the cheapest possible run**

Run **Draw Comic** with mode `portraits` and target `Bru`. That is one image,
about $0.13. It should open a PR with `static/img/characters/bru.webp`, and the
spend should appear on AI Studio's **Spend** page shortly after. Keep the
portrait if Bru's player likes it; otherwise close the PR.

To run locally instead, `export GEMINI_API_KEY=...` in your shell. Don't put
it in a file in the repo.

### Locally

```bash
pip install anthropic google-genai pillow pydantic
python scripts/comic_scene.py 64                      # Claude picks the scene
python scripts/comic_scene.py 64 --scene "The Missile"
python scripts/comic_scene.py 64 --script-only        # script only, no art
python scripts/comic_scene.py 64 --redraw --panel 3   # after editing script.json
python scripts/comic_scene.py 64 --letter-only        # re-letter, no API calls
python scripts/comic_scene.py --portraits Bru         # reference portrait
```

### How it works

1. **Script**: Claude reads the recap and the transcript and writes 3–6
   panels: what to draw, a caption, and dialogue trimmed from what was said
   at the table. The transcript decides, as with `/fix-notes`. Any line it
   cannot find in the transcript is printed (and lands in the PR body) as
   "Check against the transcript". The KB's name-correction table is applied
   to every word, the same guardrail recaps get.
2. **Art**: Gemini draws each panel with no text in it. Characters come from
   `data/character-sheets.json`; once a character has an approved portrait
   (`reference`), it is passed as a reference image so they look the same
   from panel to panel. The previous panel is passed too, to keep the style
   steady. Raw panels are kept in `data/comics/<slug>/`.
3. **Lettering**: Pillow lays out the page and adds captions, balloons and
   sound effects in code (fonts in `scripts/fonts/`, both SIL OFL). The
   model never draws text, so names can't come out misspelled. The page is
   written to `static/img/comics/<slug>.webp`.

### Character sheets

`data/character-sheets.json` holds only what the table has actually said
about how each character looks; each entry's `gaps` lists what nobody has
described, which the art model will otherwise make up. Filling those in,
then generating a portrait per PC with `--portraits` and keeping the one its
player likes, does more for consistency than anything else.

Art the group already has works as a reference too. Save it at the path in
the character's `reference` field (`static/img/characters/<name>.webp`; any
image format opens, but keep the name) and commit it. A character whose
`reference` file does not exist yet is simply drawn from the description.
Silas, Bru, Elspeth, Olivia, Leliana and Scarlet have portraits. Bru's and Leliana's
are small screenshots for now; replace them with the full-size originals when
someone finds them (same filename).

## Other Scripts

### generate-sessions-data.js

Generates session metadata for the Docusaurus site.

### add-session-positions.js

Adds position metadata to session files for proper ordering.

---

## Contributing

When adding new automation scripts:
1. Add comprehensive help text and documentation
2. Use argparse for command-line options
3. Provide clear error messages
4. Update this README with usage examples
