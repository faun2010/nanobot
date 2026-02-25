#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Final pre-publish exact guard: Composer must exactly match IMSLP complete_name, "
            "and Album must exactly match one work title for that composer."
        )
    )
    p.add_argument("--runme", required=True, help="Path to runme file")
    p.add_argument("--whitebull-dir", default="", help="WhiteBull root path (defaults to script parents)")
    p.add_argument("--json", action="store_true", help="Print JSON result")
    return p.parse_args()


def parse_assignment(line: str) -> Optional[Tuple[str, str]]:
    m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
    if not m:
        return None
    key, raw = m.group(1), m.group(2).strip()
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        val = raw[1:-1]
    else:
        val = raw.split("#", 1)[0].strip()
    return key, val


def load_runme_fields(runme_path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in runme_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parsed = parse_assignment(line)
        if not parsed:
            continue
        key, val = parsed
        out[key] = val
    return out


def load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_payload(runme_path: Path) -> Dict[str, object]:
    return {
        "ok": False,
        "runme": str(runme_path),
        "composer": "",
        "album": "",
        "matched_db_files": [],
        "matched_composer_complete_name": "",
        "matched_title": "",
        "error": "",
        "suggestions": {
            "composer_complete_name": [],
            "album_title": [],
        },
    }


def main() -> int:
    args = parse_args()
    runme_path = Path(args.runme).expanduser().resolve()
    whitebull_dir = (
        Path(args.whitebull_dir).expanduser().resolve()
        if args.whitebull_dir
        else Path(__file__).resolve().parents[3]
    )
    imslp_dir = whitebull_dir / "imslp"

    payload = build_payload(runme_path)

    if not runme_path.exists():
        payload["error"] = f"runme not found: {runme_path}"
        print(json.dumps(payload, ensure_ascii=False))
        return 4
    if not imslp_dir.is_dir():
        payload["error"] = f"imslp dir not found: {imslp_dir}"
        print(json.dumps(payload, ensure_ascii=False))
        return 4

    fields = load_runme_fields(runme_path)
    composer = (fields.get("Composer") or "").strip()
    album = (fields.get("Album") or "").strip()
    payload["composer"] = composer
    payload["album"] = album

    if not composer:
        payload["error"] = "Composer is empty in runme."
        print(json.dumps(payload, ensure_ascii=False))
        return 4
    if not album:
        payload["error"] = "Album is empty in runme."
        print(json.dumps(payload, ensure_ascii=False))
        return 4

    all_complete_names: List[str] = []
    exact_complete_entries: List[Tuple[Path, str, List[str]]] = []
    short_name_only_complete_names: List[str] = []

    for db_path in sorted(imslp_dir.glob("abs_*_db.json")):
        data = load_json(db_path)
        if not data:
            continue
        for comp in data.get("composers") or []:
            complete_name = (comp.get("complete_name") or "").strip()
            short_name = (comp.get("name") or "").strip()
            if complete_name:
                all_complete_names.append(complete_name)
            works = comp.get("works") or []
            titles = [(w.get("title") or "").strip() for w in works if (w.get("title") or "").strip()]
            if not titles:
                continue
            if complete_name and composer == complete_name:
                exact_complete_entries.append((db_path, complete_name, titles))
            elif short_name and composer == short_name and complete_name:
                short_name_only_complete_names.append(complete_name)

    if not exact_complete_entries:
        if short_name_only_complete_names:
            uniq = sorted(set(short_name_only_complete_names))
            payload["error"] = (
                f"Composer '{composer}' matches short name only. "
                "Composer must exactly equal complete_name."
            )
            payload["suggestions"]["composer_complete_name"] = uniq[:8]
        else:
            close = difflib.get_close_matches(composer, sorted(set(all_complete_names)), n=8, cutoff=0.55)
            payload["error"] = (
                f"Composer '{composer}' does not exactly match any IMSLP complete_name. "
                "Composer must be an exact full-name match."
            )
            payload["suggestions"]["composer_complete_name"] = close
        print(json.dumps(payload, ensure_ascii=False))
        return 4

    merged_titles: Dict[str, None] = {}
    matched_files: List[str] = []
    matched_complete_name = exact_complete_entries[0][1]
    for db_path, complete_name, titles in exact_complete_entries:
        matched_complete_name = complete_name
        matched_files.append(str(db_path))
        for t in titles:
            merged_titles[t] = None

    title_set = set(merged_titles.keys())
    payload["matched_db_files"] = matched_files
    payload["matched_composer_complete_name"] = matched_complete_name

    if album not in title_set:
        close_titles = difflib.get_close_matches(album, sorted(title_set), n=8, cutoff=0.45)
        payload["error"] = (
            f"Album '{album}' not found in IMSLP titles for composer '{matched_complete_name}'. "
            "Album must be an exact title match."
        )
        payload["suggestions"]["album_title"] = close_titles
        print(json.dumps(payload, ensure_ascii=False))
        return 4

    payload["ok"] = True
    payload["matched_title"] = album
    payload["error"] = ""
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

