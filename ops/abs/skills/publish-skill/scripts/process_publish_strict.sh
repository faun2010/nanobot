#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  process_publish_strict.sh --album-dir DIR --target-root DIR [options]

Options:
  --album-dir DIR              Album root directory.
  --target-root DIR            Publish destination root (MUSIC_ROOT), e.g. /Volumes/data3/abs_tgt.
  --work-index N               Publish one work index (repeatable).
  --from-index N               Publish index range start (inclusive).
  --to-index N                 Publish index range end (inclusive).
  --cleanup-only               Only cleanup hidden files (no publish).
  --cleanup-path DIR           Path to cleanup in cleanup-only mode (repeatable).
  --overwrite-dup-cache        Set OVERWRITE=1 to bypass duplicate-cache blocking.
  --force-overwrite-dup-cache  Allow overwrite-dup-cache on source albums (dangerous; use only when explicitly approved).
  --full-refresh               Do full runme processing before publish (default: publish-only).
  --stop-on-error              Stop on first failed work.
  --dry-run                    Pass dry-run to runme-skill (no publish move).
  --no-move-to-done            Skip moving successful source album into sibling 0_done/.
  --done-dir DIR               Override done destination directory (default: dirname(album_dir)/0_done).
  --json                       Print JSON summary from runme-skill.
  --help                       Show this help.
EOF
}

ALBUM_DIR=""
TARGET_ROOT=""
OVERWRITE_DUP_CACHE=0
FORCE_OVERWRITE_DUP_CACHE=0
FULL_REFRESH=0
STOP_ON_ERROR=0
DRY_RUN=0
JSON_OUT=0
CLEANUP_ONLY=0
MOVE_TO_DONE=1
DONE_DIR=""

WORK_INDEX_ARGS=()
RANGE_ARGS=()
CLEANUP_PATHS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --album-dir)
      ALBUM_DIR="$2"
      shift 2
      ;;
    --target-root)
      TARGET_ROOT="$2"
      shift 2
      ;;
    --work-index)
      WORK_INDEX_ARGS+=(--work-index "$2")
      shift 2
      ;;
    --from-index|--to-index)
      RANGE_ARGS+=("$1" "$2")
      shift 2
      ;;
    --cleanup-only)
      CLEANUP_ONLY=1
      shift
      ;;
    --cleanup-path)
      CLEANUP_PATHS+=("$2")
      shift 2
      ;;
    --overwrite-dup-cache)
      OVERWRITE_DUP_CACHE=1
      shift
      ;;
    --force-overwrite-dup-cache)
      FORCE_OVERWRITE_DUP_CACHE=1
      shift
      ;;
    --full-refresh)
      FULL_REFRESH=1
      shift
      ;;
    --stop-on-error)
      STOP_ON_ERROR=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --no-move-to-done)
      MOVE_TO_DONE=0
      shift
      ;;
    --done-dir)
      DONE_DIR="$2"
      shift 2
      ;;
    --json)
      JSON_OUT=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WHITEBULL_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
RUNME_STRICT="$WHITEBULL_DIR/skills/runme-skill/scripts/process_runme_strict.sh"

if [[ $CLEANUP_ONLY -ne 1 ]]; then
  if [[ -z "$ALBUM_DIR" || -z "$TARGET_ROOT" ]]; then
    echo "ERROR: --album-dir and --target-root are required." >&2
    usage >&2
    exit 2
  fi

  if [[ ! -d "$ALBUM_DIR" ]]; then
    echo "ERROR: album dir not found: $ALBUM_DIR" >&2
    exit 2
  fi

  if [[ ! -d "$TARGET_ROOT" ]]; then
    echo "ERROR: target root not found: $TARGET_ROOT" >&2
    exit 2
  fi

  if [[ ! -x "$RUNME_STRICT" ]]; then
    echo "ERROR: runme strict script not executable: $RUNME_STRICT" >&2
    exit 2
  fi
fi

cleanup_empty_work_dirs() {
  local removed=0
  while IFS= read -r -d '' d; do
    local b
    b="$(basename "$d")"
    if [[ ! "$b" =~ ^[0-9]+$ ]]; then
      continue
    fi

    find "$d" -mindepth 1 -maxdepth 1 -type f \( -name '.DS_Store' -o -name '._*' \) -exec rm -f -- {} + 2>/dev/null || true
    find "$d" -mindepth 1 -maxdepth 1 -type d -name '.AppleDouble' -exec rm -rf -- {} + 2>/dev/null || true

    if find "$d" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
      continue
    fi

    if rmdir "$d" 2>/dev/null; then
      rm -f "$ALBUM_DIR/._$b" 2>/dev/null || true
      removed=$((removed + 1))
    fi
  done < <(find "$ALBUM_DIR" -mindepth 1 -maxdepth 1 -type d -name '[0-9]*' -print0)

  echo "[publish-skill] removed_empty_work_dirs=$removed"
}

