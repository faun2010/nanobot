#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  fetch_musicbrainz_db_strict.sh --album-dir DIR [options]

Purpose:
  Fetch album-level metadata online using existing WhiteBull tools.

Core chain (existing tools only):
  1) absolutely/musicbrainz_release_search.sh   (MusicBrainz catno/release -> MB release id)
  2) scripts/discogs_release_search.py          (Discogs catno/title -> Discogs release id)
  3) absolutely/mb_wgetRelease.py               (id -> musicbrainz_0.* or discogs_0.*)
  4) absolutely/liszt_digWorksNum.sh            (optional work split)
  5) absolutely/jcbach_dispatchCoverJson.sh     (dispatch cover/back/runme/json to split work dirs)

Options:
  --album-dir DIR           Target album directory to receive metadata db/json
  --catalog-no STR          Catalog number override (e.g. "446 172-2")
  --release-id MBID         Release MBID override (skip search)
  --limit N                 Search limit for release candidates (default: 5)
  --force                   Force re-download even if target already has metadata db
  --skip-track-check        Do not require fetched track count to match local FLAC count
  --split-works             Run liszt_digWorksNum.sh to separate different works (default)
  --no-split-works          Disable work splitting stage
  --works-spec SPEC         Manual works grouping spec passed to liszt_digWorksNum.sh
  --json                    Print JSON summary
  --debug                   Debug logging
  -h, --help                Show this help
USAGE
}

ALBUM_DIR=""
CATNO=""
RELEASE_ID=""
LIMIT=5
FORCE=0
SKIP_TRACK_CHECK=0
SPLIT_WORKS=1
WORKS_SPEC=""
OUTPUT_JSON=0
DEBUG=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --album-dir)
      ALBUM_DIR="${2:-}"
      shift 2
      ;;
    --catalog-no)
      CATNO="${2:-}"
      shift 2
      ;;
    --release-id)
      RELEASE_ID="${2:-}"
      shift 2
      ;;
    --limit)
      LIMIT="${2:-}"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --skip-track-check)
      SKIP_TRACK_CHECK=1
      shift
      ;;
    --split-works)
      SPLIT_WORKS=1
      shift
      ;;
    --no-split-works)
      SPLIT_WORKS=0
      shift
      ;;
    --works-spec)
      WORKS_SPEC="${2:-}"
      shift 2
      ;;
    --json)
      OUTPUT_JSON=1
      shift
      ;;
    --debug)
      DEBUG=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$ALBUM_DIR" ]]; then
  echo "ERROR: --album-dir is required" >&2
  exit 2
fi

if [[ ! -d "$ALBUM_DIR" ]]; then
  echo "ERROR: album directory not found: $ALBUM_DIR" >&2
  exit 2
fi

if ! [[ "$LIMIT" =~ ^[0-9]+$ ]] || [[ "$LIMIT" -lt 1 ]] || [[ "$LIMIT" -gt 100 ]]; then
  echo "ERROR: --limit must be integer in [1,100]" >&2
  exit 2
fi

if [[ -n "$WORKS_SPEC" ]] && [[ "$SPLIT_WORKS" -ne 1 ]]; then
  echo "ERROR: --works-spec requires work split enabled (remove --no-split-works)" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WHITEBULL_DIR="${WHITEBULL_DIR:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

MB_SEARCH="$WHITEBULL_DIR/absolutely/musicbrainz_release_search.sh"
MB_FETCH_PY="$WHITEBULL_DIR/absolutely/mb_wgetRelease.py"
DETECT_CATNO_PY="$SCRIPT_DIR/detect_catalog_number.py"
DISCOGS_SEARCH_PY="$SCRIPT_DIR/discogs_release_search.py"
MB_HANDLER="$WHITEBULL_DIR/absolutely/handel_composerFromMusicbrainz.sh"
DG_HANDLER="$WHITEBULL_DIR/absolutely/handel_composerFromDiscogs.sh"
WORK_SPLIT_SH="$WHITEBULL_DIR/absolutely/liszt_digWorksNum.sh"
DISPATCH_SH="$WHITEBULL_DIR/absolutely/jcbach_dispatchCoverJson.sh"
SCRATCH_BASE="${ALBUM_SCRATCH_DIR:-$WHITEBULL_DIR/_tmp}"

for f in "$MB_SEARCH" "$MB_FETCH_PY" "$DETECT_CATNO_PY" "$DISCOGS_SEARCH_PY" "$MB_HANDLER" "$DG_HANDLER" "$WORK_SPLIT_SH" "$DISPATCH_SH"; do
  [[ -f "$f" ]] || { echo "ERROR: missing tool: $f" >&2; exit 3; }
done

command -v python3 >/dev/null 2>&1 || { echo "ERROR: missing command: python3" >&2; exit 3; }
command -v jq >/dev/null 2>&1 || { echo "ERROR: missing command: jq" >&2; exit 3; }

mkdir -p "$SCRATCH_BASE"

log_debug() {
  if [[ "$DEBUG" -eq 1 ]]; then
    echo "[album-skill][debug] $*" >&2
  fi
}

norm_catno_shell() {
  local raw="$1"
  printf '%s' "$raw" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//; s/[[:space:]]+/ /g'
}

