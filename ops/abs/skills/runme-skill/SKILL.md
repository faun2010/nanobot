---
name: runme-skill
description: Use when Nanobot must replace interactive paga-style runme processing with strict non-interactive fill + correction, ensuring runme write fields are unique, reliable, complete, and publish-safe.
---

# Runme Skill

## Goal

Process split works (`0/1/2/...`) without manual `vi` review, while enforcing strict correctness for runme write/show/info fields.

This skill replaces the interactive gap in `paga $n` flow with deterministic auto-correction and validation.

## When To Use

Use this skill when requests include:
- run `paga`-like per-work runme generation automatically
- remove manual review and still avoid naming inconsistency/duplication
- guarantee runme write fields are unique, reliable, complete, and executable

## Required Inputs

Collect:
- `album_dir` (absolute path)
- optional work selection:
  - `work_index` (repeatable) or
  - `from_index` + `to_index`

## Hard Constraints

Always enforce:
- no interactive editor steps (`vi`) in this skill
- runme correction must be deterministic and repeatable
- write fields must prefer canonical work naming from `imslp/abs_<composer>_db.json` (fallback `absolutely/abs_music_db.json`) instead of raw MusicBrainz track-title fragments
- managed keys must be unique (deduplicate duplicate lines):
  - `Composer`, `Album`, `Genre`, `Titles`
  - `Solo`, `Conductor`, `Orchestra`, `Year`, `Tail`
  - `Art`, `Release`, `Box`
- final independent pre-publish guard:
  - run `scripts/validate_publish_exact_guard.py` immediately before publish
  - `Composer` must exactly match IMSLP `complete_name` (full name, character-exact)
  - `Album` must exactly match one IMSLP work `title` for that composer (character-exact)
  - if guard fails, publish must be blocked
- required correctness gates:
  - `Composer`, `Album`, `Genre`, `Titles`, `Year` must be valid after correction
  - `Titles` count must equal work audio track count
  - `Year` must be 4-digit and within allowed publish range
  - invalid genre must be normalized to WhiteBull allowed genre set
  - `Album` must be the exact canonical `title` from `imslp/abs_<composer>_db.json` (no character drift)
  - if `Album` is not found in that composer db title list, validation must fail and publish is forbidden
  - ballet works must normalize `Genre` to `Ballet`
  - for non-chamber / non-solo / non-concerto works, `Solo` must be `"-"` (or empty) and version anchor must prefer `Conductor`
- if any gate fails, return explicit error and do not claim success

## Tool Chain

- `absolutely/handel_initCD.sh` (ensure runme template exists)
- `absolutely/bach_fillRunme.sh` (base per-work fill)
- `absolutely/runme_enricher.py` (optional enrichment)
- `scripts/canonicalize_work_from_imslp.py` (IMSLP/abs_music_db canonical work title correction)
- `scripts/validate_runme_write_strict.py` (strict correction + validation)
- optional publish stage: `bash runme force`

## Workflow

Run:
```bash
skills/runme-skill/scripts/process_runme_strict.sh \
  --album-dir "$ALBUM_DIR" \
  --json
```

Specific work:
```bash
skills/runme-skill/scripts/process_runme_strict.sh \
  --album-dir "$ALBUM_DIR" \
  --work-index 1 \
  --json
```

Range:
```bash
skills/runme-skill/scripts/process_runme_strict.sh \
  --album-dir "$ALBUM_DIR" \
  --from-index 0 \
  --to-index 3 \
  --json
```

Publish after strict validation:
```bash
skills/runme-skill/scripts/process_runme_strict.sh \
  --album-dir "$ALBUM_DIR" \
  --publish \
  --json
```

## Output Contract

JSON output includes:
- `ok`
- `album_dir`
- `work_count`
- `indices`
- per-work `results[]` with:
  - `index`
  - `work_dir`
  - `ok`
  - `steps[]`
  - `validator` payload
  - `errors[]`

Validator payload includes:
- `corrected_fields`
- `removed_duplicate_keys`
- `inserted_missing_keys`
- `track_count`
- `title_count`
- `values`
- `errors`
- `warnings`

## Instruction Template

Use:
- `references/runme_prompt_template.md`
