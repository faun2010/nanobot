Use this when asking Nanobot to do final publish with existing WhiteBull scripts.

```text
Task: process_publish_strict

Inputs:
- album_dir: <ABS_ALBUM_DIR>
- target_root: <ABS_TARGET_ROOT>
- work_index: <OPTIONAL_REPEATABLE_INT>
- from_index: <OPTIONAL_INT>
- to_index: <OPTIONAL_INT>
- overwrite_dup_cache: false|true
- force_overwrite_dup_cache: false|true (required only when bypassing duplicates on source albums)
- move_to_done: true|false
- done_dir: <OPTIONAL_ABS_DONE_DIR>

Rules:
1) Use existing WhiteBull publish chain; no manual mv/cp only workflow.
2) Keep runme validation before publish.
3) Enforce final independent exact guard before publish:
   - Composer must exactly match IMSLP complete_name
   - Album must exactly match IMSLP work title for that composer
   - If guard fails, block publish
4) Publish to MUSIC_ROOT=<ABS_TARGET_ROOT>.
5) If duplicate cache blocks and overwrite_dup_cache=true, allow OVERWRITE=1.
   For source albums, also require force_overwrite_dup_cache=true; otherwise refuse.
6) After publish, clean hidden files (.DS_Store, ._*) in source album dir and published target dirs.
7) After successful publish, move source album dir into sibling 0_done/ (unless move_to_done=false).
8) Return JSON step summary, cleanup summary, postprocess summary, and final target path.

Command:
skills/publish-skill/scripts/process_publish_strict.sh \
  --album-dir "<ABS_ALBUM_DIR>" \
  --target-root "<ABS_TARGET_ROOT>" \
  --work-index 0 \
  --json
```
