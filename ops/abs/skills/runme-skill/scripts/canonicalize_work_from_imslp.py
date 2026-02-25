#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


AUDIO_EXTS = {".flac", ".ape", ".wav", ".wv", ".aiff", ".aif", ".dsf"}
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

FORM_KEYWORDS = {
    "concerto",
    "sonata",
    "symphony",
    "quartet",
    "quintet",
    "trio",
    "suite",
    "mass",
    "requiem",
    "opera",
    "cantata",
    "oratorio",
    "etude",
    "prelude",
    "fugue",
    "variation",
    "rhapsody",
}

BALLET_HINTS = {
    "sleeping beauty",
    "swan lake",
    "nutcracker",
    "giselle",
    "cinderella",
    "firebird",
    "petrouchka",
    "romeo and juliet",
    "romeo et juliette",
}


@dataclass
class WorkRow:
    title: str
    alttitle: str
    subtitle: str
    genre: str


@dataclass
class RankedWork:
    row: WorkRow
    score: float
    title_score: float
    token_score: float
    movement_score: float
    matched_subtitles: int


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Canonicalize runme work title/genre/titles by IMSLP catalog matching.")
    p.add_argument("--runme", required=True, help="Path to runme file")
    p.add_argument("--work-dir", required=True, help="Work directory with split tracks")
    p.add_argument("--album-dir", required=True, help="Album root directory")
    p.add_argument("--whitebull-dir", default="", help="WhiteBull project root")
    p.add_argument("--json", action="store_true", help="Print JSON output")
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
    fields: Dict[str, str] = {}
    for line in runme_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parsed = parse_assignment(line)
        if not parsed:
            continue
        key, value = parsed
        fields[key] = value
    return fields


def write_runme_fields(runme_path: Path, updates: Dict[str, str]) -> List[str]:
    if not updates:
        return []
    content = runme_path.read_text(encoding="utf-8")
    changed: List[str] = []
    updated = content
    for key, value in updates.items():
        safe = (value or "").replace('"', "'").strip()
        repl = f'{key}="{safe}"'
        pattern = re.compile(rf"^{re.escape(key)}=.*$", flags=re.MULTILINE)
        current = None
        m = pattern.search(updated)
        if m:
            current_line = m.group(0)
            parsed = parse_assignment(current_line)
            if parsed:
                current = parsed[1].strip()
            if current == safe:
                continue
            updated = pattern.sub(repl, updated, count=1)
            changed.append(key)
        else:
            if not updated.endswith("\n"):
                updated += "\n"
            updated += repl + "\n"
            changed.append(key)
    if updated != content:
        runme_path.write_text(updated, encoding="utf-8")
    return changed


