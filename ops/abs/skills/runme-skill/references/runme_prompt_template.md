Use this block when instructing Nanobot to run strict non-interactive runme processing.

```text
Task: process_runme_strict

Inputs:
- album_dir: <ABS_ALBUM_DIR>
- work_index: <OPTIONAL_REPEATABLE_INT>
- from_index: <OPTIONAL_INT>
- to_index: <OPTIONAL_INT>
- publish: false|true

Rules:
1) Replace interactive paga review with strict automation:
   - no vi/manual runme editing.
2) For each target work:
   - ensure runme template exists (handel_initCD.sh)
   - fill base runme with bach_fillRunme.sh
   - enrich with runme_enricher.py (optional)
   - canonicalize Composer/Album/Genre/Titles by IMSLP catalog matching (fallback abs_music_db)
   - run strict correction/validation on runme write/show/info keys
3) Managed keys must be unique in runme (deduplicate duplicates):
   - Composer/Album/Genre/Titles
   - Solo/Conductor/Orchestra/Year/Tail
   - Art/Release/Box
4) Hard validation gates:
   - Composer/Album/Genre/Titles/Year must be valid
   - Titles count must match audio track count
   - Year must be 4-digit and in allowed range
   - Genre must be normalized to WhiteBull valid set
   - Album must exactly match canonical `title` from `imslp/abs_<composer>_db.json`
   - If Album is not present in that composer db title list, fail validation and do NOT publish
   - Ballet works must normalize Genre=Ballet
   - For non-chamber/non-solo/non-concerto works: Solo must be "-" (or empty) and Conductor is the primary version anchor
5) If validation fails for any work, return explicit error; never claim success.
6) Before publish, run an independent final exact guard:
   - Composer must exactly match IMSLP complete_name
   - Album must exactly match IMSLP work title for that composer
   - If guard fails, do NOT publish
7) If publish=true, run `bash runme force` only after strict validation + final exact guard both pass.

Command:
skills/runme-skill/scripts/process_runme_strict.sh \
  --album-dir "<ABS_ALBUM_DIR>" \
  --json

Output:
- JSON summary with per-work steps, validator corrections, and failure reasons.
```
