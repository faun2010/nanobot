#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  process_album_strict_once.sh --album-dir DIR --target-root DIR [options]

Options:
  --album-dir DIR          Source album directory.
  --target-root DIR        Target MUSIC_ROOT (e.g. /Volumes/data3/abs_tgt).
  --source-image NAME      Cover source image filename (default: 01.jpg).
  --split-side MODE        Cover split side: right|left|none (default: right).
  --target-size N          Cover max size (default: 1024).
  --min-cover-size N       Cover min side in px (default: 550).
  --online-min-size N      Online candidate min side in px (default: 550).
  --no-flac                Skip flac stage.
  --no-cover               Skip cover stage.
  --no-album               Skip album metadata fetch stage.
  --no-runme               Skip runme stage.
  --no-publish             Skip publish stage.
  --help                   Show this help.
EOF
}

ALBUM_DIR=""
TARGET_ROOT=""
SOURCE_IMAGE="01.jpg"
SPLIT_SIDE="right"
TARGET_SIZE="1024"
MIN_COVER_SIZE="550"
ONLINE_MIN_SIZE="550"
DO_COVER=1
DO_ALBUM=1
DO_RUNME=1
DO_PUBLISH=1
DO_FLAC=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --album-dir)
      ALBUM_DIR="${2:-}"
      shift 2
      ;;
    --target-root)
      TARGET_ROOT="${2:-}"
      shift 2
      ;;
    --source-image)
      SOURCE_IMAGE="${2:-}"
      shift 2
      ;;
    --split-side)
      SPLIT_SIDE="${2:-}"
      shift 2
      ;;
    --target-size)
      TARGET_SIZE="${2:-}"
      shift 2
      ;;
    --min-cover-size)
      MIN_COVER_SIZE="${2:-}"
      shift 2
      ;;
    --online-min-size)
      ONLINE_MIN_SIZE="${2:-}"
      shift 2
      ;;
    --no-cover)
      DO_COVER=0
      shift
      ;;
    --no-flac)
      DO_FLAC=0
      shift
      ;;
    --no-album)
      DO_ALBUM=0
      shift
      ;;
    --no-runme)
      DO_RUNME=0
      shift
      ;;
    --no-publish)
      DO_PUBLISH=0
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

if [[ -z "$ALBUM_DIR" || -z "$TARGET_ROOT" ]]; then
  echo "ERROR: --album-dir and --target-root are required." >&2
  usage >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WHITEBULL_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

FLAC_SCRIPT="$WHITEBULL_DIR/skills/flac-skill/scripts/process_flac_strict.sh"
COVER_SCRIPT="$WHITEBULL_DIR/skills/cover-skill/scripts/prepare_cover_strict.sh"
ALBUM_SCRIPT="$WHITEBULL_DIR/skills/album-skill/scripts/fetch_musicbrainz_db_strict.sh"
RUNME_SCRIPT="$WHITEBULL_DIR/skills/runme-skill/scripts/process_runme_strict.sh"
PUBLISH_SCRIPT="$WHITEBULL_DIR/skills/publish-skill/scripts/process_publish_strict.sh"

for f in "$FLAC_SCRIPT" "$COVER_SCRIPT" "$ALBUM_SCRIPT" "$RUNME_SCRIPT" "$PUBLISH_SCRIPT"; do
  if [[ ! -x "$f" ]]; then
    echo "ERROR: missing executable: $f" >&2
    exit 2
  fi
done

if [[ $DO_FLAC -eq 1 ]]; then
  echo "[strict-once] stage=flac"
  "$FLAC_SCRIPT" --source "$ALBUM_DIR" --json
else
  echo "[strict-once] stage=flac skipped"
fi

if [[ $DO_COVER -eq 1 ]]; then
  echo "[strict-once] stage=cover"
  "$COVER_SCRIPT" \
    --album-dir "$ALBUM_DIR" \
    --source-image "$SOURCE_IMAGE" \
    --split-side "$SPLIT_SIDE" \
    --target-size "$TARGET_SIZE" \
    --min-cover-size "$MIN_COVER_SIZE" \
    --online-min-size "$ONLINE_MIN_SIZE"
else
  echo "[strict-once] stage=cover skipped"
fi

if [[ $DO_ALBUM -eq 1 ]]; then
  echo "[strict-once] stage=album"
  "$ALBUM_SCRIPT" --album-dir "$ALBUM_DIR" --json
else
  echo "[strict-once] stage=album skipped"
fi

if [[ $DO_RUNME -eq 1 ]]; then
  echo "[strict-once] stage=runme"
  "$RUNME_SCRIPT" --album-dir "$ALBUM_DIR" --json
else
  echo "[strict-once] stage=runme skipped"
fi

if [[ $DO_PUBLISH -eq 1 ]]; then
  echo "[strict-once] stage=publish"
  "$PUBLISH_SCRIPT" --album-dir "$ALBUM_DIR" --target-root "$TARGET_ROOT" --json
else
  echo "[strict-once] stage=publish skipped"
fi
