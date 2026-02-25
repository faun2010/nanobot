---
name: nanobot-abs-organizer
description: Use when Nanobot should run WhiteBull discover/organize/publish flow from source and target directories, while keeping classification rules unchanged and cover processing delegated to cover-skill.
---

# Nanobot Abs Organizer

## Overview

Use this skill to run WhiteBull organization in a low-freedom, deterministic way.
It enforces fixed processing order for classification/publish and keeps cover logic separate.

## When To Use

Use this skill when requests include one or more of:
- Organize music from a possibly nested source directory into a target library automatically.
- Keep WhiteBull fixed classification rules while driving workflow via Nanobot.
- Enforce strict preprocessing before classification (format normalization, cue handling, runme publish flow).

## Required Inputs

Collect these values before running:
- `source_dir` (absolute path)
- `target_dir` (absolute path)

## Hard Constraints

Always enforce these:
- Do not change WhiteBull category logic.
- Do not embed cover-specific heuristics in this skill.
- FLAC preprocessing must be delegated to `skills/flac-skill` before organize/publish.
- If source FLAC is damaged, follow flac-skill rule: skip split and do not attempt recovery.
- Delegate all cover operations to `skills/cover-skill` when needed.

## Workflow

1. Run FLAC preprocessing first:
```bash
skills/flac-skill/scripts/process_flac_strict.sh --source "$SOURCE_DIR" --json
```

2. Discover albums:
```bash
python3 absolutely/nanobot_organizer.py discover --source "$SOURCE_DIR" --json
```

3. If an album needs cover processing, call `cover-skill` first:
```bash
skills/cover-skill/scripts/prepare_cover_strict.sh --album-dir "$ALBUM_DIR" ...
```

4. Run organization publish workflow:
```bash
python3 absolutely/nanobot_organizer.py organize \
  --source "$SOURCE_DIR" \
  --target "$TARGET_DIR" \
  --json
```

Single-entry strict chain (recommended for one-album one-shot):
```bash
skills/nanobot-abs-organizer/scripts/process_album_strict_once.sh \
  --album-dir "$ALBUM_DIR" \
  --target-root "$TARGET_DIR"
```

5. If user asks for preview only, use:
```bash
python3 absolutely/nanobot_organizer.py organize \
  --source "$SOURCE_DIR" \
  --target "$TARGET_DIR" \
  --dry-run \
  --json
```

## Instruction Template For Nanobot

Use the template in:
- `references/nanobot_prompt_template.md`
