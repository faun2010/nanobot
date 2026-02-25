#!/usr/bin/env python3
"""Infer probable back cover image from JPG/JPEG files in an album directory.

Rules:
- Never crop/split image parts.
- Traverse existing JPG/JPEG files and score each candidate.
- Return best candidate only when confidence is high enough.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

IMAGE_EXTS = {".jpg", ".jpeg"}
IGNORE_BASENAMES = {
    "cover.jpg",
    "cover.jpeg",
    "cover_org.jpg",
    "cover_org.jpeg",
    "cover_ori.jpg",
    "cover_ori.jpeg",
    "cover_online.jpg",
    "cover_online.jpeg",
    "folder.jpg",
    "folder.jpeg",
    "front.jpg",
    "front.jpeg",
    "back.jpg",
    "back.jpeg",
}

KEYWORD_POSITIVE: Sequence[Tuple[str, int]] = (
    ("tracklist", 26),
    ("track list", 24),
    ("all rights reserved", 30),
    ("unauthorised", 20),
    ("unauthorized", 20),
    ("copyright", 18),
    ("warning", 12),
    ("barcode", 22),
    ("made in", 10),
    ("stereo", 8),
    ("digital", 8),
    ("recorded", 8),
    ("produced", 8),
    ("catalog", 8),
    ("cat.", 6),
    ("cat no", 7),
    ("catno", 7),
    ("disc", 4),
    ("cd", 4),
)

KEYWORD_NEGATIVE: Sequence[Tuple[str, int]] = (
    ("booklet", -30),
    ("libretto", -24),
    ("essay", -24),
    ("biography", -20),
    ("introduction", -18),
    ("translation", -14),
    ("chapter", -12),
)


@dataclass
class Candidate:
    path: str
    rel: str
    name: str
    width: int
    height: int
    score: int
    reasons: List[str]
    ocr_len: int


def run_cmd(args: List[str], timeout: int = 20) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as exc:
        return 127, "", str(exc)


def which(cmd: str) -> Optional[str]:
    for p in os.environ.get("PATH", "").split(os.pathsep):
        full = os.path.join(p, cmd)
        if os.path.isfile(full) and os.access(full, os.X_OK):
            return full
    return None


def read_size(path: Path) -> Tuple[int, int]:
    rc, out, _ = run_cmd(["magick", "identify", "-format", "%w %h", str(path)], timeout=10)
    if rc != 0 or not out.strip():
        rc2, out2, _ = run_cmd(["identify", "-format", "%w %h", str(path)], timeout=10)
        if rc2 != 0 or not out2.strip():
            return 0, 0
        out = out2
    parts = out.strip().split()
    if len(parts) != 2:
        return 0, 0
    try:
        return int(parts[0]), int(parts[1])
    except Exception:
        return 0, 0


def sanitize_text(s: str) -> str:
    s = s.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", s).strip()


def ocr_text(path: Path) -> str:
    if not which("tesseract"):
        return ""
    rc, out, _ = run_cmd(["tesseract", str(path), "stdout", "--psm", "6", "-l", "eng"], timeout=25)
    if rc != 0:
        return ""
    return out[:240_000]


def score_filename(name: str) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []
    n = name.lower()

    for kw, pts in (
        ("back", 72),
        ("tray", 46),
        ("inlay", 36),
        ("rear", 32),
        ("reverse", 24),
        ("inside", -16),
        ("inner", -16),
        ("booklet", -26),
        ("book", -10),
        ("cover", -34),
        ("front", -28),
        ("folder", -20),
        ("page", -12),
    ):
        if kw in n:
            score += pts
            reasons.append(f"name:{kw}:{pts:+d}")
    return score, reasons


def score_dimensions(width: int, height: int) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []
    if width <= 0 or height <= 0:
        return -100, ["dim:invalid:-100"]

    mn = min(width, height)
    mx = max(width, height)
    ratio = mx / float(mn)
    area = width * height

    if mn >= 600:
        score += 8
        reasons.append("dim:min>=600:+8")
    elif mn < 400:
        score -= 12
        reasons.append("dim:min<400:-12")

    if ratio <= 1.25:
        score += 8
        reasons.append("dim:ratio<=1.25:+8")
    elif ratio <= 1.55:
        score += 2
        reasons.append("dim:ratio<=1.55:+2")
    elif ratio > 1.90:
        score -= 24
        reasons.append("dim:ratio>1.90:-24")
    else:
        score -= 8
        reasons.append("dim:ratio>1.55:-8")

    if area < 220_000:
        score -= 8
        reasons.append("dim:area_small:-8")
    elif area >= 900_000:
        score += 4
        reasons.append("dim:area_large:+4")

    return score, reasons


def score_ocr(text: str) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []
    if not text:
        return -6, ["ocr:none:-6"]

    low = text.lower()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    for kw, pts in KEYWORD_POSITIVE:
        if kw in low:
            score += pts
            reasons.append(f"ocr:{kw}:{pts:+d}")
    for kw, pts in KEYWORD_NEGATIVE:
        if kw in low:
            score += pts
            reasons.append(f"ocr:{kw}:{pts:+d}")

    duration_count = len(re.findall(r"\b\d{1,2}[:.]\d{2}\b", text))
    track_line_count = 0
    for ln in lines[:600]:
        if re.match(r"^\s*(?:[0-9]{1,2}[.)]|[A-D][0-9]{1,2}|[IVX]{1,5}[.)])\s+", ln):
            track_line_count += 1

    if duration_count >= 5:
        pts = min(28, duration_count * 3)
        score += pts
        reasons.append(f"ocr:durations:{duration_count}:{pts:+d}")
    elif duration_count >= 2:
        score += 6
        reasons.append(f"ocr:durations:{duration_count}:+6")

    if track_line_count >= 5:
        pts = min(36, track_line_count * 4)
        score += pts
        reasons.append(f"ocr:track_lines:{track_line_count}:{pts:+d}")
    elif track_line_count >= 2:
        score += 7
        reasons.append(f"ocr:track_lines:{track_line_count}:+7")

    long_lines = sum(1 for ln in lines if len(ln.split()) >= 12)
    if long_lines >= 10 and track_line_count <= 2 and duration_count <= 1:
        score -= 24
        reasons.append("ocr:essay_dense:-24")
    elif long_lines >= 6 and track_line_count <= 3 and duration_count <= 2:
        score -= 12
        reasons.append("ocr:essay:-12")

    if re.search(r"(?:©|\u00a9|℗|\u2117)\s*(?:19|20)\d{2}", text):
        score += 15
        reasons.append("ocr:copyright_symbol:+15")

    if re.search(r"\b(?:ddd|aad|add)\b", low):
        score += 8
        reasons.append("ocr:digital_code:+8")

    return score, reasons


def collect_candidates(album_dir: Path, excludes: set[Path], max_depth: int) -> List[Path]:
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
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        if p.resolve() in excludes:
            continue
        if p.name.lower() in IGNORE_BASENAMES:
            continue
        files.append(p)
    return sorted(files)


def infer_back(
    album_dir: Path,
    excludes: set[Path],
    min_score: int,
    min_delta: int,
    max_depth: int,
) -> Dict[str, object]:
    if not (which("magick") or which("identify")):
        return {"ok": False, "reason": "no_identify_tool", "selected_path": "", "candidates": []}

    images = collect_candidates(album_dir, excludes, max_depth=max_depth)
    rows: List[Candidate] = []
    for img in images:
        width, height = read_size(img)
        score = 0
        reasons: List[str] = []

        s0, r0 = score_filename(img.name)
        score += s0
        reasons.extend(r0)

        s1, r1 = score_dimensions(width, height)
        score += s1
        reasons.extend(r1)

        txt = ocr_text(img)
        s2, r2 = score_ocr(txt)
        score += s2
        reasons.extend(r2)

        rows.append(
            Candidate(
                path=str(img),
                rel=str(img.relative_to(album_dir)),
                name=img.name,
                width=width,
                height=height,
                score=score,
                reasons=reasons[:24],
                ocr_len=len(sanitize_text(txt)),
            )
        )

    rows.sort(key=lambda c: (-c.score, c.name))
    best = rows[0] if rows else None
    second = rows[1] if len(rows) > 1 else None

    selected_path = ""
    selected_score = 0
    reason = "no_candidates"
    if best is not None:
        selected_score = best.score
        delta = best.score - (second.score if second else -9999)
        if best.score >= min_score and (second is None or delta >= min_delta):
            selected_path = best.path
            reason = "selected"
        elif best.score < min_score:
            reason = "low_score"
        else:
            reason = "ambiguous"

    return {
        "ok": bool(selected_path),
        "reason": reason,
        "selected_path": selected_path,
        "selected_score": int(selected_score),
        "min_score": int(min_score),
        "min_delta": int(min_delta),
        "candidate_count": len(rows),
        "candidates": [asdict(c) for c in rows[:20]],
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Detect probable back cover image from JPG files.")
    p.add_argument("--album-dir", required=True)
    p.add_argument("--exclude", action="append", default=[], help="Absolute/relative image path to exclude.")
    p.add_argument("--cover-path", default="", help="Cover image path to exclude.")
    p.add_argument("--source-path", default="", help="Source cover image path to exclude.")
    p.add_argument("--min-score", type=int, default=48)
    p.add_argument("--min-delta", type=int, default=12)
    p.add_argument("--max-depth", type=int, default=2)
    p.add_argument("--plain", action="store_true", help="Print selected path only.")
    args = p.parse_args()

    album_dir = Path(args.album_dir).expanduser().resolve()
    if not album_dir.is_dir():
        payload = {"ok": False, "reason": "album_dir_missing", "selected_path": "", "candidates": []}
        if args.plain:
            print("")
        else:
            print(json.dumps(payload, ensure_ascii=False))
        return 2

    excludes: set[Path] = set()
    for raw in list(args.exclude or []):
        if not raw:
            continue
        pth = Path(raw).expanduser()
        if not pth.is_absolute():
            pth = (album_dir / pth).resolve()
        else:
            pth = pth.resolve()
        excludes.add(pth)
    for raw in (args.cover_path, args.source_path):
        if not raw:
            continue
        pth = Path(raw).expanduser()
        if not pth.is_absolute():
            pth = (album_dir / pth).resolve()
        else:
            pth = pth.resolve()
        excludes.add(pth)

    payload = infer_back(
        album_dir=album_dir,
        excludes=excludes,
        min_score=max(0, int(args.min_score)),
        min_delta=max(0, int(args.min_delta)),
        max_depth=max(0, int(args.max_depth)),
    )

    if args.plain:
        print(payload.get("selected_path", "") or "")
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