def normalize_text(value: str) -> str:
    s = unicodedata.normalize("NFKD", value or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokenize(value: str) -> set[str]:
    return {t for t in normalize_text(value).split() if t}


def text_similarity(a: str, b: str) -> float:
    na = normalize_text(a)
    nb = normalize_text(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(a=na, b=nb).ratio()


def jaccard_similarity(a: str, b: str) -> float:
    sa = tokenize(a)
    sb = tokenize(b)
    if not sa or not sb:
        return 0.0
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)


def extract_opus(value: str) -> str:
    m = re.search(r"\bop\.?\s*([0-9]+(?:[._/-][0-9]+)?)\b", value or "", flags=re.IGNORECASE)
    return m.group(1).lower() if m else ""


def extract_work_no(value: str) -> str:
    m = re.search(r"(?:\bno\.?\s*|#\s*)([0-9]+)\b", value or "", flags=re.IGNORECASE)
    return m.group(1) if m else ""


def split_titles(raw: str) -> List[str]:
    parts = [x.strip() for x in (raw or "").split(";")]
    return [p for p in parts if p]


def strip_work_prefix_for_movement(title: str) -> str:
    text = (title or "").strip()
    if ":" in text:
        right = text.split(":", 1)[1].strip()
        if right:
            return right
    # Handle patterns like "No.1 Allegro ..." without colon.
    text = re.sub(
        r"^(?:concerto|sonata|symphony|quartet|quintet|trio|suite)\s*(?:no\.?|#)?\s*\d+\s*[-,]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    return text


def clean_track_title_from_name(stem: str) -> str:
    m = re.match(r"^\d{1,3}\s*-\s*(.+)$", stem)
    title = m.group(1) if m else stem
    title = re.sub(r"^\s*--\s*", "", title)
    title = title.strip()
    return title


def read_flac_title(path: Path) -> str:
    if path.suffix.lower() != ".flac":
        return ""
    proc = subprocess.run(
        ["metaflac", "--show-tag=TITLE", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    for line in proc.stdout.splitlines():
        if line.startswith("TITLE="):
            return line.split("=", 1)[1].strip()
    return ""


def discover_track_titles(work_dir: Path) -> List[str]:
    entries: List[Tuple[int, str, Path]] = []
    fallback_no = 10000
    for p in sorted(work_dir.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() not in AUDIO_EXTS:
            continue
        m = re.match(r"^(\d{1,3})\s*-\s*", p.stem)
        if m:
            no = int(m.group(1))
        else:
            no = fallback_no
            fallback_no += 1
        entries.append((no, p.name.lower(), p))
    entries.sort(key=lambda x: (x[0], x[1]))

    titles: List[str] = []
    for _, _, p in entries:
        title = read_flac_title(p).strip()
        if not title:
            title = clean_track_title_from_name(p.stem)
        if title:
            titles.append(title)
    return titles


def infer_composer_from_album_dir(album_dir: Path) -> str:
    name = album_dir.name
    cleaned = re.sub(r"^\[[^\]]+\]\s*", "", name)
    cleaned = re.sub(r"^CD\s*[0-9A-Za-z._-]+\s+", "", cleaned, flags=re.IGNORECASE)
    if " - " in cleaned:
        left = cleaned.split(" - ", 1)[0].strip()
        return left
    return ""


def infer_album_hint_from_album_dir(album_dir: Path) -> str:
    name = album_dir.name
    cleaned = re.sub(r"^\[[^\]]+\]\s*", "", name)
    cleaned = re.sub(r"^CD\s*[0-9A-Za-z._-]+\s+", "", cleaned, flags=re.IGNORECASE)
    if " - " in cleaned:
        return cleaned.split(" - ", 1)[1].strip()
    return cleaned.strip()


def _try_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def candidate_imslp_paths(imslp_dir: Path, composer_hint: str) -> List[Path]:
    candidates: List[Path] = []
    seen: set[Path] = set()
    hint = (composer_hint or "").strip()
    probes: List[str] = []
    if hint:
        probes.extend(
            [
                hint,
                hint.replace(" ", "_"),
                hint.replace("_", " "),
                hint.split()[-1],
            ]
        )
    for probe in probes:
        if not probe:
            continue
        path = imslp_dir / f"abs_{probe}_db.json"
        if path.exists() and path not in seen:
            candidates.append(path)
            seen.add(path)

    if candidates:
        return candidates

    # Fallback: fuzzy scan headers by composer name.
    norm_hint = normalize_text(hint)
    if not norm_hint:
        return candidates
    for path in sorted(imslp_dir.glob("abs_*_db.json")):
        data = _try_load_json(path)
        if not data:
            continue
        composers = data.get("composers") or []
        if not composers:
            continue
        c0 = composers[0]
        c_name = f"{c0.get('complete_name', '')} {c0.get('name', '')}".strip()
        if not c_name:
            continue
        score = max(text_similarity(c_name, hint), jaccard_similarity(c_name, hint))
        if score >= 0.65 and path not in seen:
            candidates.append(path)
            seen.add(path)
    return candidates


def choose_composer_entry(db: dict, composer_hint: str) -> Tuple[str, List[WorkRow]]:
    composers = db.get("composers") or []
    if not composers:
        return "", []
    grouped: Dict[str, Dict[str, object]] = {}

    for comp in composers:
        complete = (comp.get("complete_name") or "").strip()
        short = (comp.get("name") or "").strip()
        names = [n for n in [complete, short] if n]
        group_key = normalize_text(short or complete)
        if not group_key and names:
            group_key = normalize_text(names[0].split()[-1])
        if not group_key:
            continue

        works = comp.get("works") or []
        rows = [
            WorkRow(
                title=(w.get("title") or "").strip(),
                alttitle=(w.get("alttitle") or "").strip(),
                subtitle=(w.get("subtitle") or "").strip(),
                genre=(w.get("genre") or "").strip(),
            )
            for w in works
            if (w.get("title") or "").strip()
        ]
        if not rows:
            continue

        bucket = grouped.setdefault(
            group_key,
            {
                "names": set(),
                "rows": [],
                "seen": set(),
            },
        )
        bucket["names"].update(names)
        for row in rows:
            row_key = (row.title, row.alttitle, row.subtitle, row.genre)
            if row_key in bucket["seen"]:
                continue
            bucket["seen"].add(row_key)
            bucket["rows"].append(row)

    if not grouped:
        return "", []

    hint = composer_hint.strip()
    best_key = ""
    best_score = -1.0
    best_rows_count = -1
    for key, payload in grouped.items():
        rows = payload["rows"]  # type: ignore[assignment]
        names = payload["names"]  # type: ignore[assignment]
        if not rows:
            continue
        if not hint:
            score = 0.0
        else:
            score = 0.0
            for n in names:
                score = max(score, text_similarity(str(n), hint), jaccard_similarity(str(n), hint))
        rows_count = len(rows)
        if score > best_score or (abs(score - best_score) < 1e-9 and rows_count > best_rows_count):
            best_score = score
            best_rows_count = rows_count
            best_key = key

    if not best_key:
        best_key = max(grouped.keys(), key=lambda k: len(grouped[k]["rows"]))  # type: ignore[index]

    selected = grouped[best_key]
    names_sorted = sorted([str(x) for x in selected["names"] if str(x).strip()], key=len, reverse=True)
    display_name = names_sorted[0] if names_sorted else composer_hint.strip()
    return display_name, list(selected["rows"])  # type: ignore[list-item]


def load_catalog_works(whitebull_dir: Path, composer_hint: str) -> Tuple[str, str, List[WorkRow]]:
    imslp_dir = whitebull_dir / "imslp"
    for path in candidate_imslp_paths(imslp_dir, composer_hint):
        data = _try_load_json(path)
        if not data:
            continue
        composer_name, works = choose_composer_entry(data, composer_hint)
        if works:
            return "imslp", composer_name, works

    abs_db = whitebull_dir / "absolutely" / "abs_music_db.json"
    data = _try_load_json(abs_db)
    if data:
        composer_name, works = choose_composer_entry(data, composer_hint)
        if works:
            return "abs_music_db", composer_name, works
    return "", "", []


def movement_similarity(source_titles: Sequence[str], catalog_titles: Sequence[str]) -> Tuple[float, int]:
    if not source_titles or not catalog_titles:
        return 0.0, 0
    used: set[int] = set()
    total = 0.0
    hit = 0
    for src in source_titles:
        best = 0.0
        best_idx = -1
        for i, cand in enumerate(catalog_titles):
            if i in used:
                continue
            score = max(text_similarity(src, cand), jaccard_similarity(src, cand))
            if score > best:
                best = score
                best_idx = i
        if best_idx >= 0 and best >= 0.12:
            used.add(best_idx)
            total += best
            hit += 1
    score = total / max(1, len(source_titles))
    return score, hit


def extract_form_keywords(value: str) -> set[str]:
    words = tokenize(value)
    return {w for w in words if w in FORM_KEYWORDS}


def source_looks_like_ballet(album_hint: str, source_titles: Sequence[str]) -> bool:
    album_low = (album_hint or "").strip().lower()
    titles_low = [((x or "").strip().lower()) for x in source_titles if (x or "").strip()]
    if "ballet" in album_low:
        return True
    if any(h in album_low for h in BALLET_HINTS):
        return True
    if any(any(h in t for h in BALLET_HINTS) for t in titles_low):
        return True

    act_hits = sum(1 for t in titles_low if re.search(r"\bact\s*(i|ii|iii|iv|\d+)\b", t))
    dance_hits = 0
    for t in titles_low:
        if any(k in t for k in ("pas de", "variation", "coda", "valse", "waltz", "farandole", "polacca", "sarabande", "apotheose", "apotheosis", "entracte", "panorama")):
            dance_hits += 1
    return act_hits >= 2 and dance_hits >= 3


def rank_works(
    works: Sequence[WorkRow],
    *,
    album_hint: str,
    source_titles: Sequence[str],
) -> List[RankedWork]:
    ranked: List[RankedWork] = []
    album_nonempty = album_hint.strip()
    first_source = source_titles[0] if source_titles else ""
    hinted_op = extract_opus(f"{album_hint} {first_source}")
    hinted_no = extract_work_no(f"{album_hint} {first_source}")
    hinted_forms = extract_form_keywords(f"{album_hint} {first_source}")
    source_movements = [strip_work_prefix_for_movement(s) for s in source_titles]
    source_ballet = source_looks_like_ballet(album_hint, source_titles)
    has_ballet_candidate = any(
        (w.genre or "").strip() == "Ballet" or "ballet" in f"{w.title} {w.alttitle}".lower()
        for w in works
    )

    for row in works:
        variants = [x for x in [row.title, row.alttitle] if x]
        if not variants:
            continue
        title_score = 0.0
        token_score = 0.0
        for v in variants:
            if album_nonempty:
                title_score = max(title_score, text_similarity(album_hint, v))
                token_score = max(token_score, jaccard_similarity(album_hint, v))
            if first_source:
                title_score = max(title_score, text_similarity(first_source, v))
                token_score = max(token_score, jaccard_similarity(first_source, v))

        subtitle_rows = split_titles(row.subtitle)
        mov_score, mov_hits = movement_similarity(source_movements, subtitle_rows)

        count_bonus = 0.0
        if subtitle_rows and source_titles and len(subtitle_rows) == len(source_titles):
            count_bonus += 10.0

        op_bonus = 0.0
        row_op = extract_opus(f"{row.title} {row.alttitle}")
        if hinted_op and row_op:
            if hinted_op == row_op:
                op_bonus = 8.0
            else:
                op_bonus = -4.0

        no_bonus = 0.0
        row_no = extract_work_no(f"{row.title} {row.alttitle}")
        if hinted_no and row_no:
            if hinted_no == row_no:
                no_bonus = 6.0
            else:
                no_bonus = -3.0

        form_bonus = 0.0
        row_forms = extract_form_keywords(f"{row.title} {row.alttitle}")
        if hinted_forms:
            if hinted_forms & row_forms:
                form_bonus = 12.0
            else:
                form_bonus = -10.0

        ballet_bonus = 0.0
        if source_ballet:
            row_blob = f"{row.title} {row.alttitle} {row.genre}".lower()
            is_ballet_row = row.genre.strip() == "Ballet" or "ballet" in row_blob
            if is_ballet_row:
                ballet_bonus = 120.0
            else:
                ballet_bonus = -30.0
            if "suite" in row_blob and "ballet" not in row_blob:
                ballet_bonus -= 12.0
            if has_ballet_candidate and not is_ballet_row:
                # Hard preference: once a Ballet candidate exists, non-Ballet rows
                # should not outrank it for ballet-like source tracks.
                ballet_bonus -= 120.0

        total = (
            title_score * 30.0
            + token_score * 25.0
            + mov_score * 35.0
            + count_bonus
            + op_bonus
            + no_bonus
            + form_bonus
            + ballet_bonus
        )

        ranked.append(
            RankedWork(
                row=row,
                score=total,
                title_score=title_score,
                token_score=token_score,
                movement_score=mov_score,
                matched_subtitles=mov_hits,
            )
        )
    ranked.sort(key=lambda x: x.score, reverse=True)
    return ranked


def can_accept(best: RankedWork, second: Optional[RankedWork]) -> bool:
    if best.score < 38.0:
        return False
    if best.movement_score < 0.24 and best.title_score < 0.62 and best.token_score < 0.34:
        return False
    if second is not None:
        margin = best.score - second.score
        if margin < 6.0 and best.movement_score < 0.60 and best.title_score < 0.78:
            return False
    return True


def normalize_titles_for_runme(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for v in values:
        t = (v or "").strip()
        if not t:
            continue
        t = re.sub(r"\s+", " ", t).strip()
        out.append(t)
    return out


def main() -> int:
    args = parse_args()
    runme_path = Path(args.runme).expanduser().resolve()
    work_dir = Path(args.work_dir).expanduser().resolve()
    album_dir = Path(args.album_dir).expanduser().resolve()
    whitebull_dir = (
        Path(args.whitebull_dir).expanduser().resolve()
        if args.whitebull_dir
        else Path(__file__).resolve().parents[3]
    )

    payload: Dict[str, object] = {
        "ok": True,
        "runme": str(runme_path),
        "work_dir": str(work_dir),
        "album_dir": str(album_dir),
        "catalog": "",
        "matched": False,
        "matched_title": "",
        "matched_score": 0.0,
        "updated_keys": [],
        "reason": "",
    }

    if not runme_path.exists():
        payload["ok"] = False
        payload["reason"] = f"runme not found: {runme_path}"
        print(json.dumps(payload, ensure_ascii=False))
        return 2
    if not work_dir.is_dir():
        payload["ok"] = False
        payload["reason"] = f"work dir not found: {work_dir}"
        print(json.dumps(payload, ensure_ascii=False))
        return 2

    fields = load_runme_fields(runme_path)
    composer_hint = (fields.get("Composer") or "").strip()
    album_hint = (fields.get("Album") or "").strip()
    if not composer_hint:
        composer_hint = infer_composer_from_album_dir(album_dir)
    if not album_hint or album_hint in {"Symphony", "-"}:
        album_hint = infer_album_hint_from_album_dir(album_dir)

    file_titles = discover_track_titles(work_dir)
    runme_titles = split_titles(fields.get("Titles", ""))
    source_titles = normalize_titles_for_runme(file_titles if file_titles else runme_titles)
    if not source_titles:
        source_titles = normalize_titles_for_runme(runme_titles)

    catalog_name, canonical_composer, works = load_catalog_works(whitebull_dir, composer_hint)
    payload["catalog"] = catalog_name
    if not works:
        payload["reason"] = "no catalog works found for composer"
        print(json.dumps(payload, ensure_ascii=False) if args.json else payload["reason"])
        return 0

    ranked = rank_works(works, album_hint=album_hint, source_titles=source_titles)
    if not ranked:
        payload["reason"] = "catalog has no rankable work rows"
        print(json.dumps(payload, ensure_ascii=False) if args.json else payload["reason"])
        return 0

    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    payload["matched_score"] = round(best.score, 3)

    if not can_accept(best, second):
        payload["reason"] = "best candidate confidence too low"
        print(json.dumps(payload, ensure_ascii=False) if args.json else payload["reason"])
        return 0

    updates: Dict[str, str] = {}
    chosen = best.row
    if canonical_composer:
        updates["Composer"] = canonical_composer
    if chosen.title:
        updates["Album"] = chosen.title
    if chosen.genre in VALID_GENRES:
        updates["Genre"] = chosen.genre

    chosen_subtitles = normalize_titles_for_runme(split_titles(chosen.subtitle))
    if chosen_subtitles and source_titles and len(chosen_subtitles) == len(source_titles):
        updates["Titles"] = ";".join(chosen_subtitles)
    elif not fields.get("Titles", "").strip() and source_titles:
        updates["Titles"] = ";".join(source_titles)

    changed = write_runme_fields(runme_path, updates)
    payload["matched"] = True
    payload["matched_title"] = chosen.title
    payload["updated_keys"] = changed
    payload["reason"] = "matched and updated" if changed else "matched but no field changes"

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(
            f"[imslp-canonical] matched={payload['matched']} "
            f"title={payload['matched_title']} score={payload['matched_score']} "
            f"updated={','.join(changed) if changed else '-'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