catno_variants() {
  local c="$1"
  c="$(norm_catno_shell "$c")"
  [[ -n "$c" ]] || return 0

  printf '%s\n' "$c"

  local compact
  compact="$(printf '%s' "$c" | tr -d ' ')"
  if [[ -n "$compact" && "$compact" != "$c" ]]; then
    printf '%s\n' "$compact"
  fi

  if [[ "$compact" =~ ^([0-9]{6}-[0-9A-Za-z])$ ]]; then
    printf '%s %s\n' "${compact:0:3}" "${compact:3}"
  fi

  if [[ "$c" =~ ^CD[[:space:]]*([0-9]{2,4})$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  elif [[ "$c" =~ ^([0-9]{2,4})$ ]]; then
    printf '%s\n' "CD ${BASH_REMATCH[1]}"
  fi
}

extract_tokens() {
  awk '
    BEGIN{
      split("album complete including disc discs track tracks audio and with from the this that op opus no nos vol volume for in on at by various music classical recordings orchestra artists artist", sw, " ");
      for(i in sw) stop[sw[i]]=1
    }
    {
      line=tolower($0)
      gsub(/[^a-z0-9]+/, " ", line)
      n=split(line, a, / +/)
      for(i=1; i<=n; i++){
        w=a[i]
        if(length(w) < 4) continue
        if(w ~ /^[0-9]+$/) continue
        if(stop[w]) continue
        print w
      }
    }'
}

album_title_from_dir() {
  local name
  name="$(basename "$ALBUM_DIR")"
  name="$(printf '%s' "$name" | sed -E 's/^\[[^]]+\][[:space:]]*//')"
  name="$(printf '%s' "$name" | sed -E 's/^CD[[:space:]]*[-:]?[[:space:]]*[0-9A-Za-z]+([[:space:]-]+[0-9A-Za-z]+){0,3}[[:space:]]+//I')"
  name="$(printf '%s' "$name" | sed -E 's/[[:space:]_]+/ /g; s/^ +//; s/ +$//')"
  printf '%s\n' "$name"
}

append_release_ids_by_query() {
  local field="$1"
  local value="$2"
  local primary rid

  [[ -n "$value" ]] || return 0
  rm -f "$SEARCH_TMP/_release_id.lst"

  log_debug "search: field=$field value=$value"
  primary="$(cd "$SEARCH_TMP" && "$MB_SEARCH" "$field" "$value" "$LIMIT" 2>/dev/null || true)"
  if [[ -n "$primary" ]]; then
    printf '%s\t%s\t%s\n' "$primary" "$field" "$value" >> "$RELEASE_RAW"
  fi

  if [[ -f "$SEARCH_TMP/_release_id.lst" ]]; then
    while IFS= read -r rid; do
      [[ -n "$rid" ]] || continue
      printf '%s\t%s\t%s\n' "$rid" "$field" "$value" >> "$RELEASE_RAW"
    done < "$SEARCH_TMP/_release_id.lst"
  fi
}

append_discogs_ids() {
  local -a cmd=("$DISCOGS_SEARCH_PY" "--limit" "$LIMIT")
  local catno_item variant hint

  if [[ -s "$CATNO_CANDS" ]]; then
    while IFS= read -r catno_item; do
      [[ -n "$catno_item" ]] || continue
      while IFS= read -r variant; do
        [[ -n "$variant" ]] || continue
        cmd+=("--catno" "$variant")
      done < <(catno_variants "$catno_item" | awk 'NF' | awk '!seen[$0]++')
    done < "$CATNO_CANDS"
  fi

  if [[ -n "$TITLE_HINT" ]]; then
    cmd+=("--title-hint" "$TITLE_HINT")
  fi
  cmd+=("--title-hint" "$(album_title_from_dir)")
  if [[ -f "$DETECT_JSON" ]]; then
    while IFS= read -r hint; do
      [[ -n "$hint" ]] || continue
      cmd+=("--title-hint" "$hint")
    done < <(jq -r '.title_hints[]? // empty' "$DETECT_JSON")
  fi

  if [[ "${#cmd[@]}" -le 3 ]]; then
    return 1
  fi

  log_debug "discogs search: catno/title fallback"
  if python3 "${cmd[@]}" > "$DISC_RAW" 2>/dev/null; then
    awk -F'\t' 'NF>=1 && !seen[$1]++ {print $0}' "$DISC_RAW" > "$DISC_LIST"
    return 0
  fi
  return 1
}

trim_works_spec() {
  local spec="$1"
  printf '%s' "$spec" | tr -d '\r' | sed -E 's/[[:space:]]+//g; s/;+/;/g; s/^;//; s/;$//'
}

normalize_manual_works_spec() {
  local spec="$1"
  # Keep leading empty groups so manual spec can preserve absolute work index
  # (e.g. ";;2-1,2-2;2-3,2-4" -> groups 2/3).
  printf '%s' "$spec" | tr -d '\r' | sed -E 's/[[:space:]]+//g; s/;+$//'
}

first_track_token_from_spec() {
  local spec="$1"
  local group item
  local -a groups items
  IFS=';' read -r -a groups <<<"$spec"
  for group in "${groups[@]}"; do
    IFS=',' read -r -a items <<<"$group"
    for item in "${items[@]}"; do
      item="${item//[[:space:]]/}"
      [[ -n "$item" ]] || continue
      printf '%s\n' "$item"
      return 0
    done
  done
  return 1
}

group_index_of_token() {
  local spec="$1"
  local token="$2"
  local i group item
  local -a groups items
  IFS=';' read -r -a groups <<<"$spec"
  for i in "${!groups[@]}"; do
    group="${groups[$i]}"
    IFS=',' read -r -a items <<<"$group"
    for item in "${items[@]}"; do
      item="${item//[[:space:]]/}"
      [[ -n "$item" ]] || continue
      if [[ "$item" == "$token" ]]; then
        printf '%s\n' "$i"
        return 0
      fi
    done
  done
  return 1
}

prepend_empty_groups() {
  local spec="$1"
  local count="$2"
  local out="$spec"
  while [[ "$count" -gt 0 ]]; do
    out=";$out"
    count=$((count - 1))
  done
  printf '%s\n' "$out"
}

count_works_groups() {
  local spec="$1"
  if [[ -z "$spec" ]]; then
    echo 0
    return
  fi
  awk -F';' '{
    c=0
    for(i=1;i<=NF;i++) if(length($i)>0) c++
    print c+0
  }' <<<"$spec"
}

count_top_split_like_tracks() {
  find "$ALBUM_DIR" -maxdepth 1 -type f -iname '*.flac' ! -name '._*' -exec basename {} \; 2>/dev/null \
    | awk '
      /^[0-9]{2}[[:space:]]*-/ {c++; next}
      /^[0-9]+-[0-9]{2}[[:space:]]*-/ {c++; next}
      END {print c+0}
    '
}

count_split_tracks_in_number_dirs() {
  find "$ALBUM_DIR" -maxdepth 2 -type f -iname '*.flac' ! -name '._*' 2>/dev/null \
    | awk -F'/' '
      {
        n=split($0, p, "/")
        if(n>=2 && p[n-1] ~ /^[0-9]+$/) c++
      }
      END {print c+0}
    '
}

derive_works_spec_auto() {
  local handler spec
  if [[ -f "$ALBUM_DIR/discogs_0.json" ]]; then
    handler="$DG_HANDLER"
  elif [[ -f "$ALBUM_DIR/musicbrainz_0.json" ]]; then
    handler="$MB_HANDLER"
  else
    return 1
  fi

  spec="$(
    cd "$ALBUM_DIR" && \
    WHITEBULL_DIR="$WHITEBULL_DIR" PATH="$WHITEBULL_DIR/absolutely:$WHITEBULL_DIR/composer:$PATH" \
      "$handler" works redo 2>/dev/null || true
  )"
  spec="$(trim_works_spec "$spec")"
  [[ -n "$spec" ]] || return 1
  printf '%s\n' "$spec"
}

