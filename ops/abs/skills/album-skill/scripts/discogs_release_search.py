#!/usr/bin/env python3
"""Search Discogs release ids by catalog numbers and title hints.

Output (default):
  one TSV row per candidate:
    <release_id>\t<field>\t<query>\t<score>\t<title>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

DEFAULT_UA = "whitebull-album-skill/1.0 (+discogs-search)"


@dataclass
class Candidate:
    rid: str
    score: int
    title: str = ""
    sources: List[Tuple[str, str]] = field(default_factory=list)


def norm_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\u00a0", " ")).strip()


def norm_catno(text: str) -> str:
    t = norm_spaces(text).upper()
    t = re.sub(r"[^A-Z0-9]+", "", t)
    return t


def http_json(url: str, *, timeout: int, ua: str) -> Dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": ua,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    return json.loads(payload)


def query_discogs(params: Dict[str, str], *, timeout: int, ua: str, token: str) -> List[Dict]:
    full = dict(params)
    full["type"] = "release"
    if token:
        full["token"] = token
    url = "https://api.discogs.com/database/search?" + urllib.parse.urlencode(full)
    obj = http_json(url, timeout=timeout, ua=ua)
    rows = obj.get("results")
    return rows if isinstance(rows, list) else []


def add_candidate(pool: Dict[str, Candidate], rid: str, *, score: int, field: str, query: str, title: str) -> None:
    old = pool.get(rid)
    if old is None:
        pool[rid] = Candidate(rid=rid, score=score, title=title, sources=[(field, query)])
        return
    if score > old.score:
        old.score = score
    if title and not old.title:
        old.title = title
    src = (field, query)
    if src not in old.sources:
        old.sources.append(src)


def match_title_tokens(query: str, title: str) -> int:
    q = [w for w in re.split(r"[^a-z0-9]+", query.lower()) if len(w) >= 4]
    if not q:
        return 0
    t = set(w for w in re.split(r"[^a-z0-9]+", title.lower()) if w)
    return sum(1 for w in q if w in t)


def search_catno(
    pool: Dict[str, Candidate],
    catnos: Iterable[str],
    *,
    limit: int,
    timeout: int,
    ua: str,
    token: str,
) -> bool:
    had_error = False
    for raw in catnos:
        catno = norm_spaces(raw)
        if not catno:
            continue
        try:
            rows = query_discogs({"catno": catno, "per_page": str(limit)}, timeout=timeout, ua=ua, token=token)
        except Exception:
            had_error = True
            continue
        expected = norm_catno(catno)
        for row in rows:
            rid = row.get("id")
            if rid is None:
                continue
            rid_s = str(rid)
            title = norm_spaces(str(row.get("title", "")))
            score = 80
            row_catno = norm_catno(str(row.get("catno", "")))
            if row_catno and row_catno == expected:
                score += 12
            if row.get("type") == "release":
                score += 2
            add_candidate(pool, rid_s, score=score, field="discogs_catno", query=catno, title=title)
    return had_error


def search_title(
    pool: Dict[str, Candidate],
    hints: Iterable[str],
    *,
    limit: int,
    timeout: int,
    ua: str,
    token: str,
) -> bool:
    had_error = False
    for raw in hints:
        hint = norm_spaces(raw)
        if not hint:
            continue
        try:
            rows = query_discogs({"q": hint, "per_page": str(limit)}, timeout=timeout, ua=ua, token=token)
        except Exception:
            had_error = True
            continue
        for row in rows:
            rid = row.get("id")
            if rid is None:
                continue
            rid_s = str(rid)
            title = norm_spaces(str(row.get("title", "")))
            score = 50 + min(20, match_title_tokens(hint, title) * 5)
            if row.get("type") == "release":
                score += 2
            add_candidate(pool, rid_s, score=score, field="discogs_q", query=hint, title=title)
    return had_error


def dedupe(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        x = norm_spaces(item)
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Discogs release search by catno/title hints.")
    p.add_argument("--catno", action="append", default=[])
    p.add_argument("--title-hint", action="append", default=[])
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--timeout", type=int, default=10)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    if args.limit < 1:
        args.limit = 1
    if args.limit > 100:
        args.limit = 100

    catnos = dedupe(args.catno)
    hints = dedupe(args.title_hint)
    if not catnos and not hints:
        payload = {"ok": False, "reason": "no_query"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 2

    ua = os.environ.get("DISCOGS_USER_AGENT", "").strip() or DEFAULT_UA
    token = os.environ.get("DISCOGS_TOKEN", "").strip()

    pool: Dict[str, Candidate] = {}
    err_cat = search_catno(pool, catnos, limit=args.limit, timeout=args.timeout, ua=ua, token=token)
    err_title = search_title(pool, hints, limit=args.limit, timeout=args.timeout, ua=ua, token=token)

    ordered = sorted(pool.values(), key=lambda x: (-x.score, x.rid))
    if args.json:
        print(
            json.dumps(
                {
                    "ok": bool(ordered),
                    "had_error": bool(err_cat or err_title),
                    "count": len(ordered),
                    "candidates": [
                        {
                            "id": c.rid,
                            "score": c.score,
                            "title": c.title,
                            "sources": [{"field": f, "query": q} for f, q in c.sources],
                        }
                        for c in ordered
                    ],
                },
                ensure_ascii=False,
            )
        )
    else:
        for c in ordered:
            field, query = c.sources[0]
            print(f"{c.rid}\t{field}\t{query}\t{c.score}\t{c.title}")

    if ordered:
        return 0
    if err_cat or err_title:
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
