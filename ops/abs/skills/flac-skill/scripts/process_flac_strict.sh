#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  process_flac_strict.sh --source DIR [options]

Purpose:
  Convert/split/organize FLAC-related files in a deterministic flow.

Stages:
  0) Cleanup sidecar junk and normalize extensions
  1) Convert APE/WV -> FLAC (using absolutely/my_ape2flac.sh)
  2) Convert WAV -> FLAC
  3) Normalize CUE encoding to UTF-8 (using absolutely/my_iconv_cue.sh)
  3.1) Rewrite CUE FILE refs .ape/.wv/.wav -> .flac
  3.2) Reorganize multi-disc whole-track FLAC into subdirs 1/2/3...
  3.3) Preprocess matched CUE again before each FLAC split
  3.4) Verify source FLAC integrity; if damaged, skip split (no recovery)
  4) Split single-file FLAC by CUE (using absolutely/segovia_splitFlacWithCue.sh)
  5) Post-split placement
     - single-disc: move split FLAC tracks from disc subdir to album root
     - multi-disc: consolidate disc subdirs to album root with disc-prefix naming (using absolutely/berlioz_multiCDMove.sh)
  6) Normalize split-track filename prefixes (e.g. 1. -> 01 -)

Options:
  --source DIR                 Source directory (can be nested)
  --target-split-template STR  shnsplit template (default: "%n - %t")
  --remove-source-after-split  Remove source whole-track FLAC after split (default on)
  --keep-source-after-split    Keep source whole-track FLAC even if split is complete
  --remove-wav-source          Remove WAV files after successful conversion
  --keep-ape-source            Keep APE/WV source files after conversion
  --force-split                Split even when target dir already has enough FLAC tracks
  --skip-convert               Skip APE/WV/WAV conversion stage
  --skip-clean                 Skip cleanup/extension/cue-ref normalization stage
  --skip-split                 Skip CUE split stage
  --skip-consolidate           Skip post-split placement (keep split files in subdirs)
  --continue-on-error          Continue on per-file split failure (default)
  --stop-on-error              Stop immediately on split failure
  --json                       Print JSON summary
  --debug                      Enable shell trace
  -h, --help                   Show this help
EOF
}

SOURCE_DIR=""
SPLIT_TEMPLATE='%n - %t'
REMOVE_SOURCE_AFTER_SPLIT=1
REMOVE_WAV_SOURCE=0
KEEP_APE_SOURCE=0
FORCE_SPLIT=0
SKIP_CONVERT=0
SKIP_CLEAN=0
SKIP_SPLIT=0
SKIP_CONSOLIDATE=0
CONTINUE_ON_ERROR=1
OUTPUT_JSON=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)
      SOURCE_DIR="${2:-}"
      shift 2
      ;;
    --target-split-template)
      SPLIT_TEMPLATE="${2:-}"
      shift 2
      ;;
    --remove-source-after-split)
      REMOVE_SOURCE_AFTER_SPLIT=1
      shift
      ;;
    --keep-source-after-split)
      REMOVE_SOURCE_AFTER_SPLIT=0
      shift
      ;;
    --remove-wav-source)
      REMOVE_WAV_SOURCE=1
      shift
      ;;
    --keep-ape-source)
      KEEP_APE_SOURCE=1
      shift
      ;;
    --force-split)
      FORCE_SPLIT=1
      shift
      ;;
    --skip-convert)
      SKIP_CONVERT=1
      shift
      ;;
    --skip-clean)
      SKIP_CLEAN=1
      shift
      ;;
    --skip-split)
      SKIP_SPLIT=1
      shift
      ;;
    --skip-consolidate)
      SKIP_CONSOLIDATE=1
      shift
      ;;
    --continue-on-error)
      CONTINUE_ON_ERROR=1
      shift
      ;;
    --stop-on-error)
      CONTINUE_ON_ERROR=0
      shift
      ;;
    --json)
      OUTPUT_JSON=1
      shift
      ;;
    --debug)
      set -x
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

if [[ -z "$SOURCE_DIR" ]]; then
  echo "ERROR: --source is required" >&2
  exit 2
fi

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "ERROR: source directory not found: $SOURCE_DIR" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WHITEBULL_DIR="${WHITEBULL_DIR:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

APE2FLAC="$WHITEBULL_DIR/absolutely/my_ape2flac.sh"
WAV2FLAC="$WHITEBULL_DIR/absolutely/my-wav2flac.sh"
SPLIT_FLAC="$WHITEBULL_DIR/absolutely/segovia_splitFlacWithCue.sh"
ICONV_CUE="$WHITEBULL_DIR/absolutely/my_iconv_cue.sh"
MERGE_MULTI_CD="$WHITEBULL_DIR/absolutely/berlioz_multiCDMove.sh"

for f in "$APE2FLAC" "$WAV2FLAC" "$SPLIT_FLAC" "$ICONV_CUE" "$MERGE_MULTI_CD"; do
  [[ -f "$f" ]] || { echo "ERROR: missing tool: $f" >&2; exit 3; }
done
command -v flac >/dev/null 2>&1 || { echo "ERROR: missing command: flac" >&2; exit 3; }

# shellcheck disable=SC1090
source "$ICONV_CUE"