WORK_SPLIT_ENABLED="$SPLIT_WORKS"
WORK_SPLIT_APPLIED=0
WORK_SPLIT_MODE="off"
WORK_SPLIT_GROUPS=0
WORK_SPLIT_SPEC=""
WORK_SPLIT_REASON=""
WORK_SPLIT_TARGET=""
WORK_DISPATCH_APPLIED=0
WORK_DISPATCH_REASON=""

maybe_split_works() {
  local spec split_arg top_tracks
  local first_token auto_spec anchor_idx
  WORK_SPLIT_APPLIED=0
  WORK_SPLIT_MODE="off"
  WORK_SPLIT_GROUPS=0
  WORK_SPLIT_SPEC=""
  WORK_SPLIT_REASON=""
  WORK_SPLIT_TARGET=""

  if [[ "$SPLIT_WORKS" -ne 1 ]]; then
    WORK_SPLIT_REASON="disabled"
    return 0
  fi

  WORK_SPLIT_MODE="auto"
  if [[ -n "$WORKS_SPEC" ]]; then
    WORK_SPLIT_MODE="manual"
    spec="$(normalize_manual_works_spec "$WORKS_SPEC")"
    if [[ -z "$spec" ]]; then
      WORK_SPLIT_REASON="empty_manual_spec"
      return 0
    fi

    # Keep liszt absolute work-index semantics:
    # if manual spec starts from a later work (e.g. only CD2 "2-1,..."),
    # prefix empty groups so target dirs stay 2/3/... instead of 0/1/...
    if [[ "$spec" == *-* ]]; then
      first_token="$(first_track_token_from_spec "$spec" || true)"
      if [[ -n "$first_token" && "$first_token" == *-* ]]; then
        auto_spec="$(derive_works_spec_auto || true)"
        if [[ -n "$auto_spec" ]]; then
          anchor_idx="$(group_index_of_token "$auto_spec" "$first_token" || true)"
          if [[ "$anchor_idx" =~ ^[0-9]+$ ]] && [[ "$anchor_idx" -gt 0 ]]; then
            spec="$(prepend_empty_groups "$spec" "$anchor_idx")"
          fi
        fi
      fi
    fi
    split_arg="$spec"
  else
    spec="$(derive_works_spec_auto || true)"
    if [[ -z "$spec" ]]; then
      WORK_SPLIT_REASON="no_auto_spec"
      return 0
    fi
    split_arg="auto"
  fi

  WORK_SPLIT_SPEC="$spec"
  WORK_SPLIT_GROUPS="$(count_works_groups "$spec")"
  if ! [[ "$WORK_SPLIT_GROUPS" =~ ^[0-9]+$ ]]; then
    WORK_SPLIT_GROUPS=0
  fi

  top_tracks="$(count_top_split_like_tracks)"
  if ! [[ "$top_tracks" =~ ^[0-9]+$ ]]; then
    top_tracks=0
  fi
  if [[ "$top_tracks" -eq 0 ]]; then
    WORK_SPLIT_REASON="no_split_tracks_in_album_root"
    return 0
  fi

  if [[ "$WORK_SPLIT_MODE" == "auto" ]] && [[ "$WORK_SPLIT_GROUPS" -lt 2 ]]; then
    WORK_SPLIT_REASON="group_count_lt_2"
    return 0
  fi

  WORK_SPLIT_TARGET="$split_arg"
  if [[ "$DEBUG" -eq 1 ]]; then
    (
      cd "$ALBUM_DIR"
      WHITEBULL_DIR="$WHITEBULL_DIR" PATH="$WHITEBULL_DIR/absolutely:$WHITEBULL_DIR/composer:$PATH" \
        "$WORK_SPLIT_SH" "$split_arg"
    )
  else
    (
      cd "$ALBUM_DIR"
      WHITEBULL_DIR="$WHITEBULL_DIR" PATH="$WHITEBULL_DIR/absolutely:$WHITEBULL_DIR/composer:$PATH" \
        "$WORK_SPLIT_SH" "$split_arg" >/dev/null 2>&1
    )
  fi

  local moved_tracks
  moved_tracks="$(count_split_tracks_in_number_dirs)"
  if ! [[ "$moved_tracks" =~ ^[0-9]+$ ]]; then
    moved_tracks=0
  fi
  if [[ "$moved_tracks" -le 0 ]]; then
    WORK_SPLIT_REASON="applied_but_no_tracks_moved"
    return 1
  fi

  WORK_SPLIT_APPLIED=1
  WORK_SPLIT_REASON="applied"
  return 0
}

has_numeric_work_dirs() {
  find "$ALBUM_DIR" -mindepth 1 -maxdepth 1 -type d -name '[0-9]*' -print -quit 2>/dev/null | grep -q .
}

