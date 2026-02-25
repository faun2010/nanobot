#!/usr/bin/env python3
"""Detect probable catalog number (catno) from album local artifacts.

Sources (in priority order):
- explicit input
- directory name patterns ([446172-2], CD 098 ...)
- JSON metadata files (musicbrainz/discogs)
- cue/log/txt/runme text
- PDF extracted text (pdftotext)
- image OCR (tesseract)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

CAT_KEYS = {"catalog-number", "catno", "catalog_number", "catalognumber", "catalog", "catalogno"}
TEXT_EXTS = {".cue", ".log", ".txt", ".nfo", ".md", ".runme", ""}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
PDF_EXTS = {".pdf"}
IGNORE_VALUES = {"none", "unknown", "n/a", "na", "-", ""}
MONTH_WORDS = {
    "JANUARY",
    "FEBRUARY",
    "MARCH",
    "APRIL",
    "MAY",
    "JUNE",
    "JULY",
    "AUGUST",
    "SEPTEMBER",
    "OCTOBER",
    "NOVEMBER",
    "DECEMBER",
}
BAD_HEAD_TOKENS = {
    "TRACK",
    "INDEX",
    "FILE",
    "REM",
    "TITLE",
    "PERFORMER",
    "DISC",
    "DISCID",
    "COPY",
    "PEAK",
    "LEVEL",
    "FROM",
    "ERROR",
    "REPORT",
    "STATUS",
    "IN",
    "AND",
    "THE",
    "OF",
    "FOR",
    "TO",
    "WITH",
    "BY",
    "AT",
    "ON",
    "NO",
    "NOS",
    "CALL",
}


@dataclass
class Candidate:
    value: str
    score: int
    sources: List[str] = field(default_factory=list)


def norm_spaces(text: str) -> str:
    text = (text or "").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_catno(raw: str) -> str:
    s = norm_spaces(raw)
    s = s.strip("[](){}<>;,.\"")
    s = s.replace("_", " ")
    s = norm_spaces(s)

    m = re.match(r"^(\d{3})\s?(\d{3}-[0-9A-Za-z])$", s)
    if m:
        return f"{m.group(1)} {m.group(2)}"

    m = re.match(r"^CD\s*[-:]?\s*([0-9]{2,4})$", s, re.IGNORECASE)
    if m:
        return f"CD {m.group(1)}"

    return s


def looks_like_catno(val: str, *, source: str, context: str = "") -> bool:
    v = normalize_catno(val)
    if not v:
        return False

    low = v.lower()
    if low in IGNORE_VALUES:
        return False

    if source != "explicit" and re.fullmatch(r"[0-9a-fA-F]{8,10}", v):
        return False

    if ":" in v and re.search(r"\d{1,2}:\d{2}", v):
        return False

    token_head = v.split(" ", 1)[0].upper()
    if token_head in BAD_HEAD_TOKENS:
        return False

    if token_head in MONTH_WORDS:
        return False

    if len(v) < 4 or len(v) > 32:
        return False

    digit_count = sum(ch.isdigit() for ch in v)
    if digit_count == 0:
        return False

    if digit_count < 3 and not re.search(r"\bCD\s*[-:]?\s*[0-9]{2,4}\b", v, re.IGNORECASE):
        ctx = context.lower()
        if "catalog" not in ctx and "catno" not in ctx and "cat no" not in ctx:
            return False

    if re.search(r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+[0-9]{4}\b", v):
        return False

    # Accept strong prefixes.
    if re.search(r"\bCD\s*[0-9]{2,4}\b", v, re.IGNORECASE):
        return True

    # Typical mixed patterns: CDC 777-2, MYK 38525, 123 456-7, 446172-2 ...
    uv = v.upper()
    if re.fullmatch(r"[A-Z]{2,6}\s*-?\s*[0-9]{3,6}(?:[-/][0-9A-Za-z]{1,4})?", uv):
        return True
    if re.fullmatch(r"[A-Z]{2,6}[0-9]{3,6}(?:[-/][0-9A-Za-z]{1,4})?", uv):
        return True
    if re.search(r"[0-9]{3}\s?[0-9]{3}-[0-9A-Za-z]", v):
        return True
    if re.search(r"[0-9]{5,}-[0-9A-Za-z]", v):
        return True

    # Plain short numbers are usually false positives unless source is dir prefix.
    if re.fullmatch(r"[0-9]{2,4}", v):
        return source.startswith("dir:")

    return False


def add_candidate(pool: Dict[str, Candidate], raw: str, *, score: int, source: str, context: str = "") -> None:
    if not looks_like_catno(raw, source=source, context=context):
        return
    v = normalize_catno(raw)
    old = pool.get(v)
    if old is None:
        pool[v] = Candidate(value=v, score=score, sources=[source])
        return
    if score > old.score:
        old.score = score
    if source not in old.sources:
        old.sources.append(source)


def run_cmd(args: List[str], *, timeout: int = 15) -> Tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        out = p.stdout or ""
        if not out and p.stderr:
            out = p.stderr
        return p.returncode, out
    except Exception:
        return 127, ""


def extract_catalog_candidates_from_json(node) -> Iterable[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            k_low = str(k).lower()
            if k_low in CAT_KEYS and isinstance(v, str):
                yield v
            else:
                yield from extract_catalog_candidates_from_json(v)
    elif isinstance(node, list):
        for item in node:
            yield from extract_catalog_candidates_from_json(item)


def parse_text_for_candidates(text: str) -> List[Tuple[str, str, int]]:
    out: List[Tuple[str, str, int]] = []
    if not text:
        return out

    # Keyword-based matches (higher confidence)
    kw_pat = re.compile(
        r"(?i)(?:catalog(?:ue)?(?:\s*no\.?|\s*number)?|cat(?:alog)?\.?\s*no\.?|cat#|catno|品番|编号)"
        r"\s*[:：#]?\s*([A-Za-z0-9][A-Za-z0-9 ._/-]{1,30})"
    )
    for m in kw_pat.finditer(text):
        out.append((m.group(1), m.group(0), 92))

    # Bracket payloads often contain catno.
    for m in re.finditer(r"\[([^\]]{3,32})\]", text):
        out.append((m.group(1), m.group(0), 72))

    # General patterns.
    generic_patterns = [
        r"\bCD\s*[-:]?\s*[0-9]{2,4}\b",
        r"\b[A-Z]{2,6}\s*-?\s*[0-9]{3,6}(?:[-/][0-9A-Za-z]{1,4})?\b",
        r"\b[A-Z]{2,6}[0-9]{3,6}(?:[-/][0-9A-Za-z]{1,4})?\b",
        r"\b[0-9]{3}\s?[0-9]{3}-[0-9A-Za-z]\b",
        r"\b[0-9]{5,}-[0-9A-Za-z]\b",
    ]
    upper_text = text.upper()
    for pat in generic_patterns:
        for m in re.finditer(pat, upper_text):
            out.append((m.group(0), m.group(0), 58))

    return out


def list_candidate_files(album_dir: Path, exts: set[str], *, max_depth: int = 2) -> List[Path]:
    files: List[Path] = []
    base_depth = len(album_dir.parts)
    for p in album_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.name.startswith("._"):
            continue
        depth = len(p.parts) - base_depth
        if depth > max_depth:
            continue
        if p.suffix.lower() in exts:
            files.append(p)
    return sorted(files)


def score_image_name(name: str) -> int:
    n = name.lower()
    score = 0
    for kw, pts in (
        ("cover", 30),
        ("front", 25),
        ("folder", 20),
        ("back", 15),
        ("booklet", 12),
        ("inlay", 10),
        ("tray", 10),
        ("cd", 8),
    ):
        if kw in n:
            score += pts
    return score


def derive_title_hints(album_dir: Path, text_files: List[Path]) -> List[str]:
    hints: List[str] = []

    name = album_dir.name
    name = re.sub(r"^\[[^\]]+\]\s*", "", name)
    name = re.sub(
        r"^CD\s*[-:]?\s*[0-9A-Za-z]+(?:[\s-]+[0-9A-Za-z]+){0,3}\s+",
        "",
        name,
        flags=re.IGNORECASE,
    )
    name = norm_spaces(name.replace("_", " "))
    if name:
        hints.append(name)

    for tf in text_files:
        if tf.suffix.lower() != ".cue":
            continue
        try:
            content = tf.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        m = re.search(r"(?im)^\s*TITLE\s+\"([^\"]+)\"", content)
        if m:
            hints.append(norm_spaces(m.group(1)))
            break

    # Deduplicate and keep order.
    out: List[str] = []
    seen = set()
    for h in hints:
        if not h:
            continue
        if h in seen:
            continue
        seen.add(h)
        out.append(h)
    return out


def detect_catalog(album_dir: Path, explicit: str, max_images: int, max_pdfs: int) -> Dict[str, object]:
    pool: Dict[str, Candidate] = {}

    if explicit.strip():
        add_candidate(pool, explicit, score=100, source="explicit")

    # Directory-level heuristics.
    names = [album_dir.name]
    if album_dir.parent != album_dir:
        names.append(album_dir.parent.name)

    for nm in names:
        m = re.match(r"^\[([^\]]+)\]", nm)
        if m:
            add_candidate(pool, m.group(1), score=92, source="dir:bracket")

        m = re.match(r"^(CD\s*[-:]?\s*[0-9]{2,4})\b", nm, flags=re.IGNORECASE)
        if m:
            add_candidate(pool, m.group(1), score=78, source="dir:cd_prefix")

        for raw, ctx, sc in parse_text_for_candidates(nm):
            add_candidate(pool, raw, score=sc + 5, source="dir:pattern", context=ctx)

    # File/path names can carry catalog numbers (cover scans, rip names, etc.).
    base_depth = len(album_dir.parts)
    for p in album_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.name.startswith("._"):
            continue
        depth = len(p.parts) - base_depth
        if depth > 3:
            continue
        rel = str(p.relative_to(album_dir))
        for raw, ctx, sc in parse_text_for_candidates(p.name):
            add_candidate(pool, raw, score=sc + 6, source=f"name:{p.name}", context=ctx)
        for raw, ctx, sc in parse_text_for_candidates(rel):
            add_candidate(pool, raw, score=sc + 2, source=f"path:{rel}", context=ctx)

    # JSON metadata.
    for jf_name in ("musicbrainz_0.json", "musicbrainz_0.db", "discogs_0.json", "discogs_0.db"):
        jf = album_dir / jf_name
        if not jf.exists() or jf.name.startswith("._"):
            continue
        try:
            obj = json.loads(jf.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for raw in extract_catalog_candidates_from_json(obj):
            add_candidate(pool, str(raw), score=86, source=f"json:{jf_name}")

    # Text files.
    text_files = list_candidate_files(album_dir, TEXT_EXTS, max_depth=2)
    for tf in text_files:
        try:
            text = tf.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        ext = tf.suffix.lower()
        ext_adj = 0
        if ext == ".cue":
            ext_adj = 6
        elif ext == ".log":
            ext_adj = -6
        elif ext in {".txt", ".md", ".nfo"}:
            ext_adj = -2
        # limit parse volume for huge logs
        text = text[:400_000]
        for raw, ctx, sc in parse_text_for_candidates(text):
            add_candidate(pool, raw, score=sc + ext_adj, source=f"text:{tf.name}", context=ctx)

    # PDF text extraction.
    if shutil_which("pdftotext"):
        pdfs = list_candidate_files(album_dir, PDF_EXTS, max_depth=2)[: max(0, max_pdfs)]
        for pdf in pdfs:
            rc, out = run_cmd(["pdftotext", "-layout", str(pdf), "-"], timeout=25)
            if rc != 0 or not out:
                continue
            out = out[:500_000]
            for raw, ctx, sc in parse_text_for_candidates(out):
                add_candidate(pool, raw, score=sc - 5, source=f"pdf:{pdf.name}", context=ctx)

    # OCR images.
    if shutil_which("tesseract"):
        imgs = list_candidate_files(album_dir, IMAGE_EXTS, max_depth=2)
        imgs = sorted(imgs, key=lambda p: (-score_image_name(p.name), p.name))
        imgs = imgs[: max(0, max_images)]
        for img in imgs:
            rc, out = run_cmd(["tesseract", str(img), "stdout", "--psm", "6", "-l", "eng"], timeout=20)
            if rc != 0 or not out:
                continue
            out = out[:200_000]
            for raw, ctx, sc in parse_text_for_candidates(out):
                add_candidate(pool, raw, score=sc - 12, source=f"ocr:{img.name}", context=ctx)

    ordered = sorted(pool.values(), key=lambda c: (-c.score, c.value))
    best = ordered[0] if ordered else None

    title_hints = derive_title_hints(album_dir, text_files)

    return {
        "ok": best is not None,
        "catno": best.value if best else "",
        "source": best.sources[0] if best and best.sources else "",
        "score": int(best.score) if best else 0,
        "title_hints": title_hints,
        "candidates": [
            {
                "value": c.value,
                "score": int(c.score),
                "sources": c.sources,
            }
            for c in ordered[:30]
        ],
    }


def shutil_which(cmd: str) -> Optional[str]:
    for p in os.environ.get("PATH", "").split(os.pathsep):
        full = os.path.join(p, cmd)
        if os.path.isfile(full) and os.access(full, os.X_OK):
            return full
    return None


def main() -> int:
    p = argparse.ArgumentParser(description="Detect catalog number from album artifacts.")
    p.add_argument("--album-dir", required=True)
    p.add_argument("--explicit", default="")
    p.add_argument("--max-images", type=int, default=6)
    p.add_argument("--max-pdfs", type=int, default=3)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    album_dir = Path(args.album_dir).expanduser().resolve()
    if not album_dir.is_dir():
        payload = {"ok": False, "reason": "album_dir_missing", "catno": ""}
        print(json.dumps(payload, ensure_ascii=False))
        return 2

    payload = detect_catalog(album_dir, args.explicit, args.max_images, args.max_pdfs)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        if payload.get("ok"):
            print(payload.get("catno", ""))
        else:
            print("")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
