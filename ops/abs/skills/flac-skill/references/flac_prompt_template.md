Use this block when instructing Nanobot to preprocess FLAC files only.

```text
Task: preprocess_flac_strict

Inputs:
- source_dir: <ABS_SOURCE_DIR>
- split_template: "%n - %t"
- keep_source_after_split: false|true (default false: source FLAC will be removed after verified split)
- remove_wav_source: false|true
- keep_ape_source: false|true

Rules:
1) Clean sidecar junk (`._*`, `.DS_Store`) and normalize extension case.
2) Convert `.ape`/`.wv` to `.flac`.
3) Convert `.wav` to `.flac`.
4) Normalize `.cue` encoding to UTF-8.
5) Rewrite CUE FILE refs `.ape/.wv/.wav` -> `.flac`.
6) If one folder has multiple unsplit FLAC+CUE images (multi-CD set), regroup first by CD order:
   - put CD1-related files into subfolder `1/`, CD2 into `2/`, ...
   - then split inside each CD subfolder; never split all discs together in one folder
7) Before each FLAC split, preprocess that matched CUE again:
   - normalize UTF-8 / remove BOM / normalize CRLF to LF
   - force first `FILE "..."` row to current FLAC basename
8) Before split, verify source FLAC integrity with `flac -t`; if damaged, skip this file and do not attempt recovery.
9) Split single-file `.flac` using matching CUE.
10) After split, verify generated tracks are complete/readable; then remove unsplit source FLAC (default behavior). If verification fails, keep source FLAC.
11) Post-split placement rule:
   - single disc: move split tracks from disc subfolder to album root directly
   - multi disc: use existing script tool (`absolutely/berlioz_multiCDMove.sh`) to consolidate with disc prefix naming.
12) Continue on per-file split failure unless explicitly asked to stop.
13) This flow must not apply cover/back constraints (handled by cover-skill).

Command:
skills/flac-skill/scripts/process_flac_strict.sh \
  --source "<ABS_SOURCE_DIR>" \
  --target-split-template "%n - %t" \
  --json

Output:
- JSON summary with before/after counts, conversion stats, split stats, and ok flag.
```