cleanup_hidden_tree() {
  local root="$1"
  local removed_files=0
  local removed_dirs=0
  [[ -d "$root" ]] || { echo "0 0"; return; }

  while IFS= read -r -d '' p; do
    local base dir origin
    base="$(basename "$p")"
    dir="$(dirname "$p")"

    # Some external filesystems recreate ._* sidecars from xattrs.
    # Clear xattrs on the paired item first when possible.
    if [[ "$base" == ._* ]] && command -v xattr >/dev/null 2>&1; then
      origin="$dir/${base#._}"
      if [[ -e "$origin" ]]; then
        xattr -c "$origin" >/dev/null 2>&1 || true
      fi
    fi

    if rm -f -- "$p" 2>/dev/null; then
      removed_files=$((removed_files + 1))
    fi
  done < <(find "$root" -depth -type f \( -name '.DS_Store' -o -name '._*' \) -print0)

  while IFS= read -r -d '' d; do
    if rm -rf -- "$d" 2>/dev/null; then
      removed_dirs=$((removed_dirs + 1))
    fi
  done < <(find "$root" -depth -type d -name '.AppleDouble' -print0)

  # On some external filesystems, xattrs on directories regenerate ._* sidecars.
  # Try clearing xattrs across the tree, then sweep ._* one more time.
  if command -v xattr >/dev/null 2>&1; then
    while IFS= read -r -d '' d; do
      xattr -c "$d" >/dev/null 2>&1 || true
    done < <(find "$root" -depth -type d ! -name '.AppleDouble' -print0)
  fi

  while IFS= read -r -d '' p; do
    if rm -f -- "$p" 2>/dev/null; then
      removed_files=$((removed_files + 1))
    fi
  done < <(find "$root" -depth -type f \( -name '.DS_Store' -o -name '._*' \) -print0)

  echo "$removed_files $removed_dirs"
}

resolve_done_dir() {
  if [[ -n "$DONE_DIR" ]]; then
    printf '%s\n' "$DONE_DIR"
    return
  fi
  printf '%s/0_done\n' "$(dirname "$ALBUM_DIR")"
}

