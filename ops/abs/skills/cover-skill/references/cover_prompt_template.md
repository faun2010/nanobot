Use this block when instructing Nanobot to process cover images only.

```text
Task: prepare_cover_strict

Inputs:
- album_dir: <ABS_ALBUM_DIR>
- source_image: <IMAGE_FILE> (default 01.jpg)
- split_side: right|left|none
- target_size: 1024
- min_cover_size: 600
- catalog_number: <CATNO> (optional)

Rules:
1) Source image must exist.
2) If source is not JPG, convert it to JPG first.
3) If no image exists, recover source from `*_cover.jpf` or FLAC embedded picture.
4) If local recovery fails or image too small, lookup online by catalog number:
   - priority: MusicBrainz/Cover Art Archive
   - fallback: Discogs -> Amazon -> eBay
   - reject online image if width/height < 600
5) Generate cover.jpg from source image.
6) If split_side=right|left, crop using WhiteBull cut script.
7) Normalize to square with size rules:
   - if source >1024: output 1024x1024
   - if source in [600,1024]: keep size, only square-normalize
   - if source <600 on any side: fail
8) Validate:
   - cover.jpg exists
   - MIME is image/jpeg
   - output is square
   - output >=600x600
9) If all recovered/downloaded sources are <600, fail with explicit "need larger cover source".
10) On missing/low-res source after all attempts, write `cover_missing.todo.json` in album root.
11) Any failed check must return explicit error and stop.
12) These constraints apply to cover.jpg only; back.jpg has no such size/square limits in this flow.
13) back.jpg is optional and can be missing (the only allowed missing file in this step).
14) Do not assume opposite-side spread equals true CD back.
15) If back.jpg is missing, scan all existing JPG/JPEG files and infer the most likely CD back by full-image scoring.
16) Back inference must not crop/split from one source image side.
17) If no high-confidence back candidate exists, keep back.jpg missing (do not fail cover flow).

Command:
skills/cover-skill/scripts/prepare_cover_strict.sh \
  --album-dir "<ABS_ALBUM_DIR>" \
  --source-image "<IMAGE_FILE>" \
  --split-side "<right|left|none>" \
  --catalog-number "<CATNO>" \
  --online-min-size 600 \
  --min-cover-size 600 \
  --target-size 1024

Output:
- JSON with ok/cover_path/width/height/mime/backup_files (back_path/back_inferred_from may be null).
```
