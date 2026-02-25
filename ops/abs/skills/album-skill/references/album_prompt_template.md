Use this block when instructing Nanobot to fetch album-level MusicBrainz DB metadata.

```text
Task: fetch_album_musicbrainz_db

Inputs:
- album_dir: <ABS_ALBUM_DIR>
- catalog_no: <OPTIONAL_CATNO>
- release_id: <OPTIONAL_RELEASE_MBID>
- force: false|true
- split_works: true|false (default true)
- works_spec: <OPTIONAL_MANUAL_WORK_GROUPS>

Rules:
1) Use existing WhiteBull tools only:
   - absolutely/musicbrainz_release_search.sh
   - skills/album-skill/scripts/discogs_release_search.py
   - absolutely/mb_wgetRelease.py
   - absolutely/liszt_digWorksNum.sh
   - absolutely/jcbach_dispatchCoverJson.sh
2) Prefer release_id if provided; otherwise resolve by catalog number candidates.
3) If catalog_no is missing, infer catno from local artifacts in this order:
   - metadata json/db catno fields
   - directory name patterns ([446172-2], CD 098)
   - file/path names
   - cue/log/txt text
   - pdf text (pdftotext)
   - image OCR (tesseract)
4) Reject weak/false candidates (discid hex, CRC-like tokens, dates, track/index directives).
5) Search order:
   - MusicBrainz catno
   - MusicBrainz release-title hints
   - Discogs catno/title hints fallback
6) Keep all online scratch artifacts in /Users/panzm/Music/whitebull/_tmp.
7) Write only final files to album directory:
   - if provider=musicbrainz: musicbrainz_0.db + musicbrainz_0.json
   - if provider=discogs: discogs_0.db + discogs_0.json
8) Candidate acceptance must verify:
   - expected track count (prefer cue TRACK count when local FLAC is still single image)
   - title/artist token overlap with local hints (folder + cue performer/title)
9) If one candidate release fails fetch/parse/consistency checks, try next candidate.
10) After metadata is ready, split different works:
   - if works_spec is provided: run liszt_digWorksNum.sh "<works_spec>"
   - otherwise run liszt_digWorksNum.sh auto only when inferred work groups >= 2
   - if top-level split tracks do not exist, skip work split without error.
11) After split is applied and cover.jpg exists in album root, run:
    - jcbach_dispatchCoverJson.sh --skip-resize --skip-runme
    This must dispatch cover/back/runme and metadata json files to numbered work dirs.

Command:
skills/album-skill/scripts/fetch_musicbrainz_db_strict.sh \
  --album-dir "<ABS_ALBUM_DIR>" \
  --json

Output:
- JSON summary including provider, selected release_id, search strategy, candidate counts, written files, work-split status, and dispatch status fields.
```
