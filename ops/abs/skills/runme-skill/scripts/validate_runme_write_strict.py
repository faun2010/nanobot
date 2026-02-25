#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:
    from canonicalize_work_from_imslp import (
        can_accept as imslp_can_accept,
        load_catalog_works as imslp_load_catalog_works,
        normalize_titles_for_runme as imslp_normalize_titles_for_runme,
        rank_works as imslp_rank_works,
    )
except Exception:
    imslp_can_accept = None
    imslp_load_catalog_works = None
    imslp_normalize_titles_for_runme = None
    imslp_rank_works = None


WRITE_KEYS = ["Composer", "Album", "Genre", "Titles"]
SHOW_KEYS = ["Solo", "Conductor", "Orchestra", "Year", "Tail"]
INFO_KEYS = ["Art", "Release", "Box"]
MANAGED_KEYS = WRITE_KEYS + SHOW_KEYS + INFO_KEYS

AUDIO_EXTS = {".flac", ".dsf", ".wv", ".ape", ".wav", ".aiff", ".aif"}
VALID_GENRES = {
    "Ballet",
    "Cantata",
    "Chamber",
    "Choral",
    "Concerto",
    "Film - Theatre - Radio",
    "Instrumental",
    "Keyboard",
    "Opera",
    "Quartet",
    "Symphonic",
    "Vocal",
    "Guitar",
}

PLACEHOLDER_EMPTY = {"", "-", "unknown", "Unknown", "n/a", "N/A"}
ALBUM_PLACEHOLDER = {"", "-", "Symphony", "unknown", "Unknown"}
ENSEMBLE_ROLE_HINTS = (
    "orchestra",
    "quartet",
    "quartetto",
    "quartett",
    "quatuor",
    "quintet",
    "quintetto",
    "quintett",
    "quintette",
    "trio",
    "trio sonata",
    "octet",
    "octetto",
    "octett",
    "ensemble",
    "choir",
    "chorus",
    "band",
    "consort",
)

# User rule: only chamber/solo/concerto-type works should use Solo as version anchor.
SOLO_PRESERVE_GENRES = {
    "Chamber",
    "Quartet",
    "Concerto",
    "Keyboard",
    "Guitar",
    "Instrumental",
    "Vocal",
}

CONDUCTOR_ROLE_HINTS = (
    "conductor",
    "conducted",
    "dirigent",
    "direction",
    "maestro",
    "chef",
)

BALLET_ALBUM_HINTS = (
    "sleeping beauty",
    "swan lake",
    "nutcracker",
    "coppelia",
    "giselle",
    "la bayadere",
    "romeo and juliet",
    "romeo et juliette",
    "firebird",
    "petrouchka",
    "rite of spring",
    "daphnis et chloe",
    "cinderella",
)

