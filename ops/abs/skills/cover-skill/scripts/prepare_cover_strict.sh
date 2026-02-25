#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  prepare_cover_strict.sh --album-dir DIR [--source-image 01.jpg] [--split-side right|left|none] [--target-size 1024] [--catalog-number CATNO] [--release-id MBID] [--online-min-size 550] [--min-cover-size 550] [--no-online-lookup]

Rules:
  - If source image is non-JPG, convert it to JPG first.
  - If no image file exists, recover cover from FLAC metadata, then try online lookup by release_id/catalog number.
  - Online candidates below online-min-size are rejected and search continues.
  - If source image is below min-cover-size (default 550) on any side, stop.
  - If source is between 550 and 1024, keep resolution and only normalize to square.
  - If source is above 1024, normalize to square and downsize to 1024.
  - These limits apply to cover.jpg only; back.jpg is not constrained here.
  - back.jpg is optional and can be missing.
  - back.jpg is inferred by scanning existing JPG/JPEG candidates (no split/crop inference).
EOF
}

ALBUM_DIR=""
SOURCE_IMAGE="01.jpg"
SPLIT_SIDE="right"
TARGET_SIZE="1024"
CATALOG_NUMBER=""
RELEASE_ID=""
ONLINE_LOOKUP=true
ONLINE_MIN_SIZE="550"
MIN_COVER_SIZE="550"
WHITEBULL_DIR="${WHITEBULL_DIR:-/Users/panzm/Music/whitebull}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --album-dir)
      ALBUM_DIR="${2:-}"
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
    --catalog-number)
      CATALOG_NUMBER="${2:-}"
      shift 2
      ;;
    --release-id)
      RELEASE_ID="${2:-}"
      shift 2
      ;;
    --no-online-lookup)
      ONLINE_LOOKUP=false
      shift
      ;;
    --online-lookup)
      ONLINE_LOOKUP=true
      shift
      ;;
    --online-min-size)
      ONLINE_MIN_SIZE="${2:-}"
      shift 2
      ;;
    --min-cover-size)
      MIN_COVER_SIZE="${2:-}"
      shift 2
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

if [[ ! "$SPLIT_SIDE" =~ ^(right|left|none)$ ]]; then
  echo "ERROR: --split-side must be right|left|none" >&2
  exit 2
fi

if [[ ! "$TARGET_SIZE" =~ ^[0-9]+$ ]]; then
  echo "ERROR: --target-size must be an integer" >&2
  exit 2
fi

if [[ ! "$ONLINE_MIN_SIZE" =~ ^[0-9]+$ ]]; then
  echo "ERROR: --online-min-size must be an integer" >&2
  exit 2
fi

if [[ ! "$MIN_COVER_SIZE" =~ ^[0-9]+$ ]]; then
  echo "ERROR: --min-cover-size must be an integer" >&2
  exit 2
fi

if [[ ! -d "$ALBUM_DIR" ]]; then
  echo "ERROR: album directory not found: $ALBUM_DIR" >&2
  exit 3
fi

if [[ ! -d "$WHITEBULL_DIR" ]]; then
  echo "ERROR: WHITEBULL_DIR not found: $WHITEBULL_DIR" >&2
  exit 3
fi

SOURCE_PATH="$ALBUM_DIR/$SOURCE_IMAGE"
COVER_PATH="$ALBUM_DIR/cover.jpg"
SOURCE_ORIGINAL="$SOURCE_IMAGE"
CONVERTED_FROM=""
RECOVERED_FROM=""
BACK_INFERRED_FROM=""
MISSING_TODO_PATH="$ALBUM_DIR/cover_missing.todo.json"
ONLINE_RECOVER_META_PATH="$ALBUM_DIR/cover_online.meta.json"
ONLINE_ATTEMPTED=false
ONLINE_LAST_REASON=""
MB_DB_FETCH_ATTEMPTED=0
MB_DB_FETCH_OK=0
MB_DB_FETCH_SKIPPED_REASON=""
MB_DB_FETCH_ERROR=""
MB_DB_FETCH_PROVIDER=""
MB_DB_FETCH_EXPECTED_FILE=""

if [[ -z "$CATALOG_NUMBER" ]]; then
  album_base="$(basename "$ALBUM_DIR")"
  if [[ "$album_base" =~ ^\[([^\]]+)\] ]]; then
    CATALOG_NUMBER="${BASH_REMATCH[1]}"
  fi