maybe_dispatch_work_assets() {
  WORK_DISPATCH_APPLIED=0
  WORK_DISPATCH_REASON=""

  if [[ "$WORK_SPLIT_APPLIED" -ne 1 ]]; then
    WORK_DISPATCH_REASON="work_split_not_applied"
    return 0
  fi

  if ! has_numeric_work_dirs; then
    WORK_DISPATCH_REASON="no_numeric_work_dirs"
    return 0
  fi

  if [[ ! -f "$ALBUM_DIR/cover.jpg" ]]; then
    WORK_DISPATCH_REASON="cover_missing"
    return 0
  fi

  if [[ "$DEBUG" -eq 1 ]]; then
    (
      cd "$ALBUM_DIR"
      WHITEBULL_DIR="$WHITEBULL_DIR" PATH="$WHITEBULL_DIR/absolutely:$WHITEBULL_DIR/composer:$PATH" \
        "$DISPATCH_SH" --skip-resize --skip-runme
    )
  else
    (
      cd "$ALBUM_DIR"
      WHITEBULL_DIR="$WHITEBULL_DIR" PATH="$WHITEBULL_DIR/absolutely:$WHITEBULL_DIR/composer:$PATH" \
        "$DISPATCH_SH" --skip-resize --skip-runme >/dev/null 2>&1
    )
  fi

  WORK_DISPATCH_APPLIED=1
  WORK_DISPATCH_REASON="applied"
  return 0
}

SEARCH_TMP="$(mktemp -d "$SCRATCH_BASE/album_skill_search.XXXXXX")"
FETCH_TMP="$(mktemp -d "$SCRATCH_BASE/album_skill_fetch.XXXXXX")"

DETECT_JSON="$SEARCH_TMP/catno_detect.json"
CATNO_CANDS_RAW="$SEARCH_TMP/catno_candidates_raw.lst"
CATNO_CANDS="$SEARCH_TMP/catno_candidates.lst"
RELEASE_RAW="$SEARCH_TMP/release_candidates_raw.tsv"
RELEASE_LIST="$SEARCH_TMP/release_candidates.tsv"
DISC_RAW="$SEARCH_TMP/discogs_candidates_raw.tsv"
DISC_LIST="$SEARCH_TMP/discogs_candidates.tsv"

: > "$CATNO_CANDS_RAW"
: > "$RELEASE_RAW"
: > "$DISC_RAW"
: > "$DISC_LIST"

SELECTED_ID=""
SELECTED_FIELD=""
SELECTED_QUERY=""
SELECTED_CATNO=""
SELECTED_PROVIDER=""
FETCH_OK=0
FETCH_TRACKS=0
SEARCH_USED=0
MB_CANDIDATE_COUNT=0
DISC_CANDIDATE_COUNT=0
DISCOGS_PRIMARY_MIN=600

DETECTED_CATNO=""
DETECTED_SOURCE=""
TITLE_HINT=""
LOCAL_TOKEN_COUNT=0
MIN_TOKEN_MATCH=1
WRITTEN_A=""
WRITTEN_B=""

LOCAL_TRACKS="$(find "$ALBUM_DIR" -type f -iname '*.flac' ! -name '._*' | wc -l | tr -d '[:space:]')"
if ! [[ "$LOCAL_TRACKS" =~ ^[0-9]+$ ]]; then
  LOCAL_TRACKS=0
fi

# Prefer cue-defined track count when album still has single unsplit image FLAC.
LOCAL_CUE_TRACKS=0
while IFS= read -r -d '' cue_file; do
  cue_tracks="$(
    awk 'BEGIN{c=0} /^[[:space:]]*TRACK[[:space:]]+[0-9]{2}[[:space:]]+AUDIO[[:space:]]*$/ {c++} END{print c+0}' "$cue_file" 2>/dev/null
  )"
  if [[ "$cue_tracks" =~ ^[0-9]+$ ]] && [[ "$cue_tracks" -gt "$LOCAL_CUE_TRACKS" ]]; then
    LOCAL_CUE_TRACKS="$cue_tracks"
  fi
done < <(find "$ALBUM_DIR" -maxdepth 3 -type f -iname '*.cue' ! -name '._*' -print0 2>/dev/null)

EXPECTED_TRACKS="$LOCAL_TRACKS"
if [[ "$EXPECTED_TRACKS" -le 1 && "$LOCAL_CUE_TRACKS" -gt 0 ]]; then
  EXPECTED_TRACKS="$LOCAL_CUE_TRACKS"
fi

if [[ "$FORCE" -ne 1 && ( -s "$ALBUM_DIR/musicbrainz_0.db" || -s "$ALBUM_DIR/discogs_0.db" ) ]]; then
  if [[ -s "$ALBUM_DIR/musicbrainz_0.db" ]]; then
    SELECTED_PROVIDER="musicbrainz"
    WRITTEN_A="musicbrainz_0.db"
    WRITTEN_B="musicbrainz_0.json"
  else
    SELECTED_PROVIDER="discogs"
    WRITTEN_A="discogs_0.db"
    WRITTEN_B="discogs_0.json"
  fi
  if ! maybe_split_works; then
    echo "ERROR: work split stage failed via liszt_digWorksNum.sh" >&2
    exit 7
  fi
  if ! maybe_dispatch_work_assets; then
    echo "ERROR: post-split dispatch stage failed via jcbach_dispatchCoverJson.sh" >&2
    exit 8
  fi
  if [[ "$OUTPUT_JSON" -eq 1 ]]; then
    python3 - "$ALBUM_DIR" "$LOCAL_TRACKS" "$LOCAL_CUE_TRACKS" "$EXPECTED_TRACKS" "$SELECTED_PROVIDER" "$WRITTEN_A" "$WRITTEN_B" "$WORK_SPLIT_ENABLED" "$WORK_SPLIT_APPLIED" "$WORK_SPLIT_MODE" "$WORK_SPLIT_GROUPS" "$WORK_SPLIT_REASON" "$WORK_SPLIT_TARGET" "$WORK_SPLIT_SPEC" "$WORK_DISPATCH_APPLIED" "$WORK_DISPATCH_REASON" <<'PY'
