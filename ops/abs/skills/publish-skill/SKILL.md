---
name: publish-skill
description: Use when the final step must publish processed work folders (0/1/2...) into MUSIC_ROOT using existing WhiteBull publish scripts with validation, not manual file moves.
---

# Publish Skill

## Goal

Publish processed work folders into target library by reusing existing WhiteBull scripts:
- `runme -> abs_runme.sh -> abs_ccdt.sh -> publish.sh -> schubert_copyToTaget.sh`

This keeps built-in checks (track count/year/tag-cache conflict checks) and avoids ad-hoc `mv`.

## Required Inputs

- `album_dir` (absolute)
- `target_root` (absolute, mapped to `MUSIC_ROOT`)

Optional:
- work selector (`work_index` or `from_index/to_index`)
- duplicate-cache bypass (`--overwrite-dup-cache`)

## Command

Publish-only (recommended for confirmed runme):
```bash
skills/publish-skill/scripts/process_publish_strict.sh \
  --album-dir "$ALBUM_DIR" \
  --target-root "$TARGET_ROOT" \
  --work-index 0 \
  --json
```

If duplicate-cache blocks but you must publish:
```bash
skills/publish-skill/scripts/process_publish_strict.sh \
  --album-dir "$ALBUM_DIR" \
  --target-root "$TARGET_ROOT" \
  --work-index 0 \
  --overwrite-dup-cache \
  --json
```

## Notes

- Default mode is publish-only:
  - `--skip-fill --skip-enrich --skip-imslp-canonical` are applied internally.
- `--full-refresh` can be used to run full runme pipeline before publish.
- This skill delegates validation/publish execution to `skills/runme-skill/scripts/process_runme_strict.sh` to avoid duplicated logic.
- Before `runme force` publish, delegated runme-skill performs an independent exact guard:
  - `Composer` must exactly match IMSLP `complete_name`
  - `Album` must exactly match IMSLP work `title` for that composer
  - guard failure blocks publish
- After successful publish (non-dry-run), it automatically:
  - removes hidden files (`._*`, `.DS_Store`) and `.AppleDouble` dirs in source `album_dir`
  - removes hidden files (`._*`, `.DS_Store`) and `.AppleDouble` dirs in published target dirs
  - removes empty numeric work dirs (`0/1/2...`) in `album_dir` and their `._N` sidecar files
  - moves the completed source album dir into sibling `0_done/` (for progress tracking)
- If source move should be skipped, pass:
  - `--no-move-to-done`
- If `0_done` location must be customized, pass:
  - `--done-dir /absolute/path/to/0_done`
- Duplicate bypass safety:
  - Source album paths refuse `--overwrite-dup-cache` by default.
  - To force bypass on source (dangerous), you must add `--force-overwrite-dup-cache`.
  - Album paths inside `target_root` (repair mode) can still use `--overwrite-dup-cache`.