fi

normalize_release_id() {
  local raw="$1"
  if [[ "$raw" =~ discogs\.com/release/([0-9]+) ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
    return 0
  fi
  if [[ "$raw" =~ ([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}) ]]; then
    printf '%s\n' "${BASH_REMATCH[1],,}"
    return 0
  fi
  if [[ "$raw" =~ ^[[:space:]]*([0-9]{4,})[[:space:]]*$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
    return 0
  fi
  return 1
}

detect_release_id() {
  local rid line

  rid="$(normalize_release_id "$RELEASE_ID" || true)"
  if [[ -n "$rid" ]]; then
    RELEASE_ID="$rid"
    return 0
  fi

  if [[ -s "$ALBUM_DIR/_release_id.lst" ]]; then
    while IFS= read -r line; do
      rid="$(normalize_release_id "$line" || true)"
      if [[ -n "$rid" ]]; then
        RELEASE_ID="$rid"
        return 0
      fi
    done < "$ALBUM_DIR/_release_id.lst"
  fi

  if command -v jq >/dev/null 2>&1; then
    for jf in "$ALBUM_DIR/musicbrainz_0.db" "$ALBUM_DIR/musicbrainz_0.json" "$ALBUM_DIR/discogs_0.db" "$ALBUM_DIR/discogs_0.json"; do
      [[ -f "$jf" ]] || continue
      while IFS= read -r line; do
        rid="$(normalize_release_id "$line" || true)"
        if [[ -n "$rid" ]]; then
          RELEASE_ID="$rid"
          return 0
        fi
      done < <(jq -r '.id // empty, .uri // empty, .resource_url // empty' "$jf" 2>/dev/null || true)
    done
  fi

  for jf in "$ALBUM_DIR/musicbrainz_0.db" "$ALBUM_DIR/musicbrainz_0.json" "$ALBUM_DIR/discogs_0.db" "$ALBUM_DIR/discogs_0.json"; do
    [[ -f "$jf" ]] || continue
    line="$(grep -Eo 'https?://[^[:space:]]*discogs\.com/release/[0-9]+' "$jf" 2>/dev/null | head -n 1 || true)"
    rid="$(normalize_release_id "$line" || true)"
    if [[ -n "$rid" ]]; then
      RELEASE_ID="$rid"
      return 0
    fi
    line="$(grep -Eo '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}' "$jf" 2>/dev/null | head -n 1 || true)"
    rid="$(normalize_release_id "$line" || true)"
    if [[ -n "$rid" ]]; then
      RELEASE_ID="$rid"
      return 0
    fi
  done

  RELEASE_ID=""
  return 1
}

ensure_musicbrainz_db_from_release_id() {
  local beethoven provider expected_file
  if [[ -s "$ALBUM_DIR/musicbrainz_0.db" || -s "$ALBUM_DIR/discogs_0.db" ]]; then
    MB_DB_FETCH_SKIPPED_REASON="already_present"
    return 0
  fi

  if [[ -z "$RELEASE_ID" ]]; then
    MB_DB_FETCH_SKIPPED_REASON="release_id_missing"
    return 0
  fi

  provider=""
  expected_file=""
  if [[ "$RELEASE_ID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
    provider="musicbrainz"
    expected_file="musicbrainz_0.db"
  elif [[ "$RELEASE_ID" =~ ^[0-9]{4,}$ ]]; then
    provider="discogs"
    expected_file="discogs_0.db"
  else
    MB_DB_FETCH_SKIPPED_REASON="release_id_unsupported_format"
    return 0
  fi
  MB_DB_FETCH_PROVIDER="$provider"
  MB_DB_FETCH_EXPECTED_FILE="$expected_file"

  beethoven="$WHITEBULL_DIR/absolutely/beethoven_DiscogsWgetRelease.sh"
  if [[ ! -x "$beethoven" ]]; then
    MB_DB_FETCH_SKIPPED_REASON="beethoven_script_missing"
    MB_DB_FETCH_ERROR="$beethoven"
    return 0
  fi

  MB_DB_FETCH_ATTEMPTED=1
  if (cd "$ALBUM_DIR" && "$beethoven" "$RELEASE_ID" >/dev/null 2>&1); then
    if [[ -s "$ALBUM_DIR/$expected_file" ]]; then
      MB_DB_FETCH_OK=1
      MB_DB_FETCH_SKIPPED_REASON=""
      MB_DB_FETCH_ERROR=""
      return 0
    fi
    MB_DB_FETCH_ERROR="beethoven_completed_but_${expected_file}_missing"
    return 1
  fi

  MB_DB_FETCH_ERROR="beethoven_fetch_failed"
  return 1
}

detect_release_id || true
ensure_musicbrainz_db_from_release_id || true

write_missing_todo() {
  local reason="$1"
  local detail="$2"
  printf '{\n' > "$MISSING_TODO_PATH"
  printf '  "ok": false,\n' >> "$MISSING_TODO_PATH"
  printf '  "reason": "%s",\n' "${reason//\"/\\\"}" >> "$MISSING_TODO_PATH"
  printf '  "detail": "%s",\n' "${detail//\"/\\\"}" >> "$MISSING_TODO_PATH"
  printf '  "album_dir": "%s",\n' "${ALBUM_DIR//\"/\\\"}" >> "$MISSING_TODO_PATH"
  printf '  "source_original": "%s",\n' "${SOURCE_ORIGINAL//\"/\\\"}" >> "$MISSING_TODO_PATH"
  printf '  "catalog_number": "%s",\n' "${CATALOG_NUMBER//\"/\\\"}" >> "$MISSING_TODO_PATH"
  printf '  "release_id": "%s",\n' "${RELEASE_ID//\"/\\\"}" >> "$MISSING_TODO_PATH"
  if [[ "$MB_DB_FETCH_ATTEMPTED" -eq 1 ]]; then
    printf '  "musicbrainz_db_fetch_attempted": true,\n' >> "$MISSING_TODO_PATH"
  else
    printf '  "musicbrainz_db_fetch_attempted": false,\n' >> "$MISSING_TODO_PATH"
  fi
  if [[ "$MB_DB_FETCH_OK" -eq 1 ]]; then
    printf '  "musicbrainz_db_fetch_ok": true,\n' >> "$MISSING_TODO_PATH"
  else
    printf '  "musicbrainz_db_fetch_ok": false,\n' >> "$MISSING_TODO_PATH"
  fi
  printf '  "musicbrainz_db_fetch_provider": "%s",\n' "${MB_DB_FETCH_PROVIDER//\"/\\\"}" >> "$MISSING_TODO_PATH"
  printf '  "musicbrainz_db_fetch_expected_file": "%s",\n' "${MB_DB_FETCH_EXPECTED_FILE//\"/\\\"}" >> "$MISSING_TODO_PATH"
  printf '  "musicbrainz_db_fetch_skipped_reason": "%s",\n' "${MB_DB_FETCH_SKIPPED_REASON//\"/\\\"}" >> "$MISSING_TODO_PATH"
  printf '  "musicbrainz_db_fetch_error": "%s",\n' "${MB_DB_FETCH_ERROR//\"/\\\"}" >> "$MISSING_TODO_PATH"
  if $ONLINE_ATTEMPTED; then
    printf '  "online_attempted": true,\n' >> "$MISSING_TODO_PATH"
  else
    printf '  "online_attempted": false,\n' >> "$MISSING_TODO_PATH"
  fi
  printf '  "online_reason": "%s",\n' "${ONLINE_LAST_REASON//\"/\\\"}" >> "$MISSING_TODO_PATH"
  printf '  "required": "provide cover source image >= %sx%s (preferred >= 1024x1024) or explicit cover URL"\n' "$MIN_COVER_SIZE" "$MIN_COVER_SIZE" >> "$MISSING_TODO_PATH"
  printf '}\n' >> "$MISSING_TODO_PATH"
}

resolve_source_path() {
  local ext_lc alt_uc
  if [[ -f "$SOURCE_PATH" ]]; then
    return
  fi
  local stem ext candidate
  stem="${SOURCE_IMAGE%.*}"
  ext="${SOURCE_IMAGE##*.}"
  if [[ "$stem" == "$SOURCE_IMAGE" ]]; then
    stem="$SOURCE_IMAGE"
    ext=""
  fi
  ext_lc="$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')"
  if [[ "$ext_lc" == "jpg" || "$ext_lc" == "jpeg" || -z "$ext" ]]; then
    for alt in jpeg png bmp webp tif tiff; do
      candidate="$ALBUM_DIR/$stem.$alt"
      if [[ -f "$candidate" ]]; then
        SOURCE_PATH="$candidate"
        SOURCE_IMAGE="$(basename "$candidate")"
        return
      fi
      alt_uc="$(printf '%s' "$alt" | tr '[:lower:]' '[:upper:]')"
      candidate="$ALBUM_DIR/$stem.$alt_uc"
      if [[ -f "$candidate" ]]; then
        SOURCE_PATH="$candidate"
        SOURCE_IMAGE="$(basename "$candidate")"
        return
      fi
    done
  fi

  for named in cover.jpg cover_org.jpg folder.jpg front.jpg Cover.jpg Folder.jpg Front.jpg; do
    candidate="$ALBUM_DIR/$named"
    if [[ -f "$candidate" ]]; then
      SOURCE_PATH="$candidate"
      SOURCE_IMAGE="$(basename "$candidate")"
      return
    fi
  done
}

recover_source_image_if_missing() {
  local jpf first_flac rel first_try
  if [[ -f "$SOURCE_PATH" ]]; then
    return 0
  fi

  first_try="$(find "$ALBUM_DIR" -type f -name '*_cover.jpf' ! -name '._*' | LC_ALL=C sort | head -n 1 || true)"
  if [[ -n "$first_try" ]]; then
    cp "$first_try" "$ALBUM_DIR/cover_org.jpg"
    SOURCE_PATH="$ALBUM_DIR/cover_org.jpg"
    SOURCE_IMAGE="cover_org.jpg"
    RECOVERED_FROM="jpf_backup"
    return 0
  fi

  first_flac="$(find "$ALBUM_DIR" -type f -iname '*.flac' ! -name '._*' | LC_ALL=C sort | head -n 1 || true)"
  if [[ -z "$first_flac" ]]; then
    return 1
  fi

  if [[ "$first_flac" == "$ALBUM_DIR/"* ]]; then
    rel="${first_flac#$ALBUM_DIR/}"
  else
    rel="$first_flac"
  fi

  if [[ -x "$WHITEBULL_DIR/composer/mf-image-out" ]]; then
    if (cd "$ALBUM_DIR" && "$WHITEBULL_DIR/composer/mf-image-out" "$rel" >/dev/null 2>&1); then
      if [[ -s "$ALBUM_DIR/cover_org.jpg" ]]; then
        SOURCE_PATH="$ALBUM_DIR/cover_org.jpg"
        SOURCE_IMAGE="cover_org.jpg"
        RECOVERED_FROM="flac_mf_image_out"
        return 0
      fi
    fi
  fi

  if command -v metaflac >/dev/null 2>&1; then
    if metaflac --export-picture-to="$ALBUM_DIR/cover_org.jpg" "$first_flac" >/dev/null 2>&1; then
      if [[ -s "$ALBUM_DIR/cover_org.jpg" ]]; then
        SOURCE_PATH="$ALBUM_DIR/cover_org.jpg"
        SOURCE_IMAGE="cover_org.jpg"
        RECOVERED_FROM="flac_metaflac_export"
        return 0
      fi
    fi
  fi

  if command -v ffmpeg >/dev/null 2>&1; then
    if ffmpeg -loglevel error -y -i "$first_flac" -an -c:v copy "$ALBUM_DIR/cover_org.jpg"; then
      if [[ -s "$ALBUM_DIR/cover_org.jpg" ]]; then
        SOURCE_PATH="$ALBUM_DIR/cover_org.jpg"
        SOURCE_IMAGE="cover_org.jpg"
        RECOVERED_FROM="flac_ffmpeg_extract"
        return 0
      fi
    fi
  fi

  return 1
}

try_online_cover_lookup() {
  local py cmd_out
  local -a cmd
  if ! $ONLINE_LOOKUP; then
    return 1
  fi
  py="$WHITEBULL_DIR/skills/cover-skill/scripts/fetch_cover_online.py"
  if [[ ! -f "$py" ]]; then
    return 1
  fi

  ONLINE_ATTEMPTED=true
  rm -f "$ONLINE_RECOVER_META_PATH"
  cmd=(python3 "$py" --album-dir "$ALBUM_DIR" --min-size "$ONLINE_MIN_SIZE" --output "$ALBUM_DIR/cover_online.jpg" --back-output "$ALBUM_DIR/back.jpg")
  if [[ -n "$CATALOG_NUMBER" ]]; then
    cmd+=(--catalog-number "$CATALOG_NUMBER")
  fi
  if [[ -n "$RELEASE_ID" ]]; then
    cmd+=(--release-id "$RELEASE_ID")
  fi
  if ! cmd_out="$("${cmd[@]}" 2>&1)"; then
    ONLINE_LAST_REASON="$cmd_out"
    return 1
  fi

  if [[ ! -s "$ALBUM_DIR/cover_online.jpg" ]]; then
    ONLINE_LAST_REASON="${cmd_out:-online_no_output_image}"
    return 1
  fi

  printf '%s\n' "$cmd_out" > "$ONLINE_RECOVER_META_PATH"
  ONLINE_LAST_REASON=""
  SOURCE_PATH="$ALBUM_DIR/cover_online.jpg"
  SOURCE_IMAGE="cover_online.jpg"
  RECOVERED_FROM="online_lookup"
  return 0
}

convert_source_to_jpg_if_needed() {
  local mime out_jpg base original_name
  mime="$(file -b --mime-type "$SOURCE_PATH" || true)"
  if [[ "$mime" == "image/jpeg" ]]; then
    return
  fi
  if [[ "$mime" != image/* ]]; then
    echo "ERROR: source is not an image: $SOURCE_PATH ($mime)" >&2
    exit 4
  fi
  base="${SOURCE_IMAGE%.*}"
  if [[ "$base" == "$SOURCE_IMAGE" ]]; then
    base="$SOURCE_IMAGE"
  fi
  original_name="$(basename "$SOURCE_PATH")"
  out_jpg="$ALBUM_DIR/$base.jpg"

  if command -v ffmpeg >/dev/null 2>&1; then
    if ffmpeg -loglevel error -y -i "$SOURCE_PATH" "$out_jpg"; then
      SOURCE_PATH="$out_jpg"
      SOURCE_IMAGE="$(basename "$out_jpg")"
      CONVERTED_FROM="$original_name"
      return
    fi
  fi

  if command -v sips >/dev/null 2>&1; then
    if sips --setProperty format jpeg "$SOURCE_PATH" --out "$out_jpg" >/dev/null; then
      SOURCE_PATH="$out_jpg"
      SOURCE_IMAGE="$(basename "$out_jpg")"
      CONVERTED_FROM="$original_name"
      return
    fi
  fi

  echo "ERROR: failed to convert source image to JPG: $SOURCE_PATH" >&2
  exit 4
}

resolve_source_path
if [[ ! -f "$SOURCE_PATH" ]]; then
  if ! recover_source_image_if_missing; then
    if ! try_online_cover_lookup; then
      write_missing_todo "cover_source_missing" "No local image, no recoverable embedded picture, and online lookup failed."
      echo "ERROR: no image source found, local recovery failed, and online lookup failed in: $ALBUM_DIR" >&2
      echo "ERROR: wrote todo file: $MISSING_TODO_PATH" >&2
      exit 4
    fi
  fi
fi
convert_source_to_jpg_if_needed

read_dim() {
  local file="$1"
  if command -v magick >/dev/null 2>&1; then
    magick identify -format "%w %h" "$file"
    return
  fi
  if command -v identify >/dev/null 2>&1; then
    identify -format "%w %h" "$file"
    return
  fi
  if command -v sips >/dev/null 2>&1; then
    local w h
    w=$(sips -g pixelWidth "$file" | awk '/pixelWidth/ {print $2}')
    h=$(sips -g pixelHeight "$file" | awk '/pixelHeight/ {print $2}')
    echo "$w $h"
    return
  fi
  echo "ERROR: no image size tool found (magick/identify/sips)" >&2
  exit 5
}

infer_back_from_existing_jpg() {
  local py candidate

  if [[ -f "$ALBUM_DIR/back.jpg" ]]; then
    return
  fi
  py="$WHITEBULL_DIR/skills/cover-skill/scripts/detect_back_image.py"
  if [[ ! -f "$py" ]]; then
    return
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    return
  fi

  candidate="$(
    python3 "$py" \
      --album-dir "$ALBUM_DIR" \
      --cover-path "$COVER_PATH" \
      --source-path "$SOURCE_PATH" \
      --exclude "cover_org.jpg" \
      --exclude "cover_ori.jpg" \
      --exclude "cover_online.jpg" \
      --exclude "folder.jpg" \
      --min-score 48 \
      --min-delta 12 \
      --plain 2>/dev/null || true
  )"
  candidate="$(printf '%s' "$candidate" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  if [[ -z "$candidate" ]]; then
    return
  fi
  if [[ ! -f "$candidate" ]]; then
    return
  fi

  if cp "$candidate" "$ALBUM_DIR/back.jpg"; then
    BACK_INFERRED_FROM="$(basename "$candidate")"
  fi
}

read -r SRC_W SRC_H <<<"$(read_dim "$SOURCE_PATH")"
if [[ -z "${SRC_W:-}" || -z "${SRC_H:-}" ]]; then
  echo "ERROR: cannot read source dimensions: $SOURCE_PATH" >&2
  exit 6
fi

SRC_MAX=$SRC_W
if (( SRC_H > SRC_MAX )); then
  SRC_MAX=$SRC_H
fi
SRC_MIN=$SRC_W
if (( SRC_H < SRC_MIN )); then
  SRC_MIN=$SRC_H
fi

if (( SRC_MIN < MIN_COVER_SIZE )); then
  if [[ "$RECOVERED_FROM" != "online_lookup" ]]; then
    if try_online_cover_lookup; then
      convert_source_to_jpg_if_needed
      read -r SRC_W SRC_H <<<"$(read_dim "$SOURCE_PATH")"
      SRC_MAX=$SRC_W
      if (( SRC_H > SRC_MAX )); then
        SRC_MAX=$SRC_H
      fi
      SRC_MIN=$SRC_W
      if (( SRC_H < SRC_MIN )); then
        SRC_MIN=$SRC_H
      fi
    fi
  fi
fi

if (( SRC_MIN < MIN_COVER_SIZE )); then
  if [[ -n "$RECOVERED_FROM" ]]; then
    write_missing_todo "cover_too_small" "Recovered image ${SRC_W}x${SRC_H} from ${RECOVERED_FROM} is below ${MIN_COVER_SIZE}x${MIN_COVER_SIZE}."
    echo "ERROR: recovered source is too small (${SRC_W}x${SRC_H}) from ${RECOVERED_FROM}; minimum is ${MIN_COVER_SIZE}x${MIN_COVER_SIZE}" >&2
    echo "ERROR: wrote todo file: $MISSING_TODO_PATH" >&2
  else
    write_missing_todo "cover_too_small" "Source image ${SRC_W}x${SRC_H} is below ${MIN_COVER_SIZE}x${MIN_COVER_SIZE}."
    echo "ERROR: source image too small (${SRC_W}x${SRC_H}); minimum is ${MIN_COVER_SIZE}x${MIN_COVER_SIZE}" >&2
    echo "ERROR: wrote todo file: $MISSING_TODO_PATH" >&2
  fi
  exit 7
fi

cp "$SOURCE_PATH" "$COVER_PATH"

if [[ "$SPLIT_SIDE" == "right" ]]; then
  "$WHITEBULL_DIR/composer/cut-right-cover.sh" "$COVER_PATH"
elif [[ "$SPLIT_SIDE" == "left" ]]; then
  "$WHITEBULL_DIR/composer/cut-right-cover.sh" "$COVER_PATH" left
fi

# Re-evaluate effective source size after optional split/crop.
read -r EFF_W EFF_H <<<"$(read_dim "$COVER_PATH")"
if [[ -z "${EFF_W:-}" || -z "${EFF_H:-}" ]]; then
  echo "ERROR: cannot read effective source dimensions after split: $COVER_PATH" >&2
  exit 8
fi
EFF_MAX=$EFF_W
if (( EFF_H > EFF_MAX )); then
  EFF_MAX=$EFF_H
fi

"$WHITEBULL_DIR/composer/5.5-resize-cover.sh" --size "$TARGET_SIZE" --square "$COVER_PATH"

if [[ ! -f "$COVER_PATH" ]]; then
  echo "ERROR: cover was not generated: $COVER_PATH" >&2
  exit 8
fi

read -r DST_W DST_H <<<"$(read_dim "$COVER_PATH")"
if [[ "$DST_W" != "$DST_H" ]]; then
  echo "ERROR: cover is not square: ${DST_W}x${DST_H}" >&2
  exit 9
fi

if (( DST_W < MIN_COVER_SIZE )); then
  echo "ERROR: final cover too small: ${DST_W}x${DST_H}, minimum is ${MIN_COVER_SIZE}x${MIN_COVER_SIZE}" >&2
  exit 9
fi

if (( EFF_MAX > TARGET_SIZE )); then
  if [[ "$DST_W" != "$TARGET_SIZE" ]]; then
    echo "ERROR: cover size invalid: ${DST_W}x${DST_H}, expected ${TARGET_SIZE}x${TARGET_SIZE} for effective high-res source" >&2
    exit 9
  fi
else
  if (( DST_W > TARGET_SIZE )); then
    echo "ERROR: cover size invalid: ${DST_W}x${DST_H}, should not exceed ${TARGET_SIZE}x${TARGET_SIZE}" >&2
    exit 9
  fi
fi

MIME_TYPE="$(file -b --mime-type "$COVER_PATH" || true)"
if [[ "$MIME_TYPE" != "image/jpeg" ]]; then
  echo "ERROR: cover mime type invalid: $MIME_TYPE (expected image/jpeg)" >&2
  exit 10
fi

infer_back_from_existing_jpg

BACKUPS=()
[[ -f "$ALBUM_DIR/cover_ori.jpg" ]] && BACKUPS+=("cover_ori.jpg")
[[ -f "$ALBUM_DIR/cover_org.jpg" ]] && BACKUPS+=("cover_org.jpg")

printf '{'
printf '"ok":true,'
printf '"album_dir":"%s",' "${ALBUM_DIR//\"/\\\"}"
printf '"source_original":"%s",' "${SOURCE_ORIGINAL//\"/\\\"}"
printf '"source_used":"%s",' "${SOURCE_IMAGE//\"/\\\"}"
printf '"catalog_number":"%s",' "${CATALOG_NUMBER//\"/\\\"}"
printf '"release_id":"%s",' "${RELEASE_ID//\"/\\\"}"
if [[ "$MB_DB_FETCH_ATTEMPTED" -eq 1 ]]; then
  printf '"musicbrainz_db_fetch_attempted":true,'
else
  printf '"musicbrainz_db_fetch_attempted":false,'
fi
if [[ "$MB_DB_FETCH_OK" -eq 1 ]]; then
  printf '"musicbrainz_db_fetch_ok":true,'
else
  printf '"musicbrainz_db_fetch_ok":false,'
fi
printf '"musicbrainz_db_fetch_provider":"%s",' "${MB_DB_FETCH_PROVIDER//\"/\\\"}"
printf '"musicbrainz_db_fetch_expected_file":"%s",' "${MB_DB_FETCH_EXPECTED_FILE//\"/\\\"}"
printf '"musicbrainz_db_fetch_skipped_reason":"%s",' "${MB_DB_FETCH_SKIPPED_REASON//\"/\\\"}"
printf '"musicbrainz_db_fetch_error":"%s",' "${MB_DB_FETCH_ERROR//\"/\\\"}"
printf '"split_side":"%s",' "${SPLIT_SIDE//\"/\\\"}"
printf '"cover_path":"%s",' "${COVER_PATH//\"/\\\"}"
printf '"target_size":%s,' "$TARGET_SIZE"
printf '"min_cover_size":%s,' "$MIN_COVER_SIZE"
printf '"width":%s,' "$DST_W"
printf '"height":%s,' "$DST_H"
printf '"mime":"%s",' "${MIME_TYPE//\"/\\\"}"
if [[ -f "$ALBUM_DIR/back.jpg" ]]; then
  printf '"back_path":"%s",' "${ALBUM_DIR//\"/\\\"}/back.jpg"
else
  printf '"back_path":null,'
fi
if [[ -n "$BACK_INFERRED_FROM" ]]; then
  printf '"back_inferred_from":"%s",' "${BACK_INFERRED_FROM//\"/\\\"}"
else
  printf '"back_inferred_from":null,'
fi
if [[ -n "$CONVERTED_FROM" ]]; then
  printf '"converted_from":"%s",' "${CONVERTED_FROM//\"/\\\"}"
else
  printf '"converted_from":null,'
fi
if [[ -n "$RECOVERED_FROM" ]]; then
  printf '"recovered_from":"%s",' "${RECOVERED_FROM//\"/\\\"}"
else
  printf '"recovered_from":null,'
fi
if [[ -s "$ONLINE_RECOVER_META_PATH" ]]; then
  printf '"online_meta_path":"%s",' "${ONLINE_RECOVER_META_PATH//\"/\\\"}"
else
  printf '"online_meta_path":null,'
fi
printf '"backup_files":['
for i in "${!BACKUPS[@]}"; do
  if (( i > 0 )); then
    printf ','
  fi
  printf '"%s"' "${BACKUPS[$i]//\"/\\\"}"
done
printf ']'
printf '}\n'