import json, sys
print(json.dumps({
  "ok": True,
  "album_dir": sys.argv[1],
  "skipped_existing": True,
  "provider": sys.argv[5],
  "catalog_no": None,
  "detected_catalog_no": None,
  "catalog_source": None,
  "release_id": None,
  "search_used": False,
  "search_strategy": None,
  "query": None,
  "candidate_count": 0,
  "mb_candidate_count": 0,
  "discogs_candidate_count": 0,
  "local_tracks": int(sys.argv[2]),
  "cue_tracks": int(sys.argv[3]),
  "expected_tracks": int(sys.argv[4]),
  "tracks": None,
  "written": [x for x in (sys.argv[6], sys.argv[7]) if x],
  "work_split_enabled": sys.argv[8] == "1",
  "work_split_applied": sys.argv[9] == "1",
  "work_split_mode": sys.argv[10] or None,
  "work_split_groups": int(sys.argv[11]),
  "work_split_reason": sys.argv[12] or None,
  "work_split_target": sys.argv[13] or None,
  "work_split_spec": sys.argv[14] or None,
  "dispatch_assets_applied": sys.argv[15] == "1",
  "dispatch_assets_reason": sys.argv[16] or None
}, ensure_ascii=False))
PY
  else
    echo "[album-skill] reuse existing provider=$SELECTED_PROVIDER: $ALBUM_DIR/$WRITTEN_A"
    echo "[album-skill] work_split enabled=$WORK_SPLIT_ENABLED applied=$WORK_SPLIT_APPLIED mode=$WORK_SPLIT_MODE groups=$WORK_SPLIT_GROUPS reason=$WORK_SPLIT_REASON target=$WORK_SPLIT_TARGET"
    echo "[album-skill] dispatch_assets applied=$WORK_DISPATCH_APPLIED reason=$WORK_DISPATCH_REASON"
  fi
  exit 0
fi

if [[ -z "$RELEASE_ID" ]]; then
  if [[ -n "$CATNO" ]]; then
    printf '%s\n' "$(norm_catno_shell "$CATNO")" >> "$CATNO_CANDS_RAW"
  else
    if python3 "$DETECT_CATNO_PY" --album-dir "$ALBUM_DIR" --json > "$DETECT_JSON" 2>/dev/null; then
      DETECTED_CATNO="$(jq -r '.catno // empty' "$DETECT_JSON")"
      DETECTED_SOURCE="$(jq -r '.source // empty' "$DETECT_JSON")"
      TITLE_HINT="$(jq -r '.title_hints[0] // empty' "$DETECT_JSON")"
      jq -r '.candidates[]?.value // empty' "$DETECT_JSON" >> "$CATNO_CANDS_RAW" || true
      if [[ -n "$DETECTED_CATNO" ]]; then
        printf '%s\n' "$DETECTED_CATNO" >> "$CATNO_CANDS_RAW"
      fi
    fi
  fi

  awk 'NF' "$CATNO_CANDS_RAW" | awk '!seen[$0]++' > "$CATNO_CANDS" || true

  if [[ -s "$CATNO_CANDS" ]]; then
    SEARCH_USED=1
    while IFS= read -r catno_item; do
      [[ -n "$catno_item" ]] || continue
      while IFS= read -r variant; do
        [[ -n "$variant" ]] || continue
        append_release_ids_by_query "catno" "$variant"
      done < <(catno_variants "$catno_item" | awk 'NF' | awk '!seen[$0]++')
    done < "$CATNO_CANDS"
  fi

  if [[ ! -s "$RELEASE_RAW" ]]; then
    if [[ -z "$TITLE_HINT" ]]; then
      TITLE_HINT="$(album_title_from_dir)"
    fi
    if [[ -n "$TITLE_HINT" ]]; then
      SEARCH_USED=1
      append_release_ids_by_query "release" "$TITLE_HINT"
      if [[ -f "$DETECT_JSON" ]]; then
        while IFS= read -r hint; do
          [[ -n "$hint" ]] || continue
          [[ "$hint" == "$TITLE_HINT" ]] && continue
          append_release_ids_by_query "release" "$hint"
        done < <(jq -r '.title_hints[]? // empty' "$DETECT_JSON")
      fi
    fi
  fi

  if [[ -s "$RELEASE_RAW" ]]; then
    awk -F'\t' 'NF>=1 && !seen[$1]++ {print $0}' "$RELEASE_RAW" > "$RELEASE_LIST"
  else
    : > "$RELEASE_LIST"
  fi
else
  printf '%s\trelease_id\texplicit\n' "$RELEASE_ID" > "$RELEASE_LIST"
fi

LOCAL_HINTS_RAW="$SEARCH_TMP/local_hints_raw.txt"
LOCAL_TOKENS="$SEARCH_TMP/local_tokens.lst"
: > "$LOCAL_HINTS_RAW"

printf '%s\n' "$(album_title_from_dir)" >> "$LOCAL_HINTS_RAW"
if [[ -n "$TITLE_HINT" ]]; then
  printf '%s\n' "$TITLE_HINT" >> "$LOCAL_HINTS_RAW"
fi
if [[ -f "$DETECT_JSON" ]]; then
  jq -r '.title_hints[]? // empty' "$DETECT_JSON" >> "$LOCAL_HINTS_RAW" || true
fi

