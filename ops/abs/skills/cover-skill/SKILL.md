---
name: cover-skill
description: Use when Nanobot must generate/validate album cover.jpg from scan images with strict WhiteBull rules (fixed crop side, square output, exact size, explicit failure).
---

# Cover Skill

## Overview

This skill isolates all cover processing rules from the rest of the organization pipeline.
Use it to produce a deterministic `cover.jpg` without changing classification logic.

## When To Use

Use this skill when the request includes:
- create `cover.jpg` from spread scans (for example `01.jpg`)
- source image is PNG/BMP/WEBP/TIFF and must be converted to JPG first
- no cover image files exist and recovery from FLAC metadata is required
- when local recovery fails, online lookup by catalog number is required
- force square cover output with tiered sizing:
  `>=1024 -> 1024`, `550~1024 -> keep size`, `<550 -> stop`
- strict validation of output type and size
- fail-fast behavior (no silent fallback)

## Required Inputs

Collect:
- `album_dir` (absolute path)
- `source_image` (default `01.jpg`)
- `split_side` (`right|left|none`)
- `target_size` (default `1024`)
- `min_cover_size` (default `550`)
- optional `catalog_number` (if omitted, try to parse from album dir name like `[446172-2] ...`)
- optional `release_id` (preferred when known; supports MBID/MusicBrainz release URL, and Discogs release id/release URL)

## Hard Constraints

Always enforce:
- source image must exist
- non-JPG source must be converted to JPG before cover generation
- if no image exists, recover from `*_cover.jpf` or FLAC embedded picture
- if local recovery fails or image is too small, try online lookup by `release_id`, then catalog number + album title
- online lookup priority: MusicBrainz/Cover Art Archive -> Discogs -> Amazon -> eBay
- when `release_id` is a Discogs release id/url, fetch cover directly from that release; if secondary image exists, try to save it as `back.jpg`
- Discogs `release_id` path uses a curl-based fast fetch first, and falls back to the stable legacy path on failure
- MusicBrainz `release_id` path uses a CAA `front/back` fast fetch path first, with proxy-aware retries
- online candidates below `550x550` are rejected and search continues
- output must be `cover.jpg`
- output must be `image/jpeg`
- output must be square
- output minimum size must be `>=550x550`
- if source is `550~1024`, keep resolution (no upscale), only normalize to square
- if source is `>1024`, downsize to `1024x1024`
- `back.jpg` is out of scope for these limits (no min-size/square/resize constraint here)
- `back.jpg` is optional (this is the only file in this step that may be missing)
- do not assume opposite-side spread equals true CD back
- if `back.jpg` is missing, infer from existing JPG/JPEG files in album directory (full-image candidate scoring)
- back inference must not crop/split from one image side; only evaluate existing image files as candidates
- if inference confidence is low/ambiguous, keep `back.jpg` missing
- never fail cover flow because `back.jpg` is missing
- any check failure must stop with explicit error
- if all lookups fail or remain low-res (`<550x550`), fail and require manual补图
- when missing/low-res after all attempts, write `cover_missing.todo.json` in album root for later manual补图

## Workflow

Run:
```bash
skills/cover-skill/scripts/prepare_cover_strict.sh \
  --album-dir "$ALBUM_DIR" \
  --source-image "$SOURCE_IMAGE" \
  --split-side "$SPLIT_SIDE" \
  --catalog-number "$CATNO" \
  --online-min-size 550 \
  --min-cover-size 550 \
  --target-size "$TARGET_SIZE"
```

For `[446172-2] Brahms - The Complete Quintets`:
```bash
skills/cover-skill/scripts/prepare_cover_strict.sh \
  --album-dir "/Volumes/data3/abs_src/[446172-2] Brahms - The Complete Quintets" \
  --source-image "01.jpg" \
  --split-side right \
  --target-size 1024
```

## Output Contract

Success output is JSON and must include:
- `ok`
- `album_dir`
- `source_used`
- `split_side`
- `cover_path`
- `width`
- `height`
- `mime`
- `backup_files`

`back_path` is optional and can be `null`.
`back_inferred_from` is optional and can be `null`.

Online lookup helper:
- `skills/cover-skill/scripts/fetch_cover_online.py`
- `skills/cover-skill/scripts/detect_back_image.py`
- Optional env for higher Discogs quota: `DISCOGS_TOKEN`
- Network speed/stability options: `--proxy`, `--auto-proxy` (default on), `--network-retries` (default 3), `--probe-timeout` (default 2s)
- fetch result may include `fetch_mode=fast` when the Discogs fast path is used
- MB fast-path tuning envs:
  - `WHITEBULL_MB_TIMEOUT_CAP` (default `4` seconds per MB fast request)
  - `WHITEBULL_MB_JSON_FALLBACK` (`1/true` to enable slower CAA JSON fallback for special cases)
- `prepare_cover_strict.sh` auto-detects `release_id` from `_release_id.lst` / `musicbrainz_0.*` / `discogs_0.*` when available

## Instruction Template

Use:
- `references/cover_prompt_template.md`