cleanup_sidecar_files() {
  local base="$1"
  CLEAN_REMOVED_FILES=0
  CLEAN_REMOVED_DIRS=0
  while IFS= read -r -d '' p; do
    rm -f "$p" || true
    CLEAN_REMOVED_FILES=$((CLEAN_REMOVED_FILES + 1))
  done < <(find "$base" -type f \( -name '.DS_Store' -o -name '._*' \) -print0)

  while IFS= read -r -d '' p; do
    rm -rf "$p" || true
    CLEAN_REMOVED_DIRS=$((CLEAN_REMOVED_DIRS + 1))
  done < <(find "$base" -type d -name '.AppleDouble' -print0)
}

normalize_extension_case() {
  local base="$1"
  local ext="$2"
  local changed=0
  while IFS= read -r -d '' f; do
    local dir bn stem out
    dir="$(dirname "$f")"
    bn="$(basename "$f")"
    stem="${bn%.*}"
    out="$dir/$stem.$ext"
    if [[ "$f" != "$out" ]]; then
      mv -n "$f" "$out" || true
      changed=$((changed + 1))
    fi
  done < <(find "$base" -type f -iname "*.${ext}" ! -name "._*" -print0)
  printf '%s\n' "$changed"
}

normalize_cue_file_refs_to_flac() {
  local base="$1"
  local updated=0
  while IFS= read -r -d '' cue; do
    if grep -Eiq '\.(ape|wv|wav)"' "$cue"; then
      perl -i -pe 's/\.(ape|wv|wav)"/.flac"/ig' "$cue"
      updated=$((updated + 1))
    fi
  done < <(find "$base" -type f -iname '*.cue' ! -name '._*' -print0)
  printf '%s\n' "$updated"
}

preprocess_cue_for_split() {
  local flac="$1"
  local cue="$2"
  local flac_base
  flac_base="$(basename "$flac")"

  # Run per-cue encoding normalization before split (safe no-op if already UTF-8).
  do_iconv_iso2utf "$cue" >/dev/null 2>&1 || true

  # Normalize line endings and strip UTF-8 BOM on the first line.
  perl -i -pe 's/\r$//; s/^\xEF\xBB\xBF// if $.==1' "$cue"

  # Normalize source extensions referenced in FILE rows.
  if grep -Eiq '\.(ape|wv|wav)"' "$cue"; then
    perl -i -pe 's/\.(ape|wv|wav)"/.flac"/ig' "$cue"
  fi

  # Force first FILE row to point to the current FLAC basename.
  FLAC_BASENAME="$flac_base" perl -i -pe '
    BEGIN { $done = 0; }
    if (!$done && /^\s*FILE\s+"/i) {
      s/^(\s*FILE\s+")([^"]*)(".*)$/$1$ENV{FLAC_BASENAME}$3/i;
      $done = 1;
    }
  ' "$cue"
}

extract_disc_number_from_text() {
  local raw="$1" text num
  text="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]')"
  if [[ "$text" =~ (^|[^a-z0-9])(cd|disc|disk)[[:space:]_.-]*0*([1-9][0-9]*)([^0-9]|$) ]]; then
    num="${BASH_REMATCH[3]}"
    printf '%s\n' "$num"
    return 0
  fi
  if [[ "$text" =~ (^|[^a-z0-9])0*([1-9][0-9]*)[[:space:]_.-]*(cd|disc|disk)([^a-z0-9]|$) ]]; then
    num="${BASH_REMATCH[2]}"
    printf '%s\n' "$num"
    return 0
  fi
  return 1
}

extract_disc_number_from_cue() {
  local cue="$1" line num
  line="$(grep -Eim1 '^[[:space:]]*REM[[:space:]]+DISC(NUMBER)?[[:space:]]+\"?[0-9]+' "$cue" || true)"
  if [[ -z "$line" ]]; then
    return 1
  fi
  num="$(printf '%s\n' "$line" | sed -E 's/.*[^0-9]([0-9]+).*/\1/')"
  if [[ "$num" =~ ^[1-9][0-9]*$ ]]; then
    printf '%s\n' "$num"
    return 0
  fi
  return 1
}

disc_used() {
  local target="$1"
  shift
  local item
  for item in "$@"; do
    if [[ "$item" == "$target" ]]; then
      return 0
    fi
  done
  return 1
}

move_file_to_dir() {
  local src="$1"
  local dst_dir="$2"
  [[ -e "$src" ]] || return 1
  mkdir -p "$dst_dir"
  if [[ "$(dirname "$src")" == "$dst_dir" ]]; then
    return 1
  fi
  mv -n "$src" "$dst_dir/" || return 1
  if [[ ! -e "$src" ]]; then
    return 0
  fi
  return 1
}

