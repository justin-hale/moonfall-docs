---
description: Correct a published session recap against the transcript, in the Chronicle's persona voice
argument-hint: <session number> — <what is wrong>
allowed-tools: Read, Edit, Write, Grep, Glob, Bash
---

# /fix-notes

Correct a published recap in `docs/sessions/`. A correction is not just an edit to
one line: it is a fix propagated to every place the error was copied, recorded in
the campaign memory, and — for sessions inside the publication arc — printed as a
signed correction notice in the recap's own voice.

**Correction request:** $ARGUMENTS

If the request does not name a session, ask which one before doing anything else.

---

## 1. Establish what actually happened

The transcript is the only source of truth. The recap, `data/campaign-state.md`,
and your own memory of the session are all downstream of it and can all be wrong
in the same way.

1. Find the session file: `docs/sessions/session-N.md` (or `interlude-N.md`).
2. Find its transcript. Match `date:` in the frontmatter against
   `docs/transcripts/YYYY-MM-DD.md`. **If no transcript carries that date, the
   date itself is suspect** — grep the transcripts for a distinctive proper noun
   from the recap (an NPC name, a location, a running joke) to find the real one,
   and correct the `date:` field and the `***Month D, YYYY***` line to match.
3. Grep the transcript for the disputed detail and read the surrounding 100–200
   lines. The transcripts are speech-to-text with overlapping speakers: names are
   mangled, lines interleave, and a single sentence may be split across four
   turns by two people. Read enough context to be sure who was speaking.
4. Check `data/campaign-kb.md` for the canonical spelling of every name involved
   and for the known-transcription-errors table.

**Do not correct anything you could not confirm in the transcript.** If the
transcript is genuinely ambiguous, say so and ask — a confidently wrong
correction is worse than the original error.

### Failure modes worth checking for specifically

- **PC/NPC conflation.** The generator merges an NPC into a PC when they share a
  profession, a name shape, or a scene. Before crediting a PC with an action,
  confirm that PC's *player* was speaking in that part of the transcript — a
  DM-voiced party member is not the same as a player-driven one, and a player who
  joins late did nothing in the first hour.
- **Transcription leakage.** Google Meet handles (`Tyram`), mangled names
  (`Brew`, `Ellsworth`, `Liliana`, `Elderan`), and mis-heard NPC names reaching
  the published page — including inside quotations, which get less scrutiny.
- **Invented specificity.** Dice totals, DCs, and full names that appear in the
  recap but nowhere in the transcript.
- **Date drift.** As above: `date:` must equal the transcript's date.

## 2. Fix the recap

Apply the correction everywhere it landed in the file, not just the sentence the
user quoted. A single wrong fact typically appears in the `description` and
`summary` frontmatter, in one or two Plot Events sections, and again in Notable
Character Moments, Themes, or Session MVP. Grep the file for the wrong name or
claim and confirm you have zero hits left.

Rewrite in the recap's existing voice and keep it the same shape — matched
detail and length, existing `/player-characters/` and `/npcs/` links preserved.
A correction should read as though the page had always been right.

**Never touch** the byline, the editorial notes, or the `author:` / `beat:`
frontmatter. Those belong to the publication arc, not to the correction.

## 3. Print the correction in persona (sessions in a beat only)

Read `corrections` in `data/publication-arc.json` — heading, placement, dateline,
rules, and the per-persona correction voice — and follow it.

The notice is issued by the persona named in **that session's** `author:`
frontmatter, not by whoever holds the masthead today; the beat named in its
`beat:` field sets how hostile the co-author's reaction is. A session whose
frontmatter has no `author:` predates the arc: fix it silently and **never**
add a persona notice, byline, or editorial note to it.

The notice corrects the *record*. It never re-narrates the scene, never
contradicts the text you just fixed, and never mentions transcripts, generators,
models, or the DM — in-world, the publication simply misprinted something.

## 4. Propagate to campaign memory

- `data/campaign-state.md` — the running memory carries the same error in the
  per-session summary, the "Session N Updates" character notes, and often in
  Key Callbacks. Fix all of them. Keep this file persona-neutral: in-world
  campaign events only, never publication-meta content.
- `data/campaign-kb.md`:
  - Add any newly confirmed NPC to the recurring-NPC table with their transcript
    aliases.
  - Add each new mis-hearing to the known-transcription-errors table so the
    generator stops repeating it.
  - Append an entry to the **Session Correction Log** — session number and date,
    one bullet per fix with its source (`[user-reported]` / `[known
    transcription error]` / `[confirmed against transcript]`), and, when the
    error has a shape that will recur, a short **Pattern:** note naming it.
- If the correction establishes a recurring NPC worth a page of their own, say so
  and offer — don't create `docs/npcs/*.md` unprompted.

## 5. Verify, commit, push

```bash
npm run build          # catches broken links and MDX breakage
git diff               # read every hunk before committing
```

Commit with a message naming the session and the substance of the fix, push to
the working branch, and open a draft PR if one is not already open.

## Report back

Tell the user, briefly:
- what the transcript actually says, with the evidence that settles it;
- every file touched and what changed in each;
- anything the transcript could not settle, stated as an open question rather
  than quietly resolved.
