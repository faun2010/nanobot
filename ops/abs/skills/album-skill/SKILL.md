---
name: album-skill
description: Use when Nanobot must generate album metadata by inferring catalog number from local artifacts (dir/file/cue/pdf/image OCR), then searching MusicBrainz first and Discogs as fallback.
---

# Album Skill

## Goal

Generate album metadata DB/JSON for one album directory with strict rules:
- reuse existing WhiteBull online tools
- infer `catno` from local evidence first
- search MusicBrainz first; if unresolved, fallback to Discogs with same catno/title hints
- after metadata is ready, split different works via `liszt_digWorksNum.sh` (auto/manual)
- keep temporary artifacts under project-local `_tmp`

## When To Use

Use this skill when requests include:
- obtain album metadata DB (`musicbrainz_0.db` preferred; `discogs_0.db` fallback)
- refresh stale album-level metadata online
- resolve release id from `catno` or release title, then fetch release JSON
- separate different works into numbered subfolders (`0`, `1`, `2`, ...) after metadata fetch

## Required Inputs

Collect:
- `album_dir` (absolute album path)
- optional `catalog_no` override (e.g. `446 172-2`)
- optional `release_id` (MusicBrainz release MBID)
- optional `works_spec` override (e.g. `1,2,3;4,5`)
- optional `split_works` toggle (`true` default, `false` to skip)

## Hard Constraints

Always enforce:
- only use existing WhiteBull tools/scripts for online fetch/split (`musicbrainz_release_search.sh`, `mb_wgetRelease.py`, `discogs_release_search.py`, `liszt_digWorksNum.sh`)
- network fetch scratch must stay in `WHITEBULL_DIR/_tmp` (default: `/Users/panzm/Music/whitebull/_tmp`)
- write only final metadata outputs to album dir:
  - MusicBrainz path: `musicbrainz_0.db` + `musicbrainz_0.json`
  - Discogs fallback path: `discogs_0.db` + `discogs_0.json`
- work-split stage runs inside album dir and must not create temp files outside project/album scope
- when auto work split detects less than 2 work groups, skip split (do not force move to `0/`)
- if source metadata is invalid or fetched JSON cannot pass basic structure check, try next candidate
- never trust a single weak clue when better clues exist (keyword cue/json > directory prefix > OCR noise)

## Tool Chain

- `absolutely/musicbrainz_release_search.sh` (query release ids by `catno`)
- `scripts/discogs_release_search.py` (query Discogs release ids by `catno`/title)
- `absolutely/mb_wgetRelease.py` (download release metadata to `musicbrainz_0.db/json`)
- `scripts/detect_catalog_number.py` (local multi-source catno detector)
- `absolutely/liszt_digWorksNum.sh` (separate works into numbered folders)
- `absolutely/jcbach_dispatchCoverJson.sh` (after split, dispatch cover/back/runme/json into numbered work folders)
- `skills/album-skill/scripts/fetch_musicbrainz_db_strict.sh` (strict wrapper)

## Catno Inference Order

When `--catalog-no` and `--release-id` are both absent, infer `catno` from local artifacts in this order:
1. existing local metadata fields (`musicbrainz_0.*`, `discogs_0.*`) with keys like `catno/catalog-number`
2. directory name patterns (`[446172-2] ...`, `CD 098 ...`)
3. file names / relative paths that include catalog-like patterns
4. text files (`.cue`, `.log`, `.txt`, `.md`, `.nfo`) with keyword and pattern extraction
5. PDF text via `pdftotext` (if available)
6. image OCR via `tesseract` for `cover/back/pic*` etc. (if available)

Reject common false positives:
- `DISCID`, CRC/AccurateRip hex tokens, timestamps, month/date text, track/index directives

## Online Fallback Strategy

`fetch_musicbrainz_db_strict.sh` must follow:
1. if `release_id` provided: fetch directly
2. else detect local catno candidates and search MusicBrainz by `catno` variants
3. if MB catno misses: derive title hints from folder/cue title and search MB by `release`
4. iterate MB candidates, fetch each, validate JSON shape
5. validate candidate consistency before accept:
   - expected track count prefers cue `TRACK` count (when local flac is unsplit single image)
   - reject candidates with low title/artist token overlap against local hints (folder + cue performer/title)
6. if all MB candidates fail or MB has no candidates, run Discogs search with the same catno/title hints
7. iterate Discogs candidates with the same consistency checks
8. first valid candidate wins and writes provider-specific files (`musicbrainz_0.*` or `discogs_0.*`)
9. run work split stage:
   - `--works-spec SPEC` => run `liszt_digWorksNum.sh "$SPEC"`
   - otherwise auto infer groups from fetched metadata and run `liszt_digWorksNum.sh auto` only when groups >= 2
10. after split is applied and `cover.jpg` exists in album root, run `jcbach_dispatchCoverJson.sh --skip-resize --skip-runme` to copy paired assets (`cover/back/runme/discogs_0.json/musicbrainz_0.json`) into each numbered work dir

## Commands

Basic:

Run:
```bash
skills/album-skill/scripts/fetch_musicbrainz_db_strict.sh \
  --album-dir "$ALBUM_DIR" \
  --json
```

Disable work split:
```bash
skills/album-skill/scripts/fetch_musicbrainz_db_strict.sh \
  --album-dir "$ALBUM_DIR" \
  --no-split-works \
  --json
```

Manual work split spec:
```bash
skills/album-skill/scripts/fetch_musicbrainz_db_strict.sh \
  --album-dir "$ALBUM_DIR" \
  --works-spec "1,2,3;4,5,6" \
  --json
```

Explicit catno override:
```bash
skills/album-skill/scripts/fetch_musicbrainz_db_strict.sh \
  --album-dir "$ALBUM_DIR" \
  --catalog-no "446 172-2" \
  --force \
  --json
```

Explicit release MBID:
```bash
skills/album-skill/scripts/fetch_musicbrainz_db_strict.sh \
  --album-dir "$ALBUM_DIR" \
  --release-id "$RELEASE_MBID" \
  --json
```

## Output Contract

JSON output includes:
- `ok`
- `album_dir`
- `provider` (`musicbrainz` or `discogs`)
- `skipped_existing`
- `catalog_no`
- `detected_catalog_no`
- `catalog_source`
- `release_id`
- `search_used`
- `search_strategy`
- `query`
- `candidate_count`
- `mb_candidate_count`
- `discogs_candidate_count`
- `local_tracks`
- `cue_tracks`
- `expected_tracks`
- `tracks`
- `written`
- `work_split_enabled`
- `work_split_applied`
- `work_split_mode`
- `work_split_groups`
- `work_split_reason`
- `work_split_target`
- `work_split_spec`
- `dispatch_assets_applied`
- `dispatch_assets_reason`

## Instruction Template

Use:
- `references/album_prompt_template.md`