move_related_files_to_disc_dir() {
  local flac="$1"
  local cue="$2"
  local disc_dir="$3"
  local src_dir flac_stem cue_stem moved
  local stem last_stem extra bn
  moved=0
  src_dir="$(dirname "$flac")"
  flac_stem="$(basename "${flac%.*}")"
  cue_stem="$(basename "${cue%.*}")"
  last_stem=""

  move_file_to_dir "$flac" "$disc_dir" && moved=$((moved + 1))
  move_file_to_dir "$cue" "$disc_dir" && moved=$((moved + 1))
  move_file_to_dir "${cue}.bak" "$disc_dir" && moved=$((moved + 1))
  move_file_to_dir "${cue%.*}.cux" "$disc_dir" && moved=$((moved + 1))

  for stem in "$flac_stem" "$cue_stem"; do
    [[ -n "$stem" ]] || continue
    if [[ "$stem" == "$last_stem" ]]; then
      continue
    fi
    last_stem="$stem"
    while IFS= read -r -d '' extra; do
      bn="$(basename "$extra")"
      if [[ "${bn#"$stem".}" == "$bn" ]]; then
        continue
      fi
      case "$extra" in
        "$flac"|"$cue"|"${cue}.bak"|"${cue%.*}.cux")
          continue
          ;;
      esac
      move_file_to_dir "$extra" "$disc_dir" && moved=$((moved + 1))
    done < <(find "$src_dir" -maxdepth 1 -type f ! -name '._*' -print0)
  done

  printf '%s\n' "$moved"
}

reorganize_multidisc_directories() {
  local base="$1"
  local regroup_dirs=0
  local regroup_groups=0
  local regroup_moved=0

  while IFS= read -r dir; do
    local -a candidate_flacs=()
    local -a candidate_cues=()
    local -a candidate_discs=()
    local flac cue expected disc flac_name cue_name

    while IFS= read -r flac; do
      if ! cue="$(cue_for_flac "$flac")"; then
        continue
      fi
      expected="$(grep -c '^[[:space:]]*TRACK' "$cue" || true)"
      expected="${expected:-0}"
      if [[ "$expected" -le 1 ]]; then
        continue
      fi

      flac_name="$(basename "$flac")"
      cue_name="$(basename "$cue")"
      disc="$(extract_disc_number_from_text "$flac_name" || true)"
      if [[ -z "$disc" ]]; then
        disc="$(extract_disc_number_from_text "$cue_name" || true)"
      fi
      if [[ -z "$disc" ]]; then
        disc="$(extract_disc_number_from_cue "$cue" || true)"
      fi

      candidate_flacs+=("$flac")
      candidate_cues+=("$cue")
      candidate_discs+=("$disc")
    done < <(find "$dir" -maxdepth 1 -type f -iname '*.flac' ! -name '._*' | sort)

    local count i next_free d moved_here disc_dir
    count="${#candidate_flacs[@]}"
    if [[ "$count" -le 1 ]]; then
      continue
    fi

    next_free=1
    for ((i = 0; i < count; i++)); do
      d="${candidate_discs[$i]}"
      if [[ "$d" =~ ^[1-9][0-9]*$ ]]; then
        continue
      fi
      while disc_used "$next_free" "${candidate_discs[@]}"; do
        next_free=$((next_free + 1))
      done
      candidate_discs[$i]="$next_free"
      next_free=$((next_free + 1))
    done

    local -a assigned_discs=()
    for ((i = 0; i < count; i++)); do
      d="${candidate_discs[$i]}"
      if ! [[ "$d" =~ ^[1-9][0-9]*$ ]]; then
        d=1
      fi
      if [[ "${#assigned_discs[@]}" -gt 0 ]]; then
        while disc_used "$d" "${assigned_discs[@]}"; do
          d=$((d + 1))
        done
      fi
      candidate_discs[$i]="$d"
      assigned_discs+=("$d")
    done

    moved_here=0
    for ((i = 0; i < count; i++)); do
      disc_dir="$dir/${candidate_discs[$i]}"
      moved_here=$((moved_here + $(move_related_files_to_disc_dir "${candidate_flacs[$i]}" "${candidate_cues[$i]}" "$disc_dir")))
    done

    regroup_dirs=$((regroup_dirs + 1))
    regroup_groups=$((regroup_groups + count))
    regroup_moved=$((regroup_moved + moved_here))
  done < <(find "$base" -type d ! -name '.AppleDouble' | sort)

  MULTIDISC_DIRS_REORGANIZED="$regroup_dirs"
  MULTIDISC_GROUPS_ASSIGNED="$regroup_groups"
  MULTIDISC_FILES_MOVED="$regroup_moved"
}

has_flac_in_top_dir() {
  local dir="$1"
  find "$dir" -maxdepth 1 -type f -iname '*.flac' ! -name '._*' | grep -q .
}

is_split_track_basename() {
  local bn="$1"
  if [[ "$bn" =~ ^[0-9]{2}([[:space:]]+-.*)?\.flac$ ]]; then
    return 0
  fi
  return 1
}

