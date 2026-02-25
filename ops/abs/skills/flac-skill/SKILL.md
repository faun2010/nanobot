---
name: flac-skill
description: Use when Nanobot must preprocess music sources into FLAC by running conversion (APE/WV/WAV), CUE-based splitting, and FLAC file normalization before downstream organization.
---

# Flac Skill

## Overview

This skill provides a deterministic preprocessing flow for FLAC libraries.
It handles conversion, cue normalization, cue splitting, and emits a strict summary for automation.

## When To Use

Use this skill when requests include:
- convert lossless sources (`.ape`, `.wv`, `.wav`) into `.flac`
- split single-image FLAC files by CUE definitions
- normalize and prepare FLAC trees before metadata publishing/classification

## Required Inputs

Collect:
- `source_dir` (absolute path)
- optional `split_template` (default `%n - %t`)
- optional strict flags: `--keep-source-after-split`, `--remove-wav-source`, `--keep-ape-source`, `--skip-consolidate`

## Hard Constraints

Always enforce:
- conversion/splitting scope is FLAC preprocessing only (no cover logic here)
- this skill does not manage FLAC tags/metadata fields
- cover/back processing must be delegated to `skills/cover-skill`
- if source FLAC is damaged, skip split for that file (no recovery attempt in this skill)
- default behavior: remove unsplit source FLAC only after split output is confirmed complete and readable
- if split completeness check fails, keep source FLAC and record skip in summary
- fail fast on tool-missing or fatal split errors (unless `--continue-on-error`)
- output summary must be machine-readable when `--json` is requested

## Tool Chain

Fixed script chain used by this skill:
- `absolutely/my_ape2flac.sh` (`.ape`/`.wv` -> `.flac`)
- `absolutely/my-wav2flac.sh` (`.wav` -> `.flac`)
- `absolutely/my_iconv_cue.sh` (CUE encoding normalization)
- `absolutely/segovia_splitFlacWithCue.sh` (split FLAC by CUE)
- `absolutely/berlioz_multiCDMove.sh` (multi-disc filename consolidation to album root)
- internal cleanup: remove `._*`/`.DS_Store`, normalize extension case, rewrite CUE refs to `.flac`
- split-track sequence normalization: normalize irregular track filename prefixes (e.g. `1. title.flac` -> `01 - title.flac`) before downstream album/runme processing
- multi-disc regroup guard: if one folder contains multiple unsplit FLAC+CUE images, regroup them first into numbered subfolders (`1`, `2`, `3`...) by CD order, then split inside each subfolder
- per-file split guard: before each FLAC split, preprocess matched CUE (UTF-8/BOM/CRLF normalization + force first `FILE` row to current FLAC basename)
- integrity guard: run `flac -t` before split; damaged source FLAC must be skipped (record as damaged)
- post-split source cleanup guard: verify split count/integrity first, then delete unsplit source FLAC by default
- post-split single-disc guard: if only one disc subfolder has split tracks, directly move split tracks to album root (no disc prefix tool)
- post-split multi-disc guard: if two or more disc subfolders have split tracks, use existing multi-disc tool to move to album root with disc prefix

## Workflow

Run:
```bash
skills/flac-skill/scripts/process_flac_strict.sh \
  --source "$SOURCE_DIR" \
  --target-split-template "%n - %t" \
  --json
```

Optional strict cleanup:
```bash
skills/flac-skill/scripts/process_flac_strict.sh \
  --source "$SOURCE_DIR" \
  --keep-source-after-split \
  --remove-wav-source \
  --json
```

## Output Contract

JSON output includes:
- `ok`
- `source_dir`
- `cleanup`
- `counts_before`
- `counts_after`
- `conversion`
- `split`

## Instruction Template

Use:
- `references/flac_prompt_template.md`
