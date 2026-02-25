Use this instruction block when telling Nanobot to run the organizer flow.

```text
Task: organize_music_strict

Inputs:
- source_dir: <ABS_SOURCE_DIR>
- target_dir: <ABS_TARGET_DIR>
- leaf_only: true
- continue_on_error: true

Rules:
1) Run FLAC preprocessing first:
   skills/flac-skill/scripts/process_flac_strict.sh --source "<ABS_SOURCE_DIR>" --json
2) If source FLAC is damaged, keep flac-skill behavior: skip split for that file (no recovery).
3) Keep WhiteBull classification flow and category rules unchanged.
4) Cover processing is handled only by cover-skill:
   skills/cover-skill/scripts/prepare_cover_strict.sh --album-dir "<ALBUM_DIR>" ...
5) After required cover steps, run:
   python3 absolutely/nanobot_organizer.py organize \
     --source "<ABS_SOURCE_DIR>" \
     --target "<ABS_TARGET_DIR>" \
     --json

Output:
- JSON report with per-album step results, errors, and final ok flag.
```