normalized_split_track_basename() {
  local bn="$1"
  local disc=""
  local track=""
  local title=""

  # Already canonical.
  if [[ "$bn" =~ ^[0-9]{2}[[:space:]]+-[[:space:]].+\.flac$ ]]; then
    return 1
  fi
  if [[ "$bn" =~ ^[1-9][0-9]*-[0-9]{2}[[:space:]]+-[[:space:]].+\.flac$ ]]; then
    return 1
  fi

  # Disc-track variants that are not yet canonical.
  if [[ "$bn" =~ ^([1-9][0-9]?)[[:space:]]*[-_.][[:space:]]*([1-9][0-9]?)[[:space:]]*-[[:space:]]*(.+)\.flac$ ]]; then
    disc="${BASH_REMATCH[1]}"
    track="${BASH_REMATCH[2]}"
    title="${BASH_REMATCH[3]}"
  elif [[ "$bn" =~ ^([1-9][0-9]?)[[:space:]]*[-_.][[:space:]]*([1-9][0-9]?)[._][[:space:]]*(.+)\.flac$ ]]; then
    disc="${BASH_REMATCH[1]}"
    track="${BASH_REMATCH[2]}"
    title="${BASH_REMATCH[3]}"
  elif [[ "$bn" =~ ^([1-9][0-9]?)[[:space:]]*[-_.][[:space:]]*([1-9][0-9]?)\)[[:space:]]*(.+)\.flac$ ]]; then
    disc="${BASH_REMATCH[1]}"
    track="${BASH_REMATCH[2]}"
    title="${BASH_REMATCH[3]}"
  # Track-only variants that are not yet canonical.
  elif [[ "$bn" =~ ^([1-9][0-9]?)\.[[:space:]]*(.+)\.flac$ ]]; then
    track="${BASH_REMATCH[1]}"
    title="${BASH_REMATCH[2]}"
  elif [[ "$bn" =~ ^([1-9][0-9]?)\)[[:space:]]*(.+)\.flac$ ]]; then
    track="${BASH_REMATCH[1]}"
    title="${BASH_REMATCH[2]}"
  elif [[ "$bn" =~ ^([1-9][0-9]?)_[[:space:]]*(.+)\.flac$ ]]; then
    track="${BASH_REMATCH[1]}"
    title="${BASH_REMATCH[2]}"
  elif [[ "$bn" =~ ^([1-9][0-9]?)[[:space:]]*-[[:space:]]*(.+)\.flac$ ]]; then
    track="${BASH_REMATCH[1]}"
    title="${BASH_REMATCH[2]}"
  elif [[ "$bn" =~ ^([1-9][0-9]?)[[:space:]]+(.+)\.flac$ ]]; then
    track="${BASH_REMATCH[1]}"
    title="${BASH_REMATCH[2]}"
  else
    return 1
  fi

  title="$(printf '%s\n' "$title" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//; s/[[:space:]]+/ /g')"
  if [[ -z "$title" ]]; then
    return 1
  fi

  if [[ -n "$disc" ]]; then
    printf '%d-%02d - %s.flac\n' "$disc" "$track" "$title"
  else
    printf '%02d - %s.flac\n' "$track" "$title"
  fi
}