BALLET_TRACK_HINTS = (
    "act i",
    "act ii",
    "act iii",
    "act iv",
    "pas de",
    "variation",
    "coda",
    "apotheose",
    "apotheosis",
    "entracte",
    "scene dansante",
    "valse",
    "marche",
    "polacca",
    "sarabande",
    "farandole",
    "panorama",
    "waltz",
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Strictly normalize and validate runme write/show/info fields.")
    p.add_argument("--runme", required=True, help="Path to runme file")
    p.add_argument("--work-dir", required=True, help="Work directory containing split audio tracks")
    p.add_argument("--album-dir", required=True, help="Album root directory containing metadata json/db")
    p.add_argument("--json", action="store_true", help="Print JSON result")
    return p.parse_args()


def normalize_text(value: str, *, allow_semicolon: bool = False) -> str:
    v = (value or "").replace("\r", " ").replace("\n", " ").strip()
    v = v.replace('"', "'")
    v = v.replace("“", "'").replace("”", "'").replace("’", "'")
    v = v.replace("«", "'").replace("»", "'")
    v = v.replace("/", "-")
    if not allow_semicolon:
        v = v.replace(";", ",")
    v = re.sub(r"\s+", " ", v)
    v = re.sub(r"\s*,\s*", ", ", v)
    v = re.sub(r"\s+\|\s+", " | ", v)
    return v.strip(" ,;")


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


def is_empty_like(value: str) -> bool:
    return normalize_text(value).lower() in {x.lower() for x in PLACEHOLDER_EMPTY}


def is_album_placeholder(value: str) -> bool:
    return normalize_text(value).lower() in {x.lower() for x in ALBUM_PLACEHOLDER}


def looks_like_composer(value: str) -> bool:
    v = normalize_text(value, allow_semicolon=True)
    if not v:
        return False
    if v.startswith("_"):
        return False
    low = v.lower()
    if "tmp" in low:
        return False
    if low in {x.lower() for x in VALID_GENRES}:
        return False
    if low in {"abs_src", "music", "various", "cd"}:
        return False
    if re.search(r"\d", v):
        return False
    letters = re.sub(r"[^A-Za-z]", "", v)
    return len(letters) >= 3


def year_from_text(value: str) -> str:
    m = re.search(r"(18|19|20)\d{2}", value or "")
    if not m:
        return ""
    y = int(m.group(0))
    if 1935 <= y <= 2050:
        return str(y)
    return ""


def run_capture(cmd: List[str], cwd: Optional[Path] = None) -> Tuple[int, str]:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout


def read_first_flac_tags(work_dir: Path) -> Dict[str, str]:
    flacs = sorted([p for p in work_dir.iterdir() if p.is_file() and p.suffix.lower() == ".flac" and not p.name.startswith(".")])
    if not flacs:
        return {}
    rc, out = run_capture(["metaflac", "--export-tags-to=-", str(flacs[0])])
    if rc != 0:
        return {}
    tags: Dict[str, str] = {}
    for line in out.splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        ku = k.strip().upper()
        vv = normalize_text(v.strip(), allow_semicolon=True)
        if ku and ku not in tags and vv:
            tags[ku] = vv
    return tags


def read_album_meta(album_dir: Path) -> Dict[str, str]:
    out: Dict[str, str] = {"provider": "", "release_id": "", "title": "", "year": ""}
    for provider in ("musicbrainz", "discogs"):
        for fn in (f"{provider}_0.db", f"{provider}_0.json"):
            p = album_dir / fn
            if not p.exists():
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            release_id = normalize_text(str(data.get("id", "")))
            title = normalize_text(str(data.get("title", "")), allow_semicolon=True)
            year = ""
            for key in ("date", "released", "year"):
                raw = str(data.get(key, ""))
                year = year_from_text(raw)
                if year:
                    break
            out = {
                "provider": provider,
                "release_id": release_id,
                "title": title,
                "year": year,
            }
            return out
    return out


def clean_album_dir_title(name: str) -> str:
    v = normalize_text(name, allow_semicolon=True)
    v = re.sub(r"^\[[^\]]+\]\s*", "", v)
    v = re.sub(r"^CD\s*[0-9A-Za-z-]+\s+", "", v, flags=re.IGNORECASE)
    return v.strip()


def infer_composer_from_album_dir(album_dir: Path) -> str:
    base = clean_album_dir_title(album_dir.name)
    if " - " in base:
        left = normalize_text(base.split(" - ", 1)[0], allow_semicolon=True)
        if looks_like_composer(left):
            return left
    return ""


def infer_album_from_dir(album_dir: Path) -> str:
    base = clean_album_dir_title(album_dir.name)
    if " - " in base:
        right = normalize_text(base.split(" - ", 1)[1], allow_semicolon=True)
        if right:
            return right
    return base


def looks_like_ballet(album_value: str, titles: List[str]) -> bool:
    low_album = normalize_text(album_value, allow_semicolon=True).lower()
    if "ballet" in low_album:
        return True
    if any(h in low_album for h in BALLET_ALBUM_HINTS):
        return True

    title_low = [normalize_text(t, allow_semicolon=False).lower() for t in titles if normalize_text(t, allow_semicolon=False)]
    if not title_low:
        return False
    if any(any(h in t for h in BALLET_ALBUM_HINTS) for t in title_low):
        return True
    act_count = sum(1 for t in title_low if re.search(r"\bact\s*(i|ii|iii|iv|\d+)\b", t))
    dance_hits = 0
    text_blob = ";".join(title_low)
    for hint in BALLET_TRACK_HINTS:
        if hint in text_blob:
            dance_hits += 1
    return act_count >= 2 and dance_hits >= 3


def infer_genre(album_value: str, existing: str, titles: List[str]) -> str:
    g = normalize_text(existing, allow_semicolon=True)
    low = (album_value or "").lower()
    if looks_like_ballet(album_value, titles):
        return "Ballet"
    if "quartet" in low:
        return "Quartet"
    if "guitar" in low or "lute" in low or "vihuela" in low:
        return "Guitar"
    if any(k in low for k in ("sonata", "trio", "quintet", "octet")):
        return "Chamber"
    if any(k in low for k in ("piano", "keyboard", "klavier")):
        return "Keyboard"
    if "concerto" in low:
        return "Concerto"
    if "requiem" in low:
        return "Choral"
    if g in VALID_GENRES:
        return g
    return "Symphonic"


def genre_allows_solo_anchor(genre: str) -> bool:
    g = normalize_text(genre, allow_semicolon=True)
    return g in SOLO_PRESERVE_GENRES


def enforce_imslp_album_guard(
    *,
    whitebull_dir: Path,
    composer: str,
    album: str,
    titles: List[str],
) -> Dict[str, str]:
    out: Dict[str, str] = {
        "ok": "false",
        "catalog": "",
        "canonical_composer": "",
        "expected_album": "",
        "expected_genre": "",
        "error": "",
    }

    if not composer:
        out["error"] = "IMSLP album guard: Composer is empty."
        return out
    if not album:
        out["error"] = "IMSLP album guard: Album is empty."
        return out
    if (
        imslp_load_catalog_works is None
        or imslp_rank_works is None
        or imslp_can_accept is None
        or imslp_normalize_titles_for_runme is None
    ):
        out["error"] = "IMSLP album guard: canonicalize module import failed."
        return out

    catalog, canonical_composer, works = imslp_load_catalog_works(whitebull_dir, composer)
    out["catalog"] = catalog
    out["canonical_composer"] = (canonical_composer or "").strip()

    if catalog != "imslp" or not works:
        out["error"] = f"IMSLP album guard: composer db not found for '{composer}'."
        return out

    source_titles = imslp_normalize_titles_for_runme(titles)
    ranked = imslp_rank_works(works, album_hint=album, source_titles=source_titles)
    if not ranked:
        out["error"] = f"IMSLP album guard: no rankable works for '{composer}'."
        return out

    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    if not imslp_can_accept(best, second):
        out["error"] = (
            "IMSLP album guard: best candidate confidence too low "
            f"(score={best.score:.3f}) for composer '{composer}'."
        )
        return out

    expected_album = (best.row.title or "").strip()
    expected_genre = (best.row.genre or "").strip()
    title_set = {(w.title or "").strip() for w in works if (w.title or "").strip()}
    if not expected_album or expected_album not in title_set:
        out["error"] = "IMSLP album guard: canonical title resolution failed."
        return out
    if album.strip() not in title_set:
        # Mandatory publish fence: album must exist in the composer IMSLP title list.
        # We still return the expected title so caller can deterministically correct runme.
        out["error"] = (
            f"IMSLP album guard: Album '{album}' not found in composer db titles; "
            f"expected '{expected_album}'."
        )
        out["expected_album"] = expected_album
        out["expected_genre"] = expected_genre
        return out

    out["ok"] = "true"
    out["expected_album"] = expected_album
    out["expected_genre"] = expected_genre
    return out


def discover_tracks(work_dir: Path) -> List[Tuple[int, Path, str]]:
    rows: List[Tuple[int, Path, str]] = []
    fallback_no = 10000
    for p in sorted(work_dir.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() not in AUDIO_EXTS:
            continue
        m = re.match(r"^(\d{1,3})\s*-\s*(.+)$", p.stem)
        if m:
            no = int(m.group(1))
            title = normalize_text(m.group(2), allow_semicolon=False)
        else:
            no = fallback_no
            fallback_no += 1
            title = normalize_text(p.stem, allow_semicolon=False)
        rows.append((no, p, title))
    rows.sort(key=lambda x: (x[0], x[1].name.lower()))
    return rows


def read_flac_title(flac: Path) -> str:
    if flac.suffix.lower() != ".flac":
        return ""
    rc, out = run_capture(["metaflac", "--show-tag=TITLE", str(flac)])
    if rc != 0:
        return ""
    for line in out.splitlines():
        if line.startswith("TITLE="):
            return normalize_text(line.split("=", 1)[1], allow_semicolon=False)
    return ""


def split_titles(raw: str) -> List[str]:
    parts = [normalize_text(x, allow_semicolon=False) for x in (raw or "").split(";")]
    return [p for p in parts if p]


def resolve_titles(existing: str, tracks: List[Tuple[int, Path, str]]) -> List[str]:
    existing_parts = split_titles(existing)
    track_count = len(tracks)
    if track_count <= 0:
        return existing_parts
    if len(existing_parts) == track_count and all(existing_parts):
        return existing_parts

    derived: List[str] = []
    for _, p, title_from_name in tracks:
        title = read_flac_title(p) or title_from_name
        title = normalize_text(title, allow_semicolon=False)
        if not title:
            title = normalize_text(p.stem, allow_semicolon=False)
        derived.append(title or "Unknown")
    if len(derived) == track_count and all(derived):
        return derived
    return existing_parts[:track_count]


def normalize_people_field(value: str, *, empty_value: str) -> str:
    raw = normalize_text(value, allow_semicolon=True)
    if not raw:
        return empty_value
    tokens = re.split(r"[;|]", raw)
    uniq: "OrderedDict[str, None]" = OrderedDict()
    for t in tokens:
        tc = normalize_text(t, allow_semicolon=False)
        if not tc or tc == "-":
            continue
        key = tc.casefold()
        if key not in uniq:
            uniq[tc] = None
    if not uniq:
        return empty_value
    return "; ".join(uniq.keys())


def looks_like_ensemble_name(name: str) -> bool:
    low = normalize_text(name, allow_semicolon=True).lower()
    if not low:
        return False
    return any(hint in low for hint in ENSEMBLE_ROLE_HINTS)


def extract_ensemble_from_tail(tail: str) -> str:
    raw = normalize_text(tail, allow_semicolon=True)
    if not raw:
        return ""
    uniq: "OrderedDict[str, None]" = OrderedDict()
    for token in re.split(r"[;,]", raw):
        t = normalize_text(token, allow_semicolon=True)
        if not t:
            continue
        m = re.match(r"^(.*?)\(([^()]*)\)\s*$", t)
        if m:
            name = normalize_text(m.group(1), allow_semicolon=False)
            role = normalize_text(m.group(2), allow_semicolon=True).lower()
            if name and any(hint in role for hint in ENSEMBLE_ROLE_HINTS):
                uniq[name] = None
            continue
        if looks_like_ensemble_name(t):
            uniq[t] = None
    if not uniq:
        return ""
    return next(iter(uniq.keys()))


def extract_conductor_from_tail(tail: str, *, solo: str, orchestra: str) -> str:
    raw = normalize_text(tail, allow_semicolon=True)
    if not raw:
        return ""

    excluded: set[str] = set()
    for token in re.split(r"[;|]", normalize_text(orchestra, allow_semicolon=True)):
        t = normalize_text(token, allow_semicolon=False)
        if t:
            excluded.add(t.casefold())
    for token in re.split(r"[;|]", normalize_text(solo, allow_semicolon=True)):
        t = normalize_text(token, allow_semicolon=False)
        if t:
            excluded.add(t.casefold())

    for token in re.split(r"[;,]", raw):
        t = normalize_text(token, allow_semicolon=True)
        if not t:
            continue

        m = re.match(r"^(.*?)\(([^()]*)\)\s*$", t)
        if m:
            name = normalize_text(m.group(1), allow_semicolon=False)
            role = normalize_text(m.group(2), allow_semicolon=True).lower()
            if not name:
                continue
            if any(hint in role for hint in CONDUCTOR_ROLE_HINTS):
                if name.casefold() not in excluded and not looks_like_ensemble_name(name):
                    return name
            continue

        if looks_like_ensemble_name(t):
            continue
        if t.casefold() in excluded:
            continue
        if t == "-":
            continue
        # Tail in orchestral albums is commonly "Conductor, Orchestra, Soloists".
        return t
    return ""


def pick_preferred_performer(
    *,
    solo: str,
    orchestra: str,
    conductor: str,
    tail: str,
    album: str,
    genre: str,
) -> str:
    album_low = normalize_text(album, allow_semicolon=True).lower()
    prefer_ensemble = (
        genre == "Quartet"
        or "quartet" in album_low
        or "quintet" in album_low
        or "trio" in album_low
        or "duo" in album_low
        or "octet" in album_low
    )

    orch_tokens = [
        normalize_text(x, allow_semicolon=False)
        for x in re.split(r"[;|]", normalize_text(orchestra, allow_semicolon=True))
        if normalize_text(x, allow_semicolon=False)
    ]
    if prefer_ensemble:
        for cand in orch_tokens:
            if looks_like_ensemble_name(cand):
                return cand
        # User rule for chamber ensembles: if Orchestra exists, prioritize it over principal soloist.
        if orch_tokens:
            return orch_tokens[0]
        tail_ensemble = extract_ensemble_from_tail(tail)
        if tail_ensemble:
            return tail_ensemble
    if solo and solo != "-":
        return solo
    if conductor and conductor != "-":
        return conductor
    if orch_tokens:
        return orch_tokens[0]
    return solo


def normalize_release(value: str) -> str:
    v = normalize_text(value, allow_semicolon=True)
    return v.replace(" ", "")


def format_assignment(key: str, value: str) -> str:
    if key == "Year":
        return f"{key}={value}"
    safe = (value or "").replace('"', "'")
    return f'{key}="{safe}"'


def rewrite_runme(
    lines: List[str],
    values: Dict[str, str],
    occurrences: Dict[str, List[Tuple[int, str]]],
) -> Tuple[List[str], List[str], List[str]]:
    removed_dup: List[str] = []
    inserted_missing: List[str] = []
    seen: set[str] = set()
    out: List[str] = []

    for line in lines:
        parsed = parse_assignment(line)
        if not parsed:
            out.append(line)
            continue
        key, _ = parsed
        if key not in MANAGED_KEYS:
            out.append(line)
            continue
        if key in seen:
            if key not in removed_dup:
                removed_dup.append(key)
            continue
        out.append(format_assignment(key, values.get(key, "")))
        seen.add(key)

    insert_at = len(out)
    for i, line in enumerate(out):
        if re.match(r"^\s*p1=", line):
            insert_at = i
            break

    for key in MANAGED_KEYS:
        if key in seen:
            continue
        out.insert(insert_at, format_assignment(key, values.get(key, "")))
        insert_at += 1
        inserted_missing.append(key)

    return out, removed_dup, inserted_missing


def main() -> int:
    args = parse_args()
    runme_path = Path(args.runme).resolve()
    work_dir = Path(args.work_dir).resolve()
    album_dir = Path(args.album_dir).resolve()

    result: Dict[str, object] = {
        "ok": False,
        "runme_path": str(runme_path),
        "work_dir": str(work_dir),
        "album_dir": str(album_dir),
        "track_count": 0,
        "title_count": 0,
        "corrected_fields": [],
        "removed_duplicate_keys": [],
        "inserted_missing_keys": [],
        "errors": [],
        "warnings": [],
        "values": {},
        "imslp_guard": {},
    }

    if not runme_path.exists():
        result["errors"].append(f"runme file not found: {runme_path}")
        print(json.dumps(result, ensure_ascii=False))
        return 4
    if not work_dir.is_dir():
        result["errors"].append(f"work dir not found: {work_dir}")
        print(json.dumps(result, ensure_ascii=False))
        return 4
    if not album_dir.is_dir():
        result["errors"].append(f"album dir not found: {album_dir}")
        print(json.dumps(result, ensure_ascii=False))
        return 4

    original_lines = runme_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    occurrences: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    for idx, line in enumerate(original_lines):
        parsed = parse_assignment(line)
        if not parsed:
            continue
        key, val = parsed
        if key in MANAGED_KEYS:
            occurrences[key].append((idx, val))

    current: Dict[str, str] = {}
    for key in MANAGED_KEYS:
        if occurrences.get(key):
            current[key] = occurrences[key][0][1]
        else:
            current[key] = ""

    tracks = discover_tracks(work_dir)
    track_count = len(tracks)
    result["track_count"] = track_count
    tags = read_first_flac_tags(work_dir)
    meta = read_album_meta(album_dir)

    composer = normalize_text(current.get("Composer", ""), allow_semicolon=True)
    if is_empty_like(composer) or not looks_like_composer(composer):
        composer = normalize_text(tags.get("COMPOSER", ""), allow_semicolon=True)
    if is_empty_like(composer) or not looks_like_composer(composer):
        composer = normalize_text(tags.get("ARTIST", ""), allow_semicolon=True)
    if is_empty_like(composer) or not looks_like_composer(composer):
        composer = infer_composer_from_album_dir(album_dir)

    album = normalize_text(current.get("Album", ""), allow_semicolon=True)
    if is_album_placeholder(album):
        album = normalize_text(tags.get("ALBUM", ""), allow_semicolon=True)
    if is_album_placeholder(album):
        album = normalize_text(meta.get("title", ""), allow_semicolon=True)
    if is_album_placeholder(album):
        album = infer_album_from_dir(album_dir)

    titles_list = resolve_titles(current.get("Titles", ""), tracks)
    titles_value = ";".join(titles_list)
    album_before_imslp = album
    whitebull_dir = Path(__file__).resolve().parents[3]
    imslp_guard = enforce_imslp_album_guard(
        whitebull_dir=whitebull_dir,
        composer=composer,
        album=album,
        titles=titles_list,
    )
    result["imslp_guard"] = imslp_guard
    imslp_guard_error = ""
    imslp_expected_album = (imslp_guard.get("expected_album") or "").strip()
    imslp_expected_genre = (imslp_guard.get("expected_genre") or "").strip()
    imslp_canonical_composer = (imslp_guard.get("canonical_composer") or "").strip()

    if imslp_canonical_composer and (is_empty_like(composer) or not looks_like_composer(composer)):
        composer = imslp_canonical_composer
    if imslp_expected_album and album.strip() != imslp_expected_album:
        album = imslp_expected_album
    if (imslp_guard.get("ok") or "").strip().lower() != "true":
        imslp_guard_error = (imslp_guard.get("error") or "").strip()

    genre = infer_genre(album, current.get("Genre", ""), titles_list)
    if imslp_expected_genre in VALID_GENRES:
        genre = imslp_expected_genre

    solo = normalize_people_field(current.get("Solo", ""), empty_value="-")
    conductor = normalize_people_field(current.get("Conductor", ""), empty_value="-")
    orchestra = normalize_people_field(current.get("Orchestra", ""), empty_value="")

    year = year_from_text(str(current.get("Year", "")))
    if not year:
        year = year_from_text(tags.get("DATE", "")) or year_from_text(tags.get("YEAR", ""))
    if not year:
        year = year_from_text(str(meta.get("year", "")))
    if not year:
        year = year_from_text(album_dir.name)

    tail = normalize_text(current.get("Tail", ""), allow_semicolon=True)
    if not tail:
        pieces = []
        for s in (conductor, orchestra, solo):
            if s and s != "-":
                pieces.append(s)
        if pieces:
            uniq: "OrderedDict[str, None]" = OrderedDict()
            for p in pieces:
                uniq[p] = None
            tail = ", ".join(uniq.keys())

    if conductor == "-" or is_empty_like(conductor):
        tag_conductor = normalize_people_field(tags.get("CONDUCTOR", ""), empty_value="-")
        if tag_conductor != "-":
            conductor = tag_conductor
    if conductor == "-" or is_empty_like(conductor):
        inferred_conductor = extract_conductor_from_tail(tail, solo=solo, orchestra=orchestra)
        if inferred_conductor:
            conductor = inferred_conductor

    extra_warnings: List[str] = []

    if genre_allows_solo_anchor(genre):
        solo = pick_preferred_performer(
            solo=solo,
            orchestra=orchestra,
            conductor=conductor,
            tail=tail,
            album=album,
            genre=genre,
        )
    else:
        # User hard rule: orchestral/non-solo works must not carry a Solo anchor.
        solo = "-"
        if conductor == "-" or is_empty_like(conductor):
            inferred_conductor = extract_conductor_from_tail(tail, solo=solo, orchestra=orchestra)
            if inferred_conductor:
                conductor = inferred_conductor
        if conductor == "-" or is_empty_like(conductor):
            extra_warnings.append("Conductor missing for non chamber/solo/concerto work; version anchor may be weak.")

    art = normalize_text(current.get("Art", ""), allow_semicolon=True) or "cover.jpg"
    release = normalize_release(current.get("Release", ""))
    if not release:
        release = normalize_release(str(meta.get("release_id", "")))
    box = normalize_text(current.get("Box", ""), allow_semicolon=True)

    canonical: Dict[str, str] = {
        "Composer": composer,
        "Album": album,
        "Genre": genre,
        "Titles": titles_value,
        "Solo": solo,
        "Conductor": conductor,
        "Orchestra": orchestra,
        "Year": year,
        "Tail": tail,
        "Art": art,
        "Release": release,
        "Box": box,
    }

    errors: List[str] = []
    warnings: List[str] = []

    if imslp_guard_error:
        errors.append(imslp_guard_error)
    if album_before_imslp.strip() and album_before_imslp.strip() != canonical["Album"].strip():
        warnings.append(
            "Album canonicalized by IMSLP guard: "
            f"'{album_before_imslp.strip()}' -> '{canonical['Album'].strip()}'."
        )

    if track_count <= 0:
        errors.append("No audio track files found in work directory.")

    title_count = len(titles_list)
    result["title_count"] = title_count
    if track_count > 0 and title_count != track_count:
        errors.append(f"Titles count mismatch: titles={title_count}, tracks={track_count}")

    if is_empty_like(canonical["Composer"]) or not looks_like_composer(canonical["Composer"]):
        errors.append("Composer is empty or invalid after correction.")
    if is_album_placeholder(canonical["Album"]):
        errors.append("Album is empty/placeholder after correction.")
    if canonical["Genre"] not in VALID_GENRES:
        errors.append(f"Genre is invalid after correction: {canonical['Genre']}")
    if not year_from_text(canonical["Year"]):
        errors.append(f"Year is invalid after correction: {canonical['Year']}")

    for key in MANAGED_KEYS:
        if len(occurrences.get(key, [])) > 1:
            warnings.append(f"Duplicate key found and will be deduplicated: {key}")
    warnings.extend(extra_warnings)

    rewritten_lines, removed_dup, inserted_missing = rewrite_runme(original_lines, canonical, occurrences)

    corrected_fields: List[str] = []
    for key in MANAGED_KEYS:
        before = normalize_text(current.get(key, ""), allow_semicolon=True)
        after = normalize_text(canonical.get(key, ""), allow_semicolon=True)
        if key == "Year":
            before = current.get(key, "").strip()
            after = canonical.get(key, "").strip()
        if before != after:
            corrected_fields.append(key)

    changed_content = "\n".join(rewritten_lines).rstrip() + "\n"
    original_content = "\n".join(original_lines).rstrip() + "\n"
    if changed_content != original_content:
        runme_path.write_text(changed_content, encoding="utf-8")

    result["ok"] = len(errors) == 0
    result["corrected_fields"] = corrected_fields
    result["removed_duplicate_keys"] = removed_dup
    result["inserted_missing_keys"] = inserted_missing
    result["errors"] = errors
    result["warnings"] = warnings
    result["values"] = canonical

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