is_album_inside_target_root() {
  local album_norm target_norm
  album_norm="${ALBUM_DIR%/}"
  target_norm="${TARGET_ROOT%/}"
  case "$album_norm/" in
    "$target_norm"/*) return 0 ;;
    *) return 1 ;;
  esac
}

assert_overwrite_guard() {
  if [[ $OVERWRITE_DUP_CACHE -ne 1 ]]; then
    return
  fi
  if is_album_inside_target_root; then
    return
  fi
  if [[ $FORCE_OVERWRITE_DUP_CACHE -eq 1 ]]; then
    return
  fi
  cat >&2 <<'EOF'
ERROR: --overwrite-dup-cache would bypass duplicate protection for a source album.
Refusing by default. Re-run with --force-overwrite-dup-cache only if explicitly approved.
EOF
  exit 2
}

extract_json_from_output() {
  local raw="$1"
  python3 - "$raw" <<'PY'
import json
import sys

raw = sys.argv[1]
lines = [line.strip() for line in raw.splitlines() if line.strip()]
for line in reversed(lines):
    if not line.startswith("{"):
        continue
    try:
        obj = json.loads(line)
    except Exception:
        continue
    print(json.dumps(obj, ensure_ascii=False))
    raise SystemExit(0)
raise SystemExit(1)
PY
}

extract_publish_dirs() {
  local payload_json="$1"
  python3 - "$payload_json" <<'PY'
import json
import re
import sys

payload = json.loads(sys.argv[1])
paths = []
seen = set()
for item in payload.get("results", []):
    for step in item.get("steps", []):
        if step.get("name") != "runme-force-publish":
            continue
        stdout = step.get("stdout", "") or ""
        for match in re.findall(r"Publish to (.+?) done\.", stdout):
            p = match.strip()
            if p and p not in seen:
                seen.add(p)
                paths.append(p)
for p in paths:
    print(p)
PY
}

if [[ $CLEANUP_ONLY -eq 1 ]]; then
  if [[ ${#CLEANUP_PATHS[@]} -eq 0 ]]; then
    if [[ -n "$ALBUM_DIR" ]]; then
      CLEANUP_PATHS+=("$ALBUM_DIR")
    fi
    if [[ -n "$TARGET_ROOT" ]]; then
      CLEANUP_PATHS+=("$TARGET_ROOT")
    fi
  fi

  if [[ ${#CLEANUP_PATHS[@]} -eq 0 ]]; then
    echo "ERROR: cleanup-only mode requires --cleanup-path (or --album-dir/--target-root)." >&2
    exit 2
  fi

  cleanup_files=0
  cleanup_dirs=0
  cleaned=()
  for p in "${CLEANUP_PATHS[@]}"; do
    if [[ ! -d "$p" ]]; then
      continue
    fi
    cleaned+=("$p")
    read -r f d <<<"$(cleanup_hidden_tree "$p")"
    cleanup_files=$((cleanup_files + f))
    cleanup_dirs=$((cleanup_dirs + d))
  done

  if [[ $JSON_OUT -eq 1 ]]; then
    python3 - "$cleanup_files" "$cleanup_dirs" "${cleaned[@]}" <<'PY'
import json
import sys

cleanup_files = int(sys.argv[1])
cleanup_dirs = int(sys.argv[2])
cleaned_paths = sys.argv[3:]
print(json.dumps({
  "ok": True,
  "cleanup_only": True,
  "cleaned_paths": cleaned_paths,
  "cleanup": {
    "hidden_files_removed": cleanup_files,
    "hidden_dirs_removed": cleanup_dirs,
  },
}, ensure_ascii=False))
PY
  else
    echo "[publish-skill] cleanup-only hidden_files_removed=$cleanup_files hidden_dirs_removed=$cleanup_dirs"
  fi
  exit 0
fi

assert_overwrite_guard

cmd=(
  "$RUNME_STRICT"
  --album-dir "$ALBUM_DIR"
  --publish
  --json
)

if [[ $FULL_REFRESH -ne 1 ]]; then
  cmd+=(--skip-fill --skip-enrich --skip-imslp-canonical)
fi

if [[ ${#WORK_INDEX_ARGS[@]} -gt 0 ]]; then
  cmd+=("${WORK_INDEX_ARGS[@]}")
fi
if [[ ${#RANGE_ARGS[@]} -gt 0 ]]; then
  cmd+=("${RANGE_ARGS[@]}")
fi
if [[ $STOP_ON_ERROR -eq 1 ]]; then
  cmd+=(--stop-on-error)
fi
if [[ $DRY_RUN -eq 1 ]]; then
  cmd+=(--dry-run)
fi

set +e
if [[ $OVERWRITE_DUP_CACHE -eq 1 ]]; then
  RUN_OUTPUT="$(OVERWRITE=1 MUSIC_ROOT="$TARGET_ROOT" WHITEBULL_DIR="$WHITEBULL_DIR" "${cmd[@]}" 2>&1)"
  RUN_RC=$?
else
  RUN_OUTPUT="$(OVERWRITE=0 MUSIC_ROOT="$TARGET_ROOT" WHITEBULL_DIR="$WHITEBULL_DIR" "${cmd[@]}" 2>&1)"
  RUN_RC=$?
fi
set -e

PARSED_JSON=""
if PARSED_JSON="$(extract_json_from_output "$RUN_OUTPUT")"; then
  :
else
  echo "$RUN_OUTPUT"
  exit "$RUN_RC"
fi

cleanup_src_files=0
cleanup_src_dirs=0
cleanup_tgt_files=0
cleanup_tgt_dirs=0
removed_empty_work_dirs=0
cleaned_target_dirs_file="$(mktemp)"
source_move_attempted=0
source_moved=0
source_moved_to=""
source_move_skipped_reason=""
source_move_error=""
FINAL_RC="$RUN_RC"

if [[ $DRY_RUN -ne 1 ]]; then
  read -r cleanup_src_files cleanup_src_dirs <<<"$(cleanup_hidden_tree "$ALBUM_DIR")"

  while IFS= read -r p; do
    [[ -z "$p" ]] && continue
    if [[ -d "$p" ]]; then
      read -r f d <<<"$(cleanup_hidden_tree "$p")"
      cleanup_tgt_files=$((cleanup_tgt_files + f))
      cleanup_tgt_dirs=$((cleanup_tgt_dirs + d))

      parent_dir="$(dirname "$p")"
      if [[ -n "$parent_dir" && -d "$parent_dir" ]]; then
        if ! grep -Fxq -- "$parent_dir" "$cleaned_target_dirs_file"; then
          printf '%s\n' "$parent_dir" >> "$cleaned_target_dirs_file"
          read -r pf pd <<<"$(cleanup_hidden_tree "$parent_dir")"
          cleanup_tgt_files=$((cleanup_tgt_files + pf))
          cleanup_tgt_dirs=$((cleanup_tgt_dirs + pd))
        fi
      fi
    fi
  done < <(extract_publish_dirs "$PARSED_JSON")

  before_count="$(find "$ALBUM_DIR" -mindepth 1 -maxdepth 1 -type d -name '[0-9]*' | wc -l | xargs)"
  cleanup_empty_work_dirs >/dev/null
  after_count="$(find "$ALBUM_DIR" -mindepth 1 -maxdepth 1 -type d -name '[0-9]*' | wc -l | xargs)"
  if [[ "$before_count" =~ ^[0-9]+$ && "$after_count" =~ ^[0-9]+$ && "$before_count" -ge "$after_count" ]]; then
    removed_empty_work_dirs=$((before_count - after_count))
  fi
fi

if [[ $MOVE_TO_DONE -ne 1 ]]; then
  source_move_skipped_reason="disabled"
elif [[ $DRY_RUN -eq 1 ]]; then
  source_move_skipped_reason="dry_run"
elif [[ $FINAL_RC -ne 0 ]]; then
  source_move_skipped_reason="publish_failed"
elif is_album_inside_target_root; then
  source_move_skipped_reason="album_under_target_root"
elif [[ "$(basename "$(dirname "$ALBUM_DIR")")" == "0_done" ]]; then
  source_move_skipped_reason="already_in_done"
else
  done_dir_effective="$(resolve_done_dir)"
  mkdir -p "$done_dir_effective"
  move_dest="$done_dir_effective/$(basename "$ALBUM_DIR")"
  if [[ -e "$move_dest" ]]; then
    ts="$(date +%Y%m%d_%H%M%S)"
    move_dest="$done_dir_effective/$(basename "$ALBUM_DIR")__done_${ts}"
    n=1
    while [[ -e "$move_dest" ]]; do
      move_dest="$done_dir_effective/$(basename "$ALBUM_DIR")__done_${ts}_$n"
      n=$((n + 1))
    done
  fi
  source_move_attempted=1
  if mv -- "$ALBUM_DIR" "$move_dest"; then
    source_moved=1
    source_moved_to="$move_dest"
  else
    source_move_error="failed to move source album to done dir: $move_dest"
    FINAL_RC=5
  fi
fi

rm -f -- "$cleaned_target_dirs_file"

if [[ $JSON_OUT -eq 1 ]]; then
  python3 - "$PARSED_JSON" "$RUN_RC" "$FINAL_RC" "$cleanup_src_files" "$cleanup_src_dirs" "$cleanup_tgt_files" "$cleanup_tgt_dirs" "$removed_empty_work_dirs" "$MOVE_TO_DONE" "$source_move_attempted" "$source_moved" "$source_moved_to" "$source_move_skipped_reason" "$source_move_error" <<'PY'
import json
import sys

run_payload = json.loads(sys.argv[1])
run_rc = int(sys.argv[2])
final_rc = int(sys.argv[3])
payload = {
    "ok": bool(run_payload.get("ok", False) and final_rc == 0),
    "run_rc": run_rc,
    "final_rc": final_rc,
    "runme_result": run_payload,
    "cleanup": {
        "source_hidden_files_removed": int(sys.argv[4]),
        "source_hidden_dirs_removed": int(sys.argv[5]),
        "target_hidden_files_removed": int(sys.argv[6]),
        "target_hidden_dirs_removed": int(sys.argv[7]),
        "empty_work_dirs_removed": int(sys.argv[8]),
    },
    "postprocess": {
        "move_to_done_enabled": bool(int(sys.argv[9])),
        "source_move_attempted": bool(int(sys.argv[10])),
        "source_moved": bool(int(sys.argv[11])),
        "source_moved_to": sys.argv[12],
        "source_move_skipped_reason": sys.argv[13],
        "source_move_error": sys.argv[14],
    },
}
print(json.dumps(payload, ensure_ascii=False))
PY
else
  echo "$PARSED_JSON"
  echo "[publish-skill] cleanup source_hidden_files_removed=$cleanup_src_files source_hidden_dirs_removed=$cleanup_src_dirs target_hidden_files_removed=$cleanup_tgt_files target_hidden_dirs_removed=$cleanup_tgt_dirs empty_work_dirs_removed=$removed_empty_work_dirs"
  echo "[publish-skill] postprocess move_to_done_enabled=$MOVE_TO_DONE source_move_attempted=$source_move_attempted source_moved=$source_moved source_moved_to=$source_moved_to source_move_skipped_reason=$source_move_skipped_reason"
  if [[ -n "$source_move_error" ]]; then
    echo "[publish-skill] postprocess error: $source_move_error" >&2
  fi
fi

exit "$FINAL_RC"