normalize_split_track_prefixes() {
  local base="$1"
  local total_renamed=0
  local total_dirs=0
  local dir

  while IFS= read -r dir; do
    local -a flacs=()
    local -a srcs=()
    local -a dsts=()
    local -a tmps=()
    local f bn dst cue1 cue2
    local i j conflict target owned src_bn tmp

    while IFS= read -r -d '' f; do
      flacs+=("$f")
    done < <(find "$dir" -maxdepth 1 -type f -iname '*.flac' ! -name '._*' -print0)

    if [[ "${#flacs[@]}" -lt 2 ]]; then
      continue
    fi

    for f in "${flacs[@]}"; do
      cue1="${f%.*}.cue"
      cue2="${f}.cue"
      # Keep whole-image FLAC(+CUE) untouched.
      if [[ -f "$cue1" || -f "$cue2" ]]; then
        continue
      fi
      bn="$(basename "$f")"
      dst="$(normalized_split_track_basename "$bn" || true)"
      if [[ -z "$dst" || "$dst" == "$bn" ]]; then
        continue
      fi
      srcs+=("$f")
      dsts+=("$dst")
    done

    # Require at least two candidates to avoid accidental single-file rename.
    if [[ "${#srcs[@]}" -lt 2 ]]; then
      continue
    fi

    conflict=0
    for ((i = 0; i < ${#dsts[@]}; i++)); do
      target="${dsts[$i]}"
      for ((j = i + 1; j < ${#dsts[@]}; j++)); do
        if [[ "${dsts[$j]}" == "$target" ]]; then
          conflict=1
          break
        fi
      done
      if [[ "$conflict" -eq 1 ]]; then
        break
      fi

      if [[ -e "$dir/$target" ]]; then
        owned=0
        for ((j = 0; j < ${#srcs[@]}; j++)); do
          src_bn="$(basename "${srcs[$j]}")"
          if [[ "$src_bn" == "$target" ]]; then
            owned=1
            break
          fi
        done
        if [[ "$owned" -ne 1 ]]; then
          conflict=1
          break
        fi
      fi
    done
    if [[ "$conflict" -eq 1 ]]; then
      continue
    fi

    for ((i = 0; i < ${#srcs[@]}; i++)); do
      tmp="$dir/.wb_tmp_rename_${$}_${RANDOM}_${i}.flac"
      while [[ -e "$tmp" ]]; do
        tmp="$dir/.wb_tmp_rename_${$}_${RANDOM}_${i}.flac"
      done
      mv "${srcs[$i]}" "$tmp"
      tmps+=("$tmp")
    done

    for ((i = 0; i < ${#tmps[@]}; i++)); do
      mv "${tmps[$i]}" "$dir/${dsts[$i]}"
      total_renamed=$((total_renamed + 1))
    done
    total_dirs=$((total_dirs + 1))
  done < <(find "$base" -type d ! -name '.AppleDouble' | sort)

  TRACK_PREFIX_NORMALIZED="$total_renamed"
  TRACK_PREFIX_DIRS_CHANGED="$total_dirs"
}

count_split_tracks_in_top_dir() {
  local dir="$1"
  local count=0
  local f bn
  while IFS= read -r -d '' f; do
    bn="$(basename "$f")"
    if is_split_track_basename "$bn"; then
      count=$((count + 1))
    fi
  done < <(find "$dir" -maxdepth 1 -type f -iname '*.flac' ! -name '._*' -print0)
  printf '%s\n' "$count"
}

is_disc_like_dir_name() {
  local name="$1"
  if [[ "$name" =~ ^0*[1-9][0-9]*$ ]]; then
    return 0
  fi
  if [[ "$name" =~ ^([Cc][Dd]|[Dd][Ii][Ss][Cc]|[Dd][Ii][Ss][Kk])([[:space:]_-]*0*[1-9][0-9]*)?$ ]]; then
    return 0
  fi
  return 1
}

count_disc_like_subdirs_with_split_tracks() {
  local dir="$1"
  local count=0
  local sub name split_tracks
  while IFS= read -r -d '' sub; do
    name="$(basename "$sub")"
    if ! is_disc_like_dir_name "$name"; then
      continue
    fi
    split_tracks="$(count_split_tracks_in_top_dir "$sub")"
    if [[ "$split_tracks" -gt 0 ]]; then
      count=$((count + 1))
    fi
  done < <(find "$dir" -mindepth 1 -maxdepth 1 -type d -print0)
  printf '%s\n' "$count"
}

promote_single_disc_to_parent() {
  local base="$1"
  local promoted_dirs=0
  local moved_files=0
  local dir sub name split_tracks top_split
  local candidate_sub=""
  local candidate_count=0
  local f bn moved_here

  while IFS= read -r dir; do
    [[ -d "$dir" ]] || continue
    top_split="$(count_split_tracks_in_top_dir "$dir")"
    if [[ "$top_split" -gt 0 ]]; then
      continue
    fi

    candidate_sub=""
    candidate_count=0
    while IFS= read -r -d '' sub; do
      name="$(basename "$sub")"
      if ! is_disc_like_dir_name "$name"; then
        continue
      fi
      split_tracks="$(count_split_tracks_in_top_dir "$sub")"
      if [[ "$split_tracks" -le 0 ]]; then
        continue
      fi
      candidate_count=$((candidate_count + 1))
      candidate_sub="$sub"
      if [[ "$candidate_count" -gt 1 ]]; then
        break
      fi
    done < <(find "$dir" -mindepth 1 -maxdepth 1 -type d -print0)

    if [[ "$candidate_count" -ne 1 || -z "$candidate_sub" ]]; then
      continue
    fi

    moved_here=0
    while IFS= read -r -d '' f; do
      bn="$(basename "$f")"
      if ! is_split_track_basename "$bn"; then
        continue
      fi
      if mv -n "$f" "$dir/" >/dev/null 2>&1; then
        moved_here=$((moved_here + 1))
      fi
    done < <(find "$candidate_sub" -maxdepth 1 -type f -iname '*.flac' ! -name '._*' -print0)

    if [[ "$moved_here" -gt 0 ]]; then
      promoted_dirs=$((promoted_dirs + 1))
      moved_files=$((moved_files + moved_here))
    fi
  done < <(find "$base" -type d ! -name '.AppleDouble' | sort)

  SINGLE_DISC_DIRS_PROMOTED="$promoted_dirs"
  SINGLE_DISC_FILES_MOVED="$moved_files"
}

consolidate_multidisc_to_parent() {
  local base="$1"
  local total=0
  local ok=0
  local fail=0
  local dir cd_subdirs

  while IFS= read -r dir; do
    [[ -d "$dir" ]] || continue
    cd_subdirs="$(count_disc_like_subdirs_with_split_tracks "$dir")"
    if [[ "$cd_subdirs" -lt 2 ]]; then
      continue
    fi

    total=$((total + 1))
    if (cd "$dir" && WHITEBULL_DIR="$WHITEBULL_DIR" "$MERGE_MULTI_CD" 1 200 >/dev/null 2>&1); then
      ok=$((ok + 1))
    else
      fail=$((fail + 1))
      if [[ "$CONTINUE_ON_ERROR" -ne 1 ]]; then
        echo "ERROR: consolidate failed: $dir" >&2
        exit 5
      fi
    fi
  done < <(find "$base" -type d ! -name '.AppleDouble' | sort)

  CONSOLIDATE_DIRS=$total
  CONSOLIDATE_OK=$ok
  CONSOLIDATE_FAIL=$fail
}

count_ext() {
  local dir="$1"
  local ext="$2"
  find "$dir" -type f -iname "*.${ext}" ! -name '._*' | wc -l | tr -d '[:space:]'
}

count_flac_other_than() {
  local dir="$1"
  local base="$2"
  find "$dir" -maxdepth 1 -type f -iname '*.flac' ! -name "$base" ! -name '._*' | wc -l | tr -d '[:space:]'
}

verify_split_outputs_complete() {
  local flac="$1"
  local expected="$2"
  local dir base other_count split_like_count bad_count
  local f bn

  dir="$(dirname "$flac")"
  base="$(basename "$flac")"
  other_count="$(count_flac_other_than "$dir" "$base")"
  if [[ "$other_count" -lt "$expected" ]]; then
    return 1
  fi

  split_like_count=0
  bad_count=0
  while IFS= read -r -d '' f; do
    bn="$(basename "$f")"
    if ! is_split_track_basename "$bn"; then
      continue
    fi
    split_like_count=$((split_like_count + 1))
    if ! flac -t "$f" >/dev/null 2>&1; then
      bad_count=$((bad_count + 1))
    fi
  done < <(find "$dir" -maxdepth 1 -type f -iname '*.flac' ! -name "$base" ! -name '._*' -print0)

  if [[ "$split_like_count" -ge "$expected" ]]; then
    [[ "$bad_count" -eq 0 ]]
    return
  fi

  bad_count=0
  while IFS= read -r -d '' f; do
    if ! flac -t "$f" >/dev/null 2>&1; then
      bad_count=$((bad_count + 1))
    fi
  done < <(find "$dir" -maxdepth 1 -type f -iname '*.flac' ! -name "$base" ! -name '._*' -print0)

  [[ "$bad_count" -eq 0 ]]
}

cue_for_flac() {
  local flac="$1"
  local cue1 cue2
  cue1="${flac%.*}.cue"
  cue2="${flac}.cue"
  if [[ -f "$cue1" ]]; then
    printf '%s\n' "$cue1"
    return 0
  fi
  if [[ -f "$cue2" ]]; then
    printf '%s\n' "$cue2"
    return 0
  fi
  return 1
}

count_wav_pending() {
  local base="$1"
  local pending=0
  while IFS= read -r -d '' wav; do
    local target
    target="${wav%.*}.flac"
    if [[ ! -f "$target" ]]; then
      pending=$((pending + 1))
    fi
  done < <(find "$base" -type f -iname '*.wav' ! -name '._*' -print0)
  printf '%s\n' "$pending"
}

remove_wav_sources_if_flac_exists() {
  local base="$1"
  local removed=0
  while IFS= read -r -d '' wav; do
    local target
    target="${wav%.*}.flac"
    if [[ -f "$target" ]]; then
      rm -f "$wav"
      removed=$((removed + 1))
    fi
  done < <(find "$base" -type f -iname '*.wav' ! -name '._*' -print0)
  printf '%s\n' "$removed"
}

split_flac_with_cue() {
  local base="$1"
  local split_ok=0
  local split_skip=0
  local split_fail=0
  local split_cue_preprocessed=0
  local split_damaged_skipped=0
  local split_source_removed=0
  local split_source_remove_skipped=0

  while IFS= read -r -d '' flac; do
    local cue expected other_count flac_base
    if ! cue="$(cue_for_flac "$flac")"; then
      continue
    fi

    if ! flac -t "$flac" >/dev/null 2>&1; then
      split_skip=$((split_skip + 1))
      split_damaged_skipped=$((split_damaged_skipped + 1))
      continue
    fi

    expected="$(grep -c '^[[:space:]]*TRACK' "$cue" || true)"
    expected="${expected:-0}"
    if [[ "$expected" -le 1 ]]; then
      split_skip=$((split_skip + 1))
      continue
    fi

    flac_base="$(basename "$flac")"
    other_count="$(count_flac_other_than "$(dirname "$flac")" "$flac_base")"
    if [[ "$FORCE_SPLIT" -ne 1 && "$other_count" -ge "$expected" ]]; then
      split_skip=$((split_skip + 1))
      if [[ "$REMOVE_SOURCE_AFTER_SPLIT" -eq 1 ]]; then
        if verify_split_outputs_complete "$flac" "$expected"; then
          rm -f "$flac"
          split_source_removed=$((split_source_removed + 1))
        else
          split_source_remove_skipped=$((split_source_remove_skipped + 1))
        fi
      fi
      continue
    fi

    preprocess_cue_for_split "$flac" "$cue"
    split_cue_preprocessed=$((split_cue_preprocessed + 1))

    local -a cmd
    cmd=("$SPLIT_FLAC")
    cmd+=(-t "$SPLIT_TEMPLATE" "$flac")

    if "${cmd[@]}" >/dev/null 2>&1; then
      split_ok=$((split_ok + 1))
      if [[ "$REMOVE_SOURCE_AFTER_SPLIT" -eq 1 ]]; then
        if verify_split_outputs_complete "$flac" "$expected"; then
          rm -f "$flac"
          split_source_removed=$((split_source_removed + 1))
        else
          split_source_remove_skipped=$((split_source_remove_skipped + 1))
        fi
      fi
    else
      split_fail=$((split_fail + 1))
      if [[ "$CONTINUE_ON_ERROR" -ne 1 ]]; then
        echo "ERROR: split failed: $flac" >&2
        exit 4
      fi
    fi
  done < <(find "$base" -type f -iname '*.flac' ! -name '._*' -print0)

  SPLIT_OK=$split_ok
  SPLIT_SKIP=$split_skip
  SPLIT_FAIL=$split_fail
  SPLIT_CUE_PREPROCESSED=$split_cue_preprocessed
  SPLIT_DAMAGED_SKIPPED=$split_damaged_skipped
  SPLIT_SOURCE_REMOVED=$split_source_removed
  SPLIT_SOURCE_REMOVE_SKIPPED=$split_source_remove_skipped
}

APE_BEFORE="$(count_ext "$SOURCE_DIR" ape)"
WV_BEFORE="$(count_ext "$SOURCE_DIR" wv)"
WAV_BEFORE="$(count_ext "$SOURCE_DIR" wav)"
FLAC_BEFORE="$(count_ext "$SOURCE_DIR" flac)"
CUE_BEFORE="$(count_ext "$SOURCE_DIR" cue)"

WAV_CONVERTED=0
WAV_SKIPPED=0
WAV_REMOVED=0
CLEAN_REMOVED_FILES=0
CLEAN_REMOVED_DIRS=0
NORM_EXT_CHANGED=0
CUE_REFS_UPDATED=0
SPLIT_OK=0
SPLIT_SKIP=0
SPLIT_FAIL=0
SPLIT_CUE_PREPROCESSED=0
SPLIT_DAMAGED_SKIPPED=0
SPLIT_SOURCE_REMOVED=0
SPLIT_SOURCE_REMOVE_SKIPPED=0
MULTIDISC_DIRS_REORGANIZED=0
MULTIDISC_GROUPS_ASSIGNED=0
MULTIDISC_FILES_MOVED=0
CONSOLIDATE_DIRS=0
CONSOLIDATE_OK=0
CONSOLIDATE_FAIL=0
SINGLE_DISC_DIRS_PROMOTED=0
SINGLE_DISC_FILES_MOVED=0
TRACK_PREFIX_NORMALIZED=0
TRACK_PREFIX_DIRS_CHANGED=0

if [[ "$SKIP_CLEAN" -ne 1 ]]; then
  cleanup_sidecar_files "$SOURCE_DIR"
  NORM_EXT_CHANGED=$((NORM_EXT_CHANGED + $(normalize_extension_case "$SOURCE_DIR" flac)))
  NORM_EXT_CHANGED=$((NORM_EXT_CHANGED + $(normalize_extension_case "$SOURCE_DIR" cue)))
  NORM_EXT_CHANGED=$((NORM_EXT_CHANGED + $(normalize_extension_case "$SOURCE_DIR" wav)))
  NORM_EXT_CHANGED=$((NORM_EXT_CHANGED + $(normalize_extension_case "$SOURCE_DIR" ape)))
  NORM_EXT_CHANGED=$((NORM_EXT_CHANGED + $(normalize_extension_case "$SOURCE_DIR" wv)))
fi

if [[ "$SKIP_CONVERT" -ne 1 ]]; then
  if [[ "$KEEP_APE_SOURCE" -eq 1 ]]; then
    "$APE2FLAC" --keep-original "$SOURCE_DIR" >/dev/null
  else
    "$APE2FLAC" "$SOURCE_DIR" >/dev/null
  fi

  WAV_PENDING_BEFORE="$(count_wav_pending "$SOURCE_DIR")"
  (
    cd "$SOURCE_DIR"
    "$WAV2FLAC" >/dev/null 2>&1 || true
  )
  WAV_PENDING_AFTER="$(count_wav_pending "$SOURCE_DIR")"
  WAV_CONVERTED=$((WAV_PENDING_BEFORE - WAV_PENDING_AFTER))
  WAV_SKIPPED="$WAV_PENDING_AFTER"
  if [[ "$REMOVE_WAV_SOURCE" -eq 1 ]]; then
    WAV_REMOVED="$(remove_wav_sources_if_flac_exists "$SOURCE_DIR")"
  fi

  # Normalize cue encoding before split stage.
  do_iconv_iso2utf "$SOURCE_DIR" >/dev/null 2>&1 || true
fi

if [[ "$SKIP_CLEAN" -ne 1 ]]; then
  CUE_REFS_UPDATED="$(normalize_cue_file_refs_to_flac "$SOURCE_DIR")"
fi

if [[ "$SKIP_SPLIT" -ne 1 ]]; then
  reorganize_multidisc_directories "$SOURCE_DIR"
  split_flac_with_cue "$SOURCE_DIR"
  if [[ "$SKIP_CONSOLIDATE" -ne 1 ]]; then
    promote_single_disc_to_parent "$SOURCE_DIR"
    consolidate_multidisc_to_parent "$SOURCE_DIR"
  fi
fi

if [[ "$SKIP_CLEAN" -ne 1 ]]; then
  normalize_split_track_prefixes "$SOURCE_DIR"
fi

APE_AFTER="$(count_ext "$SOURCE_DIR" ape)"
WV_AFTER="$(count_ext "$SOURCE_DIR" wv)"
WAV_AFTER="$(count_ext "$SOURCE_DIR" wav)"
FLAC_AFTER="$(count_ext "$SOURCE_DIR" flac)"
CUE_AFTER="$(count_ext "$SOURCE_DIR" cue)"

if [[ "$OUTPUT_JSON" -eq 1 ]]; then
  python3 - "$SOURCE_DIR" "$SPLIT_TEMPLATE" <<PY
import json
import sys

payload = {
    "ok": ${SPLIT_FAIL} == 0,
    "source_dir": sys.argv[1],
    "cleanup": {
        "skip_clean": ${SKIP_CLEAN} == 1,
        "removed_files": ${CLEAN_REMOVED_FILES},
        "removed_dirs": ${CLEAN_REMOVED_DIRS},
        "normalized_extensions": ${NORM_EXT_CHANGED},
        "cue_refs_updated": ${CUE_REFS_UPDATED},
        "track_prefix_normalized": ${TRACK_PREFIX_NORMALIZED},
        "track_prefix_dirs_changed": ${TRACK_PREFIX_DIRS_CHANGED},
    },
    "counts_before": {
        "ape": ${APE_BEFORE},
        "wv": ${WV_BEFORE},
        "wav": ${WAV_BEFORE},
        "flac": ${FLAC_BEFORE},
        "cue": ${CUE_BEFORE},
    },
    "counts_after": {
        "ape": ${APE_AFTER},
        "wv": ${WV_AFTER},
        "wav": ${WAV_AFTER},
        "flac": ${FLAC_AFTER},
        "cue": ${CUE_AFTER},
    },
    "conversion": {
        "skip_convert": ${SKIP_CONVERT} == 1,
        "keep_ape_source": ${KEEP_APE_SOURCE} == 1,
        "remove_wav_source": ${REMOVE_WAV_SOURCE} == 1,
        "wav_converted": ${WAV_CONVERTED},
        "wav_skipped_existing": ${WAV_SKIPPED},
        "wav_removed": ${WAV_REMOVED},
    },
    "split": {
        "skip_split": ${SKIP_SPLIT} == 1,
        "skip_consolidate": ${SKIP_CONSOLIDATE} == 1,
        "force_split": ${FORCE_SPLIT} == 1,
        "remove_source_after_split": ${REMOVE_SOURCE_AFTER_SPLIT} == 1,
        "template": sys.argv[2],
        "single_disc_dirs_promoted": ${SINGLE_DISC_DIRS_PROMOTED},
        "single_disc_files_moved": ${SINGLE_DISC_FILES_MOVED},
        "multidisc_dirs_reorganized": ${MULTIDISC_DIRS_REORGANIZED},
        "multidisc_groups_assigned": ${MULTIDISC_GROUPS_ASSIGNED},
        "multidisc_files_moved": ${MULTIDISC_FILES_MOVED},
        "consolidated_dirs": ${CONSOLIDATE_DIRS},
        "consolidated_ok": ${CONSOLIDATE_OK},
        "consolidated_failed": ${CONSOLIDATE_FAIL},
        "cue_preprocessed": ${SPLIT_CUE_PREPROCESSED},
        "damaged_skipped": ${SPLIT_DAMAGED_SKIPPED},
        "source_removed": ${SPLIT_SOURCE_REMOVED},
        "source_remove_skipped": ${SPLIT_SOURCE_REMOVE_SKIPPED},
        "success": ${SPLIT_OK},
        "skipped": ${SPLIT_SKIP},
        "failed": ${SPLIT_FAIL},
    },
}
print(json.dumps(payload, ensure_ascii=False))
PY
else
  echo "[flac-skill] source: $SOURCE_DIR"
  echo "[flac-skill] cleanup skip=$SKIP_CLEAN removed_files=$CLEAN_REMOVED_FILES removed_dirs=$CLEAN_REMOVED_DIRS norm_ext=$NORM_EXT_CHANGED cue_refs_updated=$CUE_REFS_UPDATED track_prefix_normalized=$TRACK_PREFIX_NORMALIZED track_prefix_dirs_changed=$TRACK_PREFIX_DIRS_CHANGED"
  echo "[flac-skill] before: ape=$APE_BEFORE wv=$WV_BEFORE wav=$WAV_BEFORE flac=$FLAC_BEFORE cue=$CUE_BEFORE"
  echo "[flac-skill] after:  ape=$APE_AFTER wv=$WV_AFTER wav=$WAV_AFTER flac=$FLAC_AFTER cue=$CUE_AFTER"
  echo "[flac-skill] wav converted=$WAV_CONVERTED pending_after=$WAV_SKIPPED removed=$WAV_REMOVED"
  echo "[flac-skill] split single_disc_promoted_dirs=$SINGLE_DISC_DIRS_PROMOTED single_disc_tracks_moved=$SINGLE_DISC_FILES_MOVED regroup_dirs=$MULTIDISC_DIRS_REORGANIZED regroup_groups=$MULTIDISC_GROUPS_ASSIGNED moved=$MULTIDISC_FILES_MOVED consolidated_dirs=$CONSOLIDATE_DIRS consolidated_ok=$CONSOLIDATE_OK consolidated_failed=$CONSOLIDATE_FAIL cue_preprocessed=$SPLIT_CUE_PREPROCESSED damaged_skipped=$SPLIT_DAMAGED_SKIPPED source_removed=$SPLIT_SOURCE_REMOVED source_remove_skipped=$SPLIT_SOURCE_REMOVE_SKIPPED success=$SPLIT_OK skipped=$SPLIT_SKIP failed=$SPLIT_FAIL"
fi

if [[ "$SPLIT_FAIL" -ne 0 || "$CONSOLIDATE_FAIL" -ne 0 ]]; then
  exit 4
fi
