#!/usr/bin/env python3
"""Fetch album cover online by catalog number/title.

Priority:
1) MusicBrainz release search + Cover Art Archive front image
2) Discogs database search + release image
3) Amazon search image candidates
4) eBay search image candidates
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_UA = (
    "whitebull-cover-skill/1.1 "
    "(https://musicbrainz.org/doc/MusicBrainz_API/Search)"
)
MB_SITE = "https://musicbrainz.org"

MBID_RE = re.compile(
    r"\b([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b"
)
DISCOGS_RELEASE_URL_RE = re.compile(r"discogs\.com/release/([0-9]+)", flags=re.IGNORECASE)
DISCOGS_RELEASE_ID_RE = re.compile(r"^[0-9]{4,}$")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://")

NETWORK_PROXY = ""
NETWORK_RETRIES = 3
NETWORK_BACKOFF = 0.35


def parse_release_ref(raw: str) -> Tuple[str, str]:
    text = (raw or "").strip()
    if not text:
        return "", ""
    m = DISCOGS_RELEASE_URL_RE.search(text)
    if m:
        return "discogs", m.group(1)
    m = MBID_RE.search(text)
    if m:
        return "musicbrainz", m.group(1).lower()
    if DISCOGS_RELEASE_ID_RE.fullmatch(text):
        return "discogs", text
    return "", ""


def dedupe_keep_order(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def set_network_profile(proxy: str, *, retries: int, backoff: float) -> None:
    global NETWORK_PROXY, NETWORK_RETRIES, NETWORK_BACKOFF
    NETWORK_PROXY = (proxy or "").strip()
    NETWORK_RETRIES = max(1, int(retries))
    NETWORK_BACKOFF = max(0.0, float(backoff))


def _normalize_proxy_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if SCHEME_RE.match(value):
        return value
    # Support compact host:port form.
    if re.match(r"^[^/\s:]+:\d+$", value):
        return f"http://{value}"
    return value


def proxy_candidates(explicit: str, *, auto_proxy: bool) -> List[str]:
    seeds: List[str] = []
    if explicit:
        seeds.append(explicit)
    for key in ("https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY", "http_proxy", "HTTP_PROXY"):
        val = os.environ.get(key, "")
        if val:
            seeds.append(val)
    if auto_proxy:
        seeds.append("http://127.0.0.1:7890")
    normalized = [_normalize_proxy_url(x) for x in seeds]
    return [x for x in dedupe_keep_order(normalized) if x]


def _build_opener() -> urllib.request.OpenerDirector:
    handlers: List[Any] = []
    if NETWORK_PROXY:
        handlers.append(urllib.request.ProxyHandler({"http": NETWORK_PROXY, "https": NETWORK_PROXY}))
    else:
        handlers.append(urllib.request.ProxyHandler({}))

    ctx = ssl._create_unverified_context()
    handlers.append(urllib.request.HTTPSHandler(context=ctx))
    handlers.append(urllib.request.HTTPHandler())
    return urllib.request.build_opener(*handlers)


def _http_bytes(
    url: str,
    *,
    timeout: int,
    headers: Dict[str, str],
    retries: Optional[int] = None,
) -> Tuple[bytes, Dict[str, str]]:
    attempts = NETWORK_RETRIES if retries is None else max(1, int(retries))
    opener = _build_opener()
    last_exc: Optional[Exception] = None

    for idx in range(attempts):
        req = urllib.request.Request(url, headers=headers)
        try:
            with opener.open(req, timeout=timeout) as resp:
                payload = resp.read()
                headers_map = {k: v for k, v in resp.headers.items()}
                return payload, headers_map
        except HTTPError as exc:
            # 4xx are usually hard failures; retry only transient overload/rate-limit.
            if 400 <= exc.code < 500 and exc.code not in (408, 429):
                raise
            last_exc = exc
        except Exception as exc:
            last_exc = exc

        if idx + 1 < attempts and NETWORK_BACKOFF > 0:
            time.sleep(NETWORK_BACKOFF * (2 ** idx))

    if last_exc is None:
        raise RuntimeError(f"request failed without exception: {url}")
    raise last_exc


def http_json(url: str, *, timeout: int, headers: Dict[str, str]) -> Dict[str, Any]:
    payload, _ = _http_bytes(url, timeout=timeout, headers=headers)
    return json.loads(payload.decode("utf-8", errors="replace"))


def http_text(url: str, *, timeout: int, headers: Dict[str, str]) -> str:
    payload, _ = _http_bytes(url, timeout=timeout, headers=headers)
    return payload.decode("utf-8", errors="replace")


def network_profile_reachable(
    *,
    release_provider: str,
    release_id: str,
    catno: str,
    timeout: int,
    headers: Dict[str, str],
) -> bool:
    probe_urls: List[str] = []
    if release_provider == "discogs" or catno:
        probe_urls.append("https://api.discogs.com/")
    if release_provider == "musicbrainz":
        if release_id:
            probe_urls.append(f"https://coverartarchive.org/release/{release_id}/front")
        else:
            probe_urls.append("https://coverartarchive.org/")
    if (release_provider == "musicbrainz" and not release_id) or catno:
        probe_urls.append("https://musicbrainz.org/ws/2/release/?query=release:%22probe%22&fmt=json&limit=1")
    if not probe_urls:
        return True

    for url in probe_urls:
        try:
            _http_bytes(url, timeout=timeout, headers=headers, retries=1)
            return True
        except Exception:
            continue
    return False
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read().decode("utf-8", errors="replace")


def norm_catno(catno: str) -> str:
    text = (catno or "").strip()
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def extract_catalog_candidates(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            key_l = str(key).lower()
            if key_l in {"catalog-number", "catno", "catalog_number", "catalognumber"} and isinstance(value, str):
                yield value
            else:
                yield from extract_catalog_candidates(value)
    elif isinstance(node, list):
        for item in node:
            yield from extract_catalog_candidates(item)


def detect_catalog_number(album_dir: Path, explicit: str) -> str:
    if explicit.strip():
        return norm_catno(explicit)

    m = re.match(r"^\[([^\]]+)\]", album_dir.name)
    if m:
        return norm_catno(m.group(1))

    for name in ("musicbrainz_0.json", "discogs_0.json"):
        obj = read_json(album_dir / name)
        if not obj:
            continue
        for raw in extract_catalog_candidates(obj):
            cand = norm_catno(raw)
            if cand and cand.lower() not in {"none", "unknown", "n/a", "-"}:
                return cand
    return ""


def absolute_url(raw: str, base_url: str) -> str:
    url = (raw or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return urllib.parse.urljoin(base_url, url)
    return url


def extract_page_urls(html_text: str, *, base_url: str) -> List[str]:
    text = html.unescape(html_text or "")
    out: List[str] = []
    seen = set()

    raw_urls = []
    raw_urls.extend(re.findall(r"https?://[^\"'<>\\s]+|//[^\"'<>\\s]+", text))
    raw_urls.extend(
        re.findall(r"(?:href|src)\s*=\s*[\"']([^\"']+)[\"']", text, flags=re.IGNORECASE)
    )
    raw_urls.extend(
        x.replace("\\/", "/")
        for x in re.findall(r"https?:\\/\\/[^\"'<>\\s]+", text)
    )

    for raw in raw_urls:
        url = absolute_url(raw, base_url)
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def extract_release_page_image_urls(html_text: str, release_id: str) -> List[str]:
    out: List[str] = []
    release_id_l = (release_id or "").lower()

    for url in extract_page_urls(html_text, base_url=f"{MB_SITE}/"):
        low = url.lower()
        if "coverartarchive.org" not in low and "archive.org" not in low:
            continue
        if not any(k in low for k in (".jpg", ".jpeg", ".png", "/front")):
            continue
        if release_id_l and release_id_l not in low and "coverartarchive.org/release/" not in low:
            continue
        out.append(url)

    # Seed deterministic endpoints first.
    seed = [
        f"https://coverartarchive.org/release/{release_id}/front",
        f"https://coverartarchive.org/release/{release_id}/front-1200",
        f"https://coverartarchive.org/release/{release_id}/front-500",
    ]

    merged: List[str] = []
    seen = set()
    for url in seed + out:
        if url in seen:
            continue
        seen.add(url)
        merged.append(url)
    return merged


def extract_release_cover_art_pages(html_text: str, release_id: str) -> List[str]:
    release_l = (release_id or "").lower()
    out: List[str] = []
    for url in extract_page_urls(html_text, base_url=f"{MB_SITE}/"):
        low = url.lower()
        if f"/release/{release_l}/cover-art" in low:
            out.append(url)
    seed = [f"{MB_SITE}/release/{release_id}/cover-art"]
    merged: List[str] = []
    seen = set()
    for url in seed + out:
        if url in seen:
            continue
        seen.add(url)
        merged.append(url)
    return merged


def try_release_page_by_id(
    release_id: str,
    out_path: Path,
    *,
    timeout: int,
    headers: Dict[str, str],
    min_size: int,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    had_error = False
    page_url = f"https://musicbrainz.org/release/{release_id}"
    try:
        html_text = http_text(page_url, timeout=timeout, headers=headers)
    except Exception:
        return None, True

    candidates = extract_release_page_image_urls(html_text, release_id)
    for url in candidates:
        ok, meta = download_image(url, out_path, timeout=timeout, headers=headers, min_size=min_size)
        if ok:
            return {
                "provider": "musicbrainz_release_page",
                "release_id": release_id,
                "page": page_url,
                "url": url,
                "width": meta.get("width"),
                "height": meta.get("height"),
            }, had_error
        if meta.get("reason") in {"download_error"}:
            had_error = True

    for cover_art_page in extract_release_cover_art_pages(html_text, release_id):
        try:
            cover_art_html = http_text(cover_art_page, timeout=timeout, headers=headers)
        except Exception:
            had_error = True
            continue
        page_candidates = extract_release_page_image_urls(cover_art_html, release_id)
        for url in page_candidates:
            ok, meta = download_image(url, out_path, timeout=timeout, headers=headers, min_size=min_size)
            if ok:
                return {
                    "provider": "musicbrainz_release_cover_art_page",
                    "release_id": release_id,
                    "page": cover_art_page,
                    "url": url,
                    "width": meta.get("width"),
                    "height": meta.get("height"),
                }, had_error
            if meta.get("reason") in {"download_error"}:
                had_error = True
    return None, had_error


def detect_album_title(album_dir: Path, catno: str) -> str:
    title = album_dir.name.strip()
    title = re.sub(r"^\[[^\]]+\]\s*", "", title)
    if catno:
        esc = re.escape(catno)
        title = re.sub(rf"^\(?{esc}\)?[\s\-_]*", "", title, flags=re.IGNORECASE)
    title = title.replace("_", " ")
    title = re.sub(r"\s+", " ", title).strip()
    return title


def image_size(path: Path) -> Optional[Tuple[int, int]]:
    try:
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
            if w > 0 and h > 0:
                return int(w), int(h)
    except Exception:
        pass

    try:
        p = subprocess.run(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if p.returncode == 0:
            w_m = re.search(r"pixelWidth:\s*(\d+)", p.stdout)
            h_m = re.search(r"pixelHeight:\s*(\d+)", p.stdout)
            if w_m and h_m:
                return int(w_m.group(1)), int(h_m.group(1))
    except Exception:
        pass

    try:
        p = subprocess.run(
            ["identify", "-format", "%w %h", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if p.returncode == 0:
            parts = p.stdout.strip().split()
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
    except Exception:
        pass

    return None


def download_image(
    url: str,
    out_path: Path,
    *,
    timeout: int,
    headers: Dict[str, str],
    min_size: int,
) -> Tuple[bool, Dict[str, Any]]:
    tmp_fd, tmp_name = tempfile.mkstemp(prefix="cover_online_", suffix=".img")
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)
    meta: Dict[str, Any] = {"url": url}
    try:
        payload, head = _http_bytes(url, timeout=timeout, headers=headers)
        content_type = (head.get("Content-Type") or "").lower()
        meta["content_type"] = content_type
        if content_type and not content_type.startswith("image/"):
            meta["reason"] = "not_image_content_type"
            return False, meta
        with tmp_path.open("wb") as f:
            f.write(payload)
        if tmp_path.stat().st_size <= 0:
            meta["reason"] = "empty_download"
            return False, meta

        size = image_size(tmp_path)
        if not size:
            meta["reason"] = "unknown_image_size"
            return False, meta
        w, h = size
        meta["width"] = w
        meta["height"] = h
        if w < min_size or h < min_size:
            meta["reason"] = "too_small"
            return False, meta

        tmp_path.replace(out_path)
        return True, meta
    except Exception as exc:
        meta["reason"] = "download_error"
        meta["error"] = str(exc)
        return False, meta
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def query_musicbrainz(
    catno: str, *, timeout: int, headers: Dict[str, str], limit: int
) -> Tuple[List[Dict[str, Any]], bool]:
    variants = [catno]
    compact = re.sub(r"\s+", "", catno)
    if compact and compact != catno:
        variants.append(compact)

    releases: List[Dict[str, Any]] = []
    had_error = False
    seen = set()
    for variant in variants:
        params = {
            "query": f'catno:"{variant}"',
            "fmt": "json",
            "limit": str(limit),
        }
        url = "https://musicbrainz.org/ws/2/release/?" + urllib.parse.urlencode(params)
        try:
            obj = http_json(url, timeout=timeout, headers=headers)
        except Exception:
            had_error = True
            continue
        for rel in obj.get("releases", []) or []:
            rid = rel.get("id")
            if not isinstance(rid, str) or rid in seen:
                continue
            seen.add(rid)
            releases.append(rel)
    return releases, had_error


def try_musicbrainz(
    catno: str,
    out_path: Path,
    *,
    timeout: int,
    headers: Dict[str, str],
    limit: int,
    min_size: int,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    releases, had_error = query_musicbrainz(catno, timeout=timeout, headers=headers, limit=limit)
    for rel in releases:
        rid = rel.get("id")
        if not isinstance(rid, str):
            continue
        for url in (
            f"https://coverartarchive.org/release/{rid}/front",
            f"https://coverartarchive.org/release/{rid}/front-1200",
            f"https://coverartarchive.org/release/{rid}/front-500",
        ):
            ok, meta = download_image(url, out_path, timeout=timeout, headers=headers, min_size=min_size)
            if ok:
                return {
                    "provider": "musicbrainz",
                    "release_id": rid,
                    "url": url,
                    "width": meta.get("width"),
                    "height": meta.get("height"),
                }, had_error
    return None, had_error


def musicbrainz_caa_endpoint(release_id: str) -> str:
    return f"https://coverartarchive.org/release/{release_id}"


def fetch_musicbrainz_caa_release_fast(
    release_id: str,
    *,
    timeout: int,
    headers: Dict[str, str],
) -> Tuple[Optional[Dict[str, Any]], bool]:
    url = musicbrainz_caa_endpoint(release_id)
    if shutil.which("curl"):
        try:
            obj = _curl_json(url, timeout=timeout, headers=headers)
            return obj, False
        except Exception:
            pass
    try:
        obj = http_json(url, timeout=timeout, headers=headers)
        if isinstance(obj, dict):
            return obj, False
        return None, False
    except Exception:
        return None, True


def _mb_image_type_set(img: Dict[str, Any]) -> set:
    out = set()
    types = img.get("types")
    if isinstance(types, list):
        for item in types:
            if isinstance(item, str) and item.strip():
                out.add(item.strip().lower())
    if img.get("front") is True:
        out.add("front")
    if img.get("back") is True:
        out.add("back")
    return out


def _mb_is_front(img: Dict[str, Any]) -> bool:
    return "front" in _mb_image_type_set(img)


def _mb_is_back(img: Dict[str, Any]) -> bool:
    return "back" in _mb_image_type_set(img)


def _mb_image_area(img: Dict[str, Any]) -> int:
    return max(0, _to_int(img.get("width"))) * max(0, _to_int(img.get("height")))


def _mb_image_url_candidates(
    img: Dict[str, Any],
    *,
    for_cover: bool,
    min_size: int,
) -> List[str]:
    thumbs = img.get("thumbnails")
    thumbs = thumbs if isinstance(thumbs, dict) else {}
    image_url = img.get("image") if isinstance(img.get("image"), str) else ""

    urls: List[str] = []
    if for_cover:
        # For cover we prefer medium-high URLs to reduce transfer while keeping >= min_size.
        if min_size <= 1200 and isinstance(thumbs.get("1200"), str):
            urls.append(thumbs["1200"])
        if min_size <= 500 and isinstance(thumbs.get("500"), str):
            urls.append(thumbs["500"])
        if isinstance(thumbs.get("large"), str):
            urls.append(thumbs["large"])
        if image_url:
            urls.append(image_url)
    else:
        # Back has no strict size rule in skill; prefer larger first.
        if isinstance(thumbs.get("1200"), str):
            urls.append(thumbs["1200"])
        if image_url:
            urls.append(image_url)
        for key in ("large", "500", "250", "small"):
            val = thumbs.get(key)
            if isinstance(val, str):
                urls.append(val)
    return dedupe_keep_order([u for u in urls if isinstance(u, str) and u])


def _mb_sorted_images(images: List[Any], *, role: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = [x for x in images if isinstance(x, dict)]
    if role == "front":
        picked = [x for x in rows if _mb_is_front(x)]
    elif role == "back":
        picked = [x for x in rows if _mb_is_back(x)]
    else:
        picked = rows
    picked.sort(key=lambda x: -_mb_image_area(x))
    return picked


def try_musicbrainz_back_from_caa_images(
    images: List[Any],
    *,
    cover_url: str,
    back_output: Optional[Path],
    timeout: int,
    headers: Dict[str, str],
) -> Tuple[Dict[str, Any], bool]:
    if not back_output:
        return {}, False
    had_error = False
    for img in _mb_sorted_images(images, role="back"):
        for candidate in _mb_image_url_candidates(img, for_cover=False, min_size=1):
            if candidate == cover_url:
                continue
            ok, meta = _download_image_curl(
                candidate,
                back_output,
                timeout=timeout,
                headers=headers,
                min_size=1,
            )
            if ok:
                return {
                    "back_url": candidate,
                    "back_width": meta.get("width"),
                    "back_height": meta.get("height"),
                    "back_output": str(back_output),
                }, had_error
            if meta.get("reason") == "download_error":
                had_error = True
    return {}, had_error


def _mb_is_hard_network_error(meta: Dict[str, Any]) -> bool:
    if meta.get("reason") != "download_error":
        return False
    err = str(meta.get("error") or "").lower()
    # Treat common HTTP client misses as non-network failures.
    for code in (" 400", " 401", " 403", " 404", " 405", " 410"):
        if code in err:
            return False
    if "the requested url returned error: 4" in err:
        return False
    return True


def _mb_release_art_urls(release_id: str, *, kind: str, min_size: int) -> List[str]:
    if kind == "front":
        return [f"https://coverartarchive.org/release/{release_id}/front"]
    if kind == "back":
        return [f"https://coverartarchive.org/release/{release_id}/back"]
    return []


def try_musicbrainz_by_release_id_fast_json(
    release_id: str,
    out_path: Path,
    *,
    timeout: int,
    headers: Dict[str, str],
    min_size: int,
    back_output: Optional[Path],
) -> Tuple[Optional[Dict[str, Any]], bool, bool]:
    rel, had_error = fetch_musicbrainz_caa_release_fast(
        release_id,
        timeout=timeout,
        headers=headers,
    )
    if not rel:
        return None, had_error, False

    images = rel.get("images", [])
    if not isinstance(images, list):
        return None, had_error, True

    front_images = _mb_sorted_images(images, role="front")
    if not front_images:
        front_images = _mb_sorted_images(images, role="any")

    for img in front_images:
        if _to_int(img.get("width")) > 0 and _to_int(img.get("height")) > 0:
            if _to_int(img.get("width")) < min_size or _to_int(img.get("height")) < min_size:
                continue
        for candidate in _mb_image_url_candidates(img, for_cover=True, min_size=min_size):
            ok, meta = _download_image_curl(
                candidate,
                out_path,
                timeout=timeout,
                headers=headers,
                min_size=min_size,
            )
            if not ok:
                if _mb_is_hard_network_error(meta):
                    had_error = True
                continue

            payload: Dict[str, Any] = {
                "provider": "musicbrainz_release_id",
                "release_id": release_id,
                "url": candidate,
                "width": meta.get("width"),
                "height": meta.get("height"),
                "fetch_mode": "fast",
            }
            back_payload, back_error = try_musicbrainz_back_from_caa_images(
                images,
                cover_url=candidate,
                back_output=back_output,
                timeout=timeout,
                headers=headers,
            )
            had_error = had_error or back_error
            payload.update(back_payload)
            return payload, had_error, True

    return None, had_error, True


def try_musicbrainz_by_release_id_fast(
    release_id: str,
    out_path: Path,
    *,
    timeout: int,
    headers: Dict[str, str],
    min_size: int,
    back_output: Optional[Path],
    allow_json_fallback: bool,
) -> Tuple[Optional[Dict[str, Any]], bool, bool]:
    had_error = False
    timeout_cap = 4
    cap_raw = str(os.environ.get("WHITEBULL_MB_TIMEOUT_CAP", "")).strip()
    if cap_raw:
        try:
            timeout_cap = max(1, int(cap_raw))
        except Exception:
            timeout_cap = 4
    mb_timeout = max(1, min(int(timeout), timeout_cap))

    for candidate in _mb_release_art_urls(release_id, kind="front", min_size=min_size):
        ok, meta = _download_image_curl(
            candidate,
            out_path,
            timeout=mb_timeout,
            headers=headers,
            min_size=min_size,
        )
        if not ok:
            if _mb_is_hard_network_error(meta):
                had_error = True
            continue

        payload: Dict[str, Any] = {
            "provider": "musicbrainz_release_id",
            "release_id": release_id,
            "url": candidate,
            "width": meta.get("width"),
            "height": meta.get("height"),
            "fetch_mode": "fast",
        }
        if back_output:
            for back_url in _mb_release_art_urls(release_id, kind="back", min_size=1):
                back_ok, back_meta = _download_image_curl(
                    back_url,
                    back_output,
                    timeout=mb_timeout,
                    headers=headers,
                    min_size=1,
                )
                if back_ok:
                    payload.update(
                        {
                            "back_url": back_url,
                            "back_width": back_meta.get("width"),
                            "back_height": back_meta.get("height"),
                            "back_output": str(back_output),
                        }
                    )
                    break
                if _mb_is_hard_network_error(back_meta):
                    had_error = True
        return payload, had_error, True

    # Fallback for releases where CAA has images but no /front endpoint.
    # Skip when hard network errors already happened to keep failure path fast.
    raw_fallback = str(os.environ.get("WHITEBULL_MB_JSON_FALLBACK", "")).strip().lower()
    enable_json_fallback = allow_json_fallback and raw_fallback in {"1", "true", "yes", "on"}
    if enable_json_fallback and not had_error:
        json_hit, json_error, json_resolved = try_musicbrainz_by_release_id_fast_json(
            release_id,
            out_path,
            timeout=mb_timeout,
            headers=headers,
            min_size=min_size,
            back_output=back_output,
        )
        if json_hit:
            return json_hit, (had_error or json_error), True
        return None, (had_error or json_error), json_resolved

    return None, had_error, True


def try_musicbrainz_by_release_id(
    release_id: str,
    out_path: Path,
    *,
    timeout: int,
    headers: Dict[str, str],
    min_size: int,
    back_output: Optional[Path],
    allow_json_fallback: bool,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    fast_hit, fast_err, fast_resolved = try_musicbrainz_by_release_id_fast(
        release_id,
        out_path,
        timeout=timeout,
        headers=headers,
        min_size=min_size,
        back_output=back_output,
        allow_json_fallback=allow_json_fallback,
    )
    if fast_hit:
        return fast_hit, fast_err
    # CAA is authoritative for MB cover art; avoid expensive page crawling fallback.
    # When fetch failed due network, outer proxy-attempt loop will retry quickly.
    _ = fast_resolved
    return None, fast_err


def query_discogs(
    catno: str,
    *,
    timeout: int,
    headers: Dict[str, str],
    token: str,
    limit: int,
) -> Tuple[List[Dict[str, Any]], bool]:
    params = {
        "catno": catno,
        "type": "release",
        "per_page": str(limit),
    }
    if token:
        params["token"] = token
    url = "https://api.discogs.com/database/search?" + urllib.parse.urlencode(params)
    try:
        obj = http_json(url, timeout=timeout, headers=headers)
    except Exception:
        return [], True
    rows = obj.get("results", [])
    return (rows if isinstance(rows, list) else []), False


def discogs_release_endpoint(release_id: str, token: str) -> str:
    base = f"https://api.discogs.com/releases/{release_id}"
    if not token:
        return base
    return base + "?" + urllib.parse.urlencode({"token": token})


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _curl_cmd_base(
    *,
    timeout: int,
    headers: Dict[str, str],
    capture_headers_path: Optional[Path] = None,
) -> List[str]:
    cmd = ["curl", "-LfsS", "--max-time", str(max(1, int(timeout)))]
    if NETWORK_PROXY:
        cmd.extend(["--proxy", NETWORK_PROXY])
    if NETWORK_RETRIES > 1:
        # Retry count is "extra tries after the first request".
        # With default NETWORK_RETRIES=3 => first try + 3 retries.
        cmd.extend(
            [
                "--retry",
                str(max(1, NETWORK_RETRIES)),
                "--retry-delay",
                "0",
                "--retry-all-errors",
                "--retry-connrefused",
            ]
        )
    for k, v in headers.items():
        if k and v:
            cmd.extend(["-H", f"{k}: {v}"])
    if capture_headers_path is not None:
        cmd.extend(["-D", str(capture_headers_path)])
    return cmd


def _curl_json(
    url: str,
    *,
    timeout: int,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    cmd = _curl_cmd_base(timeout=timeout, headers=headers)
    cmd.append(url)
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or f"curl_exit_{p.returncode}")
    obj = json.loads(p.stdout)
    if not isinstance(obj, dict):
        raise RuntimeError("curl_json_not_object")
    return obj


def _discogs_image_records(images: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for img in images:
        if not isinstance(img, dict):
            continue
        uri = img.get("uri")
        if not isinstance(uri, str) or not uri:
            continue
        out.append(
            {
                "url": uri,
                "type": str(img.get("type") or ""),
                "width": _to_int(img.get("width")),
                "height": _to_int(img.get("height")),
            }
        )
    return out


def _discogs_cover_candidates(images: List[Any], *, min_size: int) -> List[Dict[str, Any]]:
    rows = _discogs_image_records(images)
    eligible = [r for r in rows if r["width"] >= min_size and r["height"] >= min_size]
    # Prefer primary art first, then larger area.
    eligible.sort(
        key=lambda r: (
            0 if r.get("type") == "primary" else 1,
            -(int(r.get("width", 0)) * int(r.get("height", 0))),
        )
    )
    return eligible


def _discogs_back_candidates(images: List[Any], *, cover_url: str) -> List[Dict[str, Any]]:
    rows = [r for r in _discogs_image_records(images) if r.get("url") != cover_url]
    # Prefer secondary back-like pages first, then larger area.
    rows.sort(
        key=lambda r: (
            0 if r.get("type") == "secondary" else 1,
            -(int(r.get("width", 0)) * int(r.get("height", 0))),
        )
    )
    return rows


def _download_image_curl(
    url: str,
    out_path: Path,
    *,
    timeout: int,
    headers: Dict[str, str],
    min_size: int,
) -> Tuple[bool, Dict[str, Any]]:
    tmp_fd, tmp_name = tempfile.mkstemp(prefix="cover_online_", suffix=".img")
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)
    hdr_fd, hdr_name = tempfile.mkstemp(prefix="cover_online_head_", suffix=".txt")
    os.close(hdr_fd)
    hdr_path = Path(hdr_name)
    meta: Dict[str, Any] = {"url": url}
    try:
        cmd = _curl_cmd_base(timeout=timeout, headers=headers, capture_headers_path=hdr_path)
        cmd.extend(["-o", str(tmp_path), url])
        p = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if p.returncode != 0:
            meta["reason"] = "download_error"
            meta["error"] = p.stderr.strip() or f"curl_exit_{p.returncode}"
            return False, meta

        if hdr_path.exists():
            try:
                # curl -L -D includes headers for all redirect hops.
                # Use the last Content-Type (final response) to avoid false rejections.
                content_types: List[str] = []
                for line in hdr_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.lower().startswith("content-type:"):
                        content_type = line.split(":", 1)[1].strip().lower()
                        if content_type:
                            content_types.append(content_type)
                if content_types:
                    final_content_type = content_types[-1]
                    meta["content_type"] = final_content_type
                    if not final_content_type.startswith("image/"):
                        meta["reason"] = "not_image_content_type"
                        return False, meta
            except Exception:
                pass

        if not tmp_path.exists() or tmp_path.stat().st_size <= 0:
            meta["reason"] = "empty_download"
            return False, meta

        size = image_size(tmp_path)
        if not size:
            meta["reason"] = "unknown_image_size"
            return False, meta
        w, h = size
        meta["width"] = w
        meta["height"] = h
        if w < min_size or h < min_size:
            meta["reason"] = "too_small"
            return False, meta

        tmp_path.replace(out_path)
        return True, meta
    except Exception as exc:
        meta["reason"] = "download_error"
        meta["error"] = str(exc)
        return False, meta
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        try:
            if hdr_path.exists():
                hdr_path.unlink()
        except OSError:
            pass


def fetch_discogs_release(
    release_id: str,
    *,
    timeout: int,
    headers: Dict[str, str],
    token: str,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    try:
        rel = http_json(
            discogs_release_endpoint(release_id, token),
            timeout=timeout,
            headers=headers,
        )
        if isinstance(rel, dict):
            return rel, False
        return None, False
    except Exception:
        return None, True


def fetch_discogs_release_fast(
    release_id: str,
    *,
    timeout: int,
    headers: Dict[str, str],
    token: str,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    # Fast path relies on curl transport performance; fallback logic remains intact.
    if not shutil.which("curl"):
        return None, False
    try:
        rel = _curl_json(
            discogs_release_endpoint(release_id, token),
            timeout=timeout,
            headers=headers,
        )
        return rel, False
    except Exception:
        return None, True


def try_discogs_by_release_id_fast(
    release_id: str,
    out_path: Path,
    *,
    timeout: int,
    headers: Dict[str, str],
    token: str,
    min_size: int,
    back_output: Optional[Path],
) -> Tuple[Optional[Dict[str, Any]], bool]:
    rel, had_error = fetch_discogs_release_fast(
        release_id,
        timeout=timeout,
        headers=headers,
        token=token,
    )
    if not rel:
        return None, had_error
    images = rel.get("images", [])
    if not isinstance(images, list):
        return None, had_error

    for row in _discogs_cover_candidates(images, min_size=min_size):
        candidate = str(row.get("url") or "")
        if not candidate:
            continue
        ok, meta = _download_image_curl(
            candidate,
            out_path,
            timeout=timeout,
            headers=headers,
            min_size=min_size,
        )
        if not ok:
            if meta.get("reason") in {"download_error"}:
                had_error = True
            continue
        payload: Dict[str, Any] = {
            "provider": "discogs_release_id",
            "release_id": release_id,
            "url": candidate,
            "width": meta.get("width"),
            "height": meta.get("height"),
            "fetch_mode": "fast",
        }
        if back_output:
            for back_row in _discogs_back_candidates(images, cover_url=candidate):
                back_url = str(back_row.get("url") or "")
                if not back_url:
                    continue
                back_ok, back_meta = _download_image_curl(
                    back_url,
                    back_output,
                    timeout=timeout,
                    headers=headers,
                    min_size=1,
                )
                if back_ok:
                    payload.update(
                        {
                            "back_url": back_url,
                            "back_width": back_meta.get("width"),
                            "back_height": back_meta.get("height"),
                            "back_output": str(back_output),
                        }
                    )
                    break
                if back_meta.get("reason") in {"download_error"}:
                    had_error = True
        return payload, had_error
    return None, had_error


def discogs_image_urls(
    images: List[Any],
    *,
    primary_first: bool,
) -> List[str]:
    def _sort_key(item: Any) -> int:
        if not isinstance(item, dict):
            return 2
        is_primary = item.get("type") == "primary"
        if primary_first:
            return 0 if is_primary else 1
        return 0 if not is_primary else 1

    ordered = sorted(images, key=_sort_key)
    out: List[str] = []
    for img in ordered:
        if not isinstance(img, dict):
            continue
        for key in ("uri", "uri150"):
            url = img.get(key)
            if isinstance(url, str) and url:
                out.append(url)
    return dedupe_keep_order(out)


def try_discogs_back_from_release(
    release: Dict[str, Any],
    *,
    cover_url: str,
    back_output: Optional[Path],
    timeout: int,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    if not back_output:
        return {}
    images = release.get("images", [])
    if not isinstance(images, list):
        return {}
    for candidate in discogs_image_urls(images, primary_first=False):
        if candidate == cover_url:
            continue
        ok, meta = download_image(
            candidate,
            back_output,
            timeout=timeout,
            headers=headers,
            min_size=1,
        )
        if ok:
            return {
                "back_url": candidate,
                "back_width": meta.get("width"),
                "back_height": meta.get("height"),
                "back_output": str(back_output),
            }
    return {}


def try_discogs_by_release_id(
    release_id: str,
    out_path: Path,
    *,
    timeout: int,
    headers: Dict[str, str],
    token: str,
    min_size: int,
    back_output: Optional[Path],
) -> Tuple[Optional[Dict[str, Any]], bool]:
    fast_hit, fast_err = try_discogs_by_release_id_fast(
        release_id,
        out_path,
        timeout=timeout,
        headers=headers,
        token=token,
        min_size=min_size,
        back_output=back_output,
    )
    if fast_hit:
        return fast_hit, fast_err

    rel, had_error = fetch_discogs_release(
        release_id,
        timeout=timeout,
        headers=headers,
        token=token,
    )
    had_error = had_error or fast_err
    if not rel:
        return None, had_error

    images = rel.get("images", [])
    if not isinstance(images, list):
        return None, had_error

    for candidate in discogs_image_urls(images, primary_first=True):
        ok, meta = download_image(
            candidate,
            out_path,
            timeout=timeout,
            headers=headers,
            min_size=min_size,
        )
        if ok:
            payload: Dict[str, Any] = {
                "provider": "discogs_release_id",
                "release_id": release_id,
                "url": candidate,
                "width": meta.get("width"),
                "height": meta.get("height"),
            }
            payload.update(
                try_discogs_back_from_release(
                    rel,
                    cover_url=candidate,
                    back_output=back_output,
                    timeout=timeout,
                    headers=headers,
                )
            )
            return payload, had_error
    return None, had_error


def try_discogs(
    catno: str,
    out_path: Path,
    *,
    timeout: int,
    headers: Dict[str, str],
    token: str,
    limit: int,
    min_size: int,
    back_output: Optional[Path],
) -> Tuple[Optional[Dict[str, Any]], bool]:
    results, had_error = query_discogs(catno, timeout=timeout, headers=headers, token=token, limit=limit)
    for row in results:
        cover_url = row.get("cover_image")
        rid_raw = row.get("id")
        rid = str(rid_raw) if rid_raw is not None else ""
        if isinstance(cover_url, str) and cover_url:
            ok, meta = download_image(cover_url, out_path, timeout=timeout, headers=headers, min_size=min_size)
            if ok:
                payload: Dict[str, Any] = {
                    "provider": "discogs",
                    "release_id": rid,
                    "url": cover_url,
                    "width": meta.get("width"),
                    "height": meta.get("height"),
                }
                if rid:
                    rel, rel_err = fetch_discogs_release(
                        rid,
                        timeout=timeout,
                        headers=headers,
                        token=token,
                    )
                    if rel_err:
                        had_error = True
                    if rel:
                        payload.update(
                            try_discogs_back_from_release(
                                rel,
                                cover_url=cover_url,
                                back_output=back_output,
                                timeout=timeout,
                                headers=headers,
                            )
                        )
                return payload, had_error

        if not rid:
            continue
        hit, rel_err = try_discogs_by_release_id(
            rid,
            out_path,
            timeout=timeout,
            headers=headers,
            token=token,
            min_size=min_size,
            back_output=back_output,
        )
        had_error = had_error or rel_err
        if hit:
            if hit.get("provider") == "discogs_release_id":
                hit["provider"] = "discogs"
            return hit, had_error
    return None, had_error

def extract_amazon_image_urls(html: str) -> List[str]:
    urls = re.findall(r"https://m\.media-amazon\.com/images/I/[A-Za-z0-9%._+\-]+\.jpg", html)
    normed: List[str] = []
    for raw in urls:
        url = urllib.parse.unquote(raw)
        # Remove Amazon resize suffix to try original quality.
        url = re.sub(r"\._[^.]+(?=\.jpg$)", "", url)
        normed.append(url)
    return dedupe_keep_order(normed)


def extract_ebay_image_urls(html: str) -> List[str]:
    urls = re.findall(r"https://i\.ebayimg\.com/images/[A-Za-z0-9%._+\-/:]+", html)
    escaped = re.findall(r"https:\\/\\/i\\.ebayimg\\.com\\/images\\/[A-Za-z0-9%._+\-/:\\\\]+", html)
    for esc in escaped:
        urls.append(esc.replace("\\/", "/").replace("\\", ""))

    normed: List[str] = []
    for url in urls:
        url = url.split("?")[0]
        url = re.sub(r"s-l\d+(\.[A-Za-z0-9]+)$", r"s-l1600\1", url)
        normed.append(url)
    return dedupe_keep_order(normed)


def build_queries(catno: str, title: str) -> List[str]:
    queries = [
        f"{catno} {title} cd",
        f'"{catno}" {title}',
        f"{catno} classical cd",
        f"{catno} philips cd",
    ]
    if title:
        queries.append(f"{title} cd")
    return dedupe_keep_order([q.strip() for q in queries if q.strip()])


def try_amazon(
    *,
    catno: str,
    title: str,
    out_path: Path,
    timeout: int,
    headers: Dict[str, str],
    limit: int,
    min_size: int,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    had_error = False
    for query in build_queries(catno, title):
        search_url = "https://www.amazon.com/s?" + urllib.parse.urlencode({"k": query})
        try:
            html = http_text(search_url, timeout=timeout, headers=headers)
        except Exception:
            had_error = True
            continue
        candidates = extract_amazon_image_urls(html)[: limit * 8]
        for image_url in candidates:
            ok, meta = download_image(image_url, out_path, timeout=timeout, headers=headers, min_size=min_size)
            if ok:
                return {
                    "provider": "amazon",
                    "query": query,
                    "url": image_url,
                    "width": meta.get("width"),
                    "height": meta.get("height"),
                }, had_error
    return None, had_error


def try_ebay(
    *,
    catno: str,
    title: str,
    out_path: Path,
    timeout: int,
    headers: Dict[str, str],
    limit: int,
    min_size: int,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    had_error = False
    for query in build_queries(catno, title):
        search_url = "https://www.ebay.com/sch/i.html?" + urllib.parse.urlencode({"_nkw": query})
        try:
            html = http_text(search_url, timeout=timeout, headers=headers)
        except Exception:
            had_error = True
            continue
        candidates = extract_ebay_image_urls(html)[: limit * 8]
        for image_url in candidates:
            ok, meta = download_image(image_url, out_path, timeout=timeout, headers=headers, min_size=min_size)
            if ok:
                return {
                    "provider": "ebay",
                    "query": query,
                    "url": image_url,
                    "width": meta.get("width"),
                    "height": meta.get("height"),
                }, had_error
    return None, had_error


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch cover image by catalog number and album title.")
    parser.add_argument("--album-dir", required=True, help="Album directory")
    parser.add_argument(
        "--release-id",
        default="",
        help="MusicBrainz MBID/release URL or Discogs release id/release URL (optional, preferred when known)",
    )
    parser.add_argument("--catalog-number", default="", help="Catalog number (optional)")
    parser.add_argument("--output", default="", help="Output jpg path (default: <album>/cover_online.jpg)")
    parser.add_argument("--back-output", default="", help="Optional back image output path")
    parser.add_argument("--proxy", default="", help="Optional outbound proxy URL, e.g. http://127.0.0.1:7890")
    parser.add_argument(
        "--auto-proxy",
        dest="auto_proxy",
        action="store_true",
        default=True,
        help="Auto-try proxy fallbacks when direct network is unreachable (default: on)",
    )
    parser.add_argument(
        "--no-auto-proxy",
        dest="auto_proxy",
        action="store_false",
        help="Disable automatic proxy fallback",
    )
    parser.add_argument("--timeout", type=int, default=8, help="HTTP timeout seconds")
    parser.add_argument("--probe-timeout", type=int, default=2, help="Connectivity precheck timeout seconds")
    parser.add_argument("--network-retries", type=int, default=3, help="Per-request retry count")
    parser.add_argument("--network-backoff", type=float, default=0.35, help="Retry backoff base seconds")
    parser.add_argument("--limit", type=int, default=6, help="Max results per provider")
    parser.add_argument("--min-size", type=int, default=550, help="Minimum width/height in pixels")
    args = parser.parse_args()

    album_dir = Path(args.album_dir).expanduser().resolve()
    if not album_dir.is_dir():
        print(json.dumps({"ok": False, "reason": "album_dir_missing"}))
        return 2

    output = Path(args.output).expanduser().resolve() if args.output else album_dir / "cover_online.jpg"
    back_output = Path(args.back_output).expanduser().resolve() if args.back_output else None
    release_provider, release_id = parse_release_ref(args.release_id)
    catno = detect_catalog_number(album_dir, args.catalog_number)
    if not release_id and not catno:
        print(json.dumps({"ok": False, "reason": "release_id_or_catalog_number_missing"}))
        return 3
    title = detect_album_title(album_dir, catno)

    ua = os.environ.get("MUSICBRAINZ_USER_AGENT", DEFAULT_UA)
    headers = {
        "User-Agent": ua,
        "Accept-Encoding": "identity",
        "Accept-Language": "en-US,en;q=0.8",
    }
    discogs_token = os.environ.get("DISCOGS_TOKEN", "").strip()
    set_network_profile("", retries=args.network_retries, backoff=args.network_backoff)

    def run_lookup_once(*, allow_release_json_fallback: bool) -> Dict[str, Any]:
        release_hit = None
        release_error = False
        if release_id:
            if release_provider == "discogs":
                release_hit, release_error = try_discogs_by_release_id(
                    release_id,
                    output,
                    timeout=args.timeout,
                    headers=headers,
                    token=discogs_token,
                    min_size=args.min_size,
                    back_output=back_output,
                )
            else:
                release_hit, release_error = try_musicbrainz_by_release_id(
                    release_id,
                    output,
                    timeout=args.timeout,
                    headers=headers,
                    min_size=args.min_size,
                    back_output=back_output,
                    allow_json_fallback=allow_release_json_fallback,
                )
            if release_hit:
                payload = {
                    "ok": True,
                    "provider": release_hit["provider"],
                    "catalog_number": catno,
                    "album_title": title,
                    "output": str(output),
                    "url": release_hit["url"],
                    "release_id": release_hit.get("release_id"),
                    "width": release_hit.get("width"),
                    "height": release_hit.get("height"),
                }
                if release_hit.get("fetch_mode"):
                    payload["fetch_mode"] = release_hit.get("fetch_mode")
                if release_hit.get("back_url"):
                    payload["back_url"] = release_hit.get("back_url")
                    payload["back_output"] = release_hit.get("back_output")
                    payload["back_width"] = release_hit.get("back_width")
                    payload["back_height"] = release_hit.get("back_height")
                return payload

        mb_hit = None
        mb_error = False
        if catno:
            mb_hit, mb_error = try_musicbrainz(
                catno,
                output,
                timeout=args.timeout,
                headers=headers,
                limit=args.limit,
                min_size=args.min_size,
            )
            if mb_hit:
                return {
                    "ok": True,
                    "provider": mb_hit["provider"],
                    "catalog_number": catno,
                    "album_title": title,
                    "output": str(output),
                    "url": mb_hit["url"],
                    "release_id": mb_hit.get("release_id"),
                    "width": mb_hit.get("width"),
                    "height": mb_hit.get("height"),
                }

        discogs_hit = None
        discogs_error = False
        if catno:
            discogs_hit, discogs_error = try_discogs(
                catno,
                output,
                timeout=args.timeout,
                headers=headers,
                token=discogs_token,
                limit=args.limit,
                min_size=args.min_size,
                back_output=back_output,
            )
        if discogs_hit:
            payload = {
                "ok": True,
                "provider": discogs_hit["provider"],
                "catalog_number": catno,
                "album_title": title,
                "output": str(output),
                "url": discogs_hit["url"],
                "release_id": discogs_hit.get("release_id"),
                "width": discogs_hit.get("width"),
                "height": discogs_hit.get("height"),
            }
            if discogs_hit.get("back_url"):
                payload["back_url"] = discogs_hit.get("back_url")
                payload["back_output"] = discogs_hit.get("back_output")
                payload["back_width"] = discogs_hit.get("back_width")
                payload["back_height"] = discogs_hit.get("back_height")
            return payload

        amazon_hit = None
        amazon_error = False
        if catno:
            amazon_hit, amazon_error = try_amazon(
                catno=catno,
                title=title,
                out_path=output,
                timeout=args.timeout,
                headers=headers,
                limit=args.limit,
                min_size=args.min_size,
            )
        if amazon_hit:
            return {
                "ok": True,
                "provider": amazon_hit["provider"],
                "catalog_number": catno,
                "album_title": title,
                "output": str(output),
                "url": amazon_hit["url"],
                "query": amazon_hit.get("query"),
                "width": amazon_hit.get("width"),
                "height": amazon_hit.get("height"),
            }

        ebay_hit = None
        ebay_error = False
        if catno:
            ebay_hit, ebay_error = try_ebay(
                catno=catno,
                title=title,
                out_path=output,
                timeout=args.timeout,
                headers=headers,
                limit=args.limit,
                min_size=args.min_size,
            )
        if ebay_hit:
            return {
                "ok": True,
                "provider": ebay_hit["provider"],
                "catalog_number": catno,
                "album_title": title,
                "output": str(output),
                "url": ebay_hit["url"],
                "query": ebay_hit.get("query"),
                "width": ebay_hit.get("width"),
                "height": ebay_hit.get("height"),
            }

        reason = (
            "online_lookup_unreachable"
            if (release_error or mb_error or discogs_error or amazon_error or ebay_error)
            else "online_cover_not_found"
        )
        return {
            "ok": False,
            "reason": reason,
            "catalog_number": catno,
            "album_title": title,
            "min_size": args.min_size,
        }

    proxies = proxy_candidates(args.proxy, auto_proxy=args.auto_proxy)
    attempts: List[Tuple[str, str]] = []
    direct_skipped = False
    mb_force_proxy = (release_provider == "musicbrainz" and bool(release_id) and bool(proxies))

    if not mb_force_proxy and proxies and args.probe_timeout > 0:
        set_network_profile("", retries=1, backoff=0.0)
        if not network_profile_reachable(
            release_provider=release_provider,
            release_id=release_id,
            catno=catno,
            timeout=args.probe_timeout,
            headers=headers,
        ):
            direct_skipped = True
    set_network_profile("", retries=args.network_retries, backoff=args.network_backoff)

    if mb_force_proxy:
        # For explicit MusicBrainz release-id lookups, go proxy-first directly.
        attempts.extend((proxy, "proxy") for proxy in proxies)
    else:
        if not direct_skipped:
            attempts.append(("", "direct"))
        attempts.extend((proxy, "proxy") for proxy in proxies)
    if not attempts:
        attempts.append(("", "direct"))

    last_failure: Dict[str, Any] = {}
    attempted_paths: List[str] = []
    for idx, (proxy, path_name) in enumerate(attempts):
        set_network_profile(proxy, retries=args.network_retries, backoff=args.network_backoff)
        attempted_paths.append(proxy if proxy else "direct")

        payload = run_lookup_once(allow_release_json_fallback=((idx + 1) == len(attempts)))
        if payload.get("ok"):
            payload["network_path"] = path_name if proxy else "direct"
            if proxy:
                payload["network_proxy"] = proxy
            if direct_skipped:
                payload["network_direct_skipped_by_probe"] = True
            print(json.dumps(payload, ensure_ascii=False))
            return 0

        last_failure = payload
        # Proxy fallback only helps connectivity failures.
        if payload.get("reason") != "online_lookup_unreachable":
            # For explicit release-id lookups, different network paths may still yield different results.
            # Continue trying remaining attempts on "not found" before giving up.
            if (
                release_id
                and payload.get("reason") == "online_cover_not_found"
                and (idx + 1) < len(attempts)
            ):
                continue
            break

    if not last_failure:
        last_failure = {
            "ok": False,
            "reason": "online_lookup_unreachable",
            "catalog_number": catno,
            "album_title": title,
            "min_size": args.min_size,
        }
    if direct_skipped:
        last_failure["network_direct_skipped_by_probe"] = True
    last_failure["network_attempts"] = attempted_paths
    print(json.dumps(last_failure, ensure_ascii=False))
    return 4


if __name__ == "__main__":
    sys.exit(main())