while IFS= read -r -d '' cue_file; do
  awk '
    BEGIN{c=0}
    /^[[:space:]]*(PERFORMER|TITLE)[[:space:]]+"/{
      line=$0
      sub(/^[[:space:]]*(PERFORMER|TITLE)[[:space:]]+"/, "", line)
      sub(/"[[:space:]]*$/, "", line)
      print line
      c++
      if(c>=8) exit
    }' "$cue_file" >> "$LOCAL_HINTS_RAW" 2>/dev/null || true
  break
done < <(find "$ALBUM_DIR" -maxdepth 3 -type f -iname '*.cue' ! -name '._*' -print0 2>/dev/null)

extract_tokens < "$LOCAL_HINTS_RAW" | awk 'NF' | sort -u > "$LOCAL_TOKENS" || true
LOCAL_TOKEN_COUNT="$(wc -l < "$LOCAL_TOKENS" | tr -d '[:space:]')"
if ! [[ "$LOCAL_TOKEN_COUNT" =~ ^[0-9]+$ ]]; then
  LOCAL_TOKEN_COUNT=0
fi
if [[ "$LOCAL_TOKEN_COUNT" -ge 4 ]]; then
  MIN_TOKEN_MATCH=2
fi

MB_CANDIDATE_COUNT="$(wc -l < "$RELEASE_LIST" | tr -d '[:space:]')"
if ! [[ "$MB_CANDIDATE_COUNT" =~ ^[0-9]+$ ]]; then
  MB_CANDIDATE_COUNT=0
fi

while IFS=$'\t' read -r rid field query; do
  [[ -n "$rid" ]] || continue
  log_debug "try release id: $rid (field=$field query=$query)"

  rm -f "$FETCH_TMP/musicbrainz_0.db" "$FETCH_TMP/musicbrainz_0.json"
  if [[ "$FORCE" -eq 1 ]]; then
    (
      cd "$FETCH_TMP"
      WHITEBULL_DIR="$WHITEBULL_DIR" PATH="$WHITEBULL_DIR/absolutely:$PATH" python3 "$MB_FETCH_PY" -f "$rid"
    ) >/dev/null 2>&1 || true
  else
    (
      cd "$FETCH_TMP"
      WHITEBULL_DIR="$WHITEBULL_DIR" PATH="$WHITEBULL_DIR/absolutely:$PATH" python3 "$MB_FETCH_PY" "$rid"
    ) >/dev/null 2>&1 || true
  fi

  if [[ ! -s "$FETCH_TMP/musicbrainz_0.db" ]]; then
    continue
  fi

  if ! jq -e '.id and (.media|type=="array")' "$FETCH_TMP/musicbrainz_0.db" >/dev/null 2>&1; then
    continue
  fi

  FETCH_TRACKS="$(jq -r '.media|map(.tracks|length)|add' "$FETCH_TMP/musicbrainz_0.db" 2>/dev/null || echo 0)"
  if ! [[ "$FETCH_TRACKS" =~ ^[0-9]+$ ]]; then
    FETCH_TRACKS=0
  fi

  if [[ "$SKIP_TRACK_CHECK" -ne 1 && "$EXPECTED_TRACKS" -gt 0 && "$FETCH_TRACKS" -gt 0 && "$EXPECTED_TRACKS" -ne "$FETCH_TRACKS" ]]; then
    log_debug "reject by track-count mismatch: expected=$EXPECTED_TRACKS (flac=$LOCAL_TRACKS cue=$LOCAL_CUE_TRACKS) fetched=$FETCH_TRACKS"
    continue
  fi

  if [[ "$LOCAL_TOKEN_COUNT" -gt 0 ]]; then
    FETCH_HINTS="$FETCH_TMP/fetch_hints.txt"
    FETCH_TOKENS="$FETCH_TMP/fetch_tokens.lst"
    jq -r '[.title, (."artist-credit"[]? | if type=="object" then .name else empty end)] | .[]? // empty' "$FETCH_TMP/musicbrainz_0.db" > "$FETCH_HINTS" 2>/dev/null || true
    extract_tokens < "$FETCH_HINTS" | awk 'NF' | sort -u > "$FETCH_TOKENS" || true
    MATCH_COUNT="$(comm -12 "$LOCAL_TOKENS" "$FETCH_TOKENS" | wc -l | tr -d '[:space:]')"
    if ! [[ "$MATCH_COUNT" =~ ^[0-9]+$ ]]; then
      MATCH_COUNT=0
    fi
    if [[ "$MATCH_COUNT" -lt "$MIN_TOKEN_MATCH" ]]; then
      FETCH_LABEL="$(jq -r '.title // empty' "$FETCH_TMP/musicbrainz_0.db" 2>/dev/null || echo "")"
      log_debug "reject by token mismatch: need>=$MIN_TOKEN_MATCH got=$MATCH_COUNT fetched_title=$FETCH_LABEL"
      continue
    fi
  fi

  cp -f "$FETCH_TMP/musicbrainz_0.db" "$ALBUM_DIR/musicbrainz_0.db"
  cp -f "$FETCH_TMP/musicbrainz_0.json" "$ALBUM_DIR/musicbrainz_0.json"

  SELECTED_ID="$rid"
  SELECTED_FIELD="$field"
  SELECTED_QUERY="$query"
  SELECTED_PROVIDER="musicbrainz"
  WRITTEN_A="musicbrainz_0.db"
  WRITTEN_B="musicbrainz_0.json"
  if [[ "$field" == "catno" ]]; then
    SELECTED_CATNO="$query"
  fi
  FETCH_OK=1
  break
done < "$RELEASE_LIST"

# Discogs fallback when MusicBrainz has no hit or all MB hits fail validation.
if [[ "$FETCH_OK" -ne 1 && -z "$RELEASE_ID" ]]; then
  append_discogs_ids || true
  DISC_CANDIDATE_COUNT="$(wc -l < "$DISC_LIST" | tr -d '[:space:]')"
  if ! [[ "$DISC_CANDIDATE_COUNT" =~ ^[0-9]+$ ]]; then
    DISC_CANDIDATE_COUNT=0
  fi

  if [[ "$DISC_CANDIDATE_COUNT" -gt 0 ]]; then
    DISC_FALLBACK_FOUND=0
    DISC_FALLBACK_ID=""
    DISC_FALLBACK_FIELD=""
    DISC_FALLBACK_QUERY=""
    DISC_FALLBACK_CATNO=""
    DISC_FALLBACK_DB="$FETCH_TMP/discogs_fallback_0.db"
    DISC_FALLBACK_JSON="$FETCH_TMP/discogs_fallback_0.json"
    rm -f "$DISC_FALLBACK_DB" "$DISC_FALLBACK_JSON"

    SEARCH_USED=1
    while IFS=$'\t' read -r did dfield dquery _dscore _dtitle; do
      [[ -n "$did" ]] || continue
      log_debug "try discogs id: $did (field=$dfield query=$dquery)"

      rm -f "$FETCH_TMP/discogs_0.db" "$FETCH_TMP/discogs_0.json"
      if [[ "$FORCE" -eq 1 ]]; then
        (
          cd "$FETCH_TMP"
          WHITEBULL_DIR="$WHITEBULL_DIR" PATH="$WHITEBULL_DIR/absolutely:$PATH" python3 "$MB_FETCH_PY" -f "$did"
        ) >/dev/null 2>&1 || true
      else
        (
          cd "$FETCH_TMP"
          WHITEBULL_DIR="$WHITEBULL_DIR" PATH="$WHITEBULL_DIR/absolutely:$PATH" python3 "$MB_FETCH_PY" "$did"
        ) >/dev/null 2>&1 || true
      fi

      if [[ ! -s "$FETCH_TMP/discogs_0.db" ]]; then
        continue
      fi

      if ! jq -e '.id and .title' "$FETCH_TMP/discogs_0.db" >/dev/null 2>&1; then
        continue
      fi

      FETCH_TRACKS="$(jq -r '
def cnt(items):
  if (items|type)!="array" then 0
  else
    ([items[]? |
      (if (.type_ // "") == "track" then 1 else 0 end) +
      (if (.sub_tracks|type)=="array" then ([.sub_tracks[]? | if ((.type_ // "") == "track") then 1 else 0 end] | add // 0) else 0 end)
    ] | add // 0)
  end;
cnt(.tracklist)
' "$FETCH_TMP/discogs_0.db" 2>/dev/null || echo 0)"
      if ! [[ "$FETCH_TRACKS" =~ ^[0-9]+$ ]]; then
        FETCH_TRACKS=0
      fi

      if [[ "$SKIP_TRACK_CHECK" -ne 1 && "$EXPECTED_TRACKS" -gt 0 && "$FETCH_TRACKS" -gt 0 && "$EXPECTED_TRACKS" -ne "$FETCH_TRACKS" ]]; then
        log_debug "reject discogs by track-count mismatch: expected=$EXPECTED_TRACKS (flac=$LOCAL_TRACKS cue=$LOCAL_CUE_TRACKS) fetched=$FETCH_TRACKS"
        continue
      fi

      if [[ "$LOCAL_TOKEN_COUNT" -gt 0 ]]; then
        FETCH_HINTS="$FETCH_TMP/fetch_hints.txt"
        FETCH_TOKENS="$FETCH_TMP/fetch_tokens.lst"
        jq -r '[.title, (.artists[]?.name), (.tracklist[]?.title), (.tracklist[]?.sub_tracks[]?.title)] | .[]? // empty' "$FETCH_TMP/discogs_0.db" > "$FETCH_HINTS" 2>/dev/null || true
        extract_tokens < "$FETCH_HINTS" | awk 'NF' | sort -u > "$FETCH_TOKENS" || true
        MATCH_COUNT="$(comm -12 "$LOCAL_TOKENS" "$FETCH_TOKENS" | wc -l | tr -d '[:space:]')"
        if ! [[ "$MATCH_COUNT" =~ ^[0-9]+$ ]]; then
          MATCH_COUNT=0
        fi
        if [[ "$MATCH_COUNT" -lt "$MIN_TOKEN_MATCH" ]]; then
          FETCH_LABEL="$(jq -r '.title // empty' "$FETCH_TMP/discogs_0.db" 2>/dev/null || echo "")"
          log_debug "reject discogs by token mismatch: need>=$MIN_TOKEN_MATCH got=$MATCH_COUNT fetched_title=$FETCH_LABEL"
          continue
        fi
      fi

      DISC_PRIMARY_W="$(jq -r '
((.images // [])
 | map(select((.type // "") == "primary"))
 | .[0].width) // 0
' "$FETCH_TMP/discogs_0.db" 2>/dev/null || echo 0)"
      DISC_PRIMARY_H="$(jq -r '
((.images // [])
 | map(select((.type // "") == "primary"))
 | .[0].height) // 0
' "$FETCH_TMP/discogs_0.db" 2>/dev/null || echo 0)"
      if ! [[ "$DISC_PRIMARY_W" =~ ^[0-9]+$ ]]; then
        DISC_PRIMARY_W=0
      fi
      if ! [[ "$DISC_PRIMARY_H" =~ ^[0-9]+$ ]]; then
        DISC_PRIMARY_H=0
      fi

      if [[ "$DISC_FALLBACK_FOUND" -ne 1 ]]; then
        cp -f "$FETCH_TMP/discogs_0.db" "$DISC_FALLBACK_DB"
        cp -f "$FETCH_TMP/discogs_0.json" "$DISC_FALLBACK_JSON"
        DISC_FALLBACK_ID="$did"
        DISC_FALLBACK_FIELD="$dfield"
        DISC_FALLBACK_QUERY="$dquery"
        if [[ "$dfield" == "discogs_catno" ]]; then
          DISC_FALLBACK_CATNO="$dquery"
        fi
        DISC_FALLBACK_FOUND=1
      fi

      if [[ "$DISC_PRIMARY_W" -lt "$DISCOGS_PRIMARY_MIN" || "$DISC_PRIMARY_H" -lt "$DISCOGS_PRIMARY_MIN" ]]; then
        log_debug "skip discogs candidate by primary cover size: id=$did primary=${DISC_PRIMARY_W}x${DISC_PRIMARY_H} need>=${DISCOGS_PRIMARY_MIN}x${DISCOGS_PRIMARY_MIN}"
        continue
      fi

      cp -f "$FETCH_TMP/discogs_0.db" "$ALBUM_DIR/discogs_0.db"
      cp -f "$FETCH_TMP/discogs_0.json" "$ALBUM_DIR/discogs_0.json"

      SELECTED_ID="$did"
      SELECTED_FIELD="$dfield"
      SELECTED_QUERY="$dquery"
      SELECTED_PROVIDER="discogs"
      WRITTEN_A="discogs_0.db"
      WRITTEN_B="discogs_0.json"
      if [[ "$dfield" == "discogs_catno" ]]; then
        SELECTED_CATNO="$dquery"
      fi
      FETCH_OK=1
      break
    done < "$DISC_LIST"

    if [[ "$FETCH_OK" -ne 1 && "$DISC_FALLBACK_FOUND" -eq 1 ]]; then
      cp -f "$DISC_FALLBACK_DB" "$ALBUM_DIR/discogs_0.db"
      cp -f "$DISC_FALLBACK_JSON" "$ALBUM_DIR/discogs_0.json"
      SELECTED_ID="$DISC_FALLBACK_ID"
      SELECTED_FIELD="$DISC_FALLBACK_FIELD"
      SELECTED_QUERY="$DISC_FALLBACK_QUERY"
      SELECTED_PROVIDER="discogs"
      WRITTEN_A="discogs_0.db"
      WRITTEN_B="discogs_0.json"
      if [[ -n "$DISC_FALLBACK_CATNO" ]]; then
        SELECTED_CATNO="$DISC_FALLBACK_CATNO"
      fi
      FETCH_OK=1
      log_debug "discogs fallback selected without cover-size pass: id=$SELECTED_ID"
    fi
  fi
fi

if [[ "$FETCH_OK" -ne 1 ]]; then
  if [[ "$MB_CANDIDATE_COUNT" -eq 0 && "$DISC_CANDIDATE_COUNT" -eq 0 ]]; then
    echo "ERROR: unable to resolve valid metadata candidates from MusicBrainz and Discogs" >&2
    exit 5
  fi
  echo "ERROR: failed to fetch valid metadata from all MusicBrainz/Discogs candidates" >&2
  exit 6
fi

if ! maybe_split_works; then
  echo "ERROR: work split stage failed via liszt_digWorksNum.sh" >&2
  exit 7
fi
if ! maybe_dispatch_work_assets; then
  echo "ERROR: post-split dispatch stage failed via jcbach_dispatchCoverJson.sh" >&2
  exit 8
fi

if [[ -z "$SELECTED_CATNO" ]]; then
  if [[ -n "$CATNO" ]]; then
    SELECTED_CATNO="$(norm_catno_shell "$CATNO")"
  elif [[ -n "$DETECTED_CATNO" ]]; then
    SELECTED_CATNO="$DETECTED_CATNO"
  fi
fi

if [[ "$OUTPUT_JSON" -eq 1 ]]; then
  if [[ "$SELECTED_PROVIDER" == "discogs" ]]; then
    CANDIDATE_COUNT="$DISC_CANDIDATE_COUNT"
  else
    CANDIDATE_COUNT="$MB_CANDIDATE_COUNT"
  fi
  python3 - "$ALBUM_DIR" "$SELECTED_PROVIDER" "$SELECTED_CATNO" "$DETECTED_CATNO" "$DETECTED_SOURCE" "$SELECTED_ID" "$SEARCH_USED" "$SELECTED_FIELD" "$SELECTED_QUERY" "$CANDIDATE_COUNT" "$MB_CANDIDATE_COUNT" "$DISC_CANDIDATE_COUNT" "$LOCAL_TRACKS" "$LOCAL_CUE_TRACKS" "$EXPECTED_TRACKS" "$FETCH_TRACKS" "$WRITTEN_A" "$WRITTEN_B" "$WORK_SPLIT_ENABLED" "$WORK_SPLIT_APPLIED" "$WORK_SPLIT_MODE" "$WORK_SPLIT_GROUPS" "$WORK_SPLIT_REASON" "$WORK_SPLIT_TARGET" "$WORK_SPLIT_SPEC" "$WORK_DISPATCH_APPLIED" "$WORK_DISPATCH_REASON" <<'PY'
import json
import sys

payload = {
  "ok": True,
  "album_dir": sys.argv[1],
  "provider": sys.argv[2],
  "skipped_existing": False,
  "catalog_no": sys.argv[3] or None,
  "detected_catalog_no": sys.argv[4] or None,
  "catalog_source": sys.argv[5] or None,
  "release_id": sys.argv[6],
  "search_used": sys.argv[7] == "1",
  "search_strategy": sys.argv[8] or None,
  "query": sys.argv[9] or None,
  "candidate_count": int(sys.argv[10]),
  "mb_candidate_count": int(sys.argv[11]),
  "discogs_candidate_count": int(sys.argv[12]),
  "local_tracks": int(sys.argv[13]),
  "cue_tracks": int(sys.argv[14]),
  "expected_tracks": int(sys.argv[15]),
  "tracks": int(sys.argv[16]),
  "written": [x for x in (sys.argv[17], sys.argv[18]) if x],
  "work_split_enabled": sys.argv[19] == "1",
  "work_split_applied": sys.argv[20] == "1",
  "work_split_mode": sys.argv[21] or None,
  "work_split_groups": int(sys.argv[22]),
  "work_split_reason": sys.argv[23] or None,
  "work_split_target": sys.argv[24] or None,
  "work_split_spec": sys.argv[25] or None,
  "dispatch_assets_applied": sys.argv[26] == "1",
  "dispatch_assets_reason": sys.argv[27] or None,
}
print(json.dumps(payload, ensure_ascii=False))
PY
else
  echo "[album-skill] ok provider=$SELECTED_PROVIDER: $ALBUM_DIR/$WRITTEN_A"
  echo "[album-skill] release_id=$SELECTED_ID strategy=$SELECTED_FIELD query=$SELECTED_QUERY mb_candidates=$MB_CANDIDATE_COUNT discogs_candidates=$DISC_CANDIDATE_COUNT"
  echo "[album-skill] catno=$SELECTED_CATNO local_tracks=$LOCAL_TRACKS cue_tracks=$LOCAL_CUE_TRACKS expected_tracks=$EXPECTED_TRACKS fetched_tracks=$FETCH_TRACKS"
  echo "[album-skill] work_split enabled=$WORK_SPLIT_ENABLED applied=$WORK_SPLIT_APPLIED mode=$WORK_SPLIT_MODE groups=$WORK_SPLIT_GROUPS reason=$WORK_SPLIT_REASON target=$WORK_SPLIT_TARGET"
  echo "[album-skill] dispatch_assets applied=$WORK_DISPATCH_APPLIED reason=$WORK_DISPATCH_REASON"
fi
