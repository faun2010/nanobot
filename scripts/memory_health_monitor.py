#!/usr/bin/env python3
"""Monitor nanobot memory/session health from local files."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]")


@dataclass
class Metric:
    name: str
    status: str
    summary: str


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pick_nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default


def _resolve_defaults(config_path: Path) -> tuple[Path, Path, int]:
    cfg = _load_json(config_path)

    workspace = _pick_nested(cfg, "agents", "defaults", "workspace")
    workspace_path = Path(workspace).expanduser() if isinstance(workspace, str) else Path.home() / ".nanobot" / "workspace"

    sessions_path = Path.home() / ".nanobot" / "sessions"

    memory_window = _pick_nested(cfg, "agents", "defaults", "memory_window")
    if memory_window is None:
        memory_window = _pick_nested(cfg, "agents", "defaults", "memoryWindow")
    try:
        memory_window_int = int(memory_window) if memory_window is not None else 50
    except Exception:
        memory_window_int = 50

    return workspace_path, sessions_path, memory_window_int


def _parse_history_entries(history_text: str) -> list[str]:
    return [block.strip() for block in history_text.split("\n\n") if block.strip()]


def _entry_time(entry: str) -> datetime | None:
    m = TS_RE.match(entry)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _count_messages(jsonl_path: Path) -> tuple[int | None, str | None]:
    try:
        total = 0
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if isinstance(data, dict) and data.get("_type") == "metadata":
                    continue
                total += 1
        return total, None
    except Exception as e:
        return None, str(e)


def _status(ok: bool) -> str:
    return "OK" if ok else "WARN"


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor nanobot memory/session health")
    parser.add_argument("--config", default=str(Path.home() / ".nanobot" / "config.json"))
    parser.add_argument("--workspace", default=None, help="Override workspace path")
    parser.add_argument("--sessions-dir", default=None, help="Override sessions dir")
    parser.add_argument("--memory-window", type=int, default=None, help="Override memory window threshold")
    parser.add_argument("--hours", type=int, default=24, help="Freshness window for history entries")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    default_workspace, default_sessions, default_window = _resolve_defaults(config_path)

    workspace = Path(args.workspace).expanduser() if args.workspace else default_workspace
    sessions_dir = Path(args.sessions_dir).expanduser() if args.sessions_dir else default_sessions
    memory_window = args.memory_window if args.memory_window is not None else default_window

    memory_file = workspace / "memory" / "MEMORY.md"
    history_file = workspace / "memory" / "HISTORY.md"
    now = datetime.now()
    cutoff = now - timedelta(hours=args.hours)

    metrics: list[Metric] = []
    raw: dict[str, Any] = {
        "generated_at": now.isoformat(timespec="seconds"),
        "workspace": str(workspace),
        "sessions_dir": str(sessions_dir),
        "memory_window": memory_window,
    }

    memory_exists = memory_file.exists()
    history_exists = history_file.exists()
    memory_non_empty = memory_exists and bool(memory_file.read_text(encoding="utf-8").strip())
    history_entries = _parse_history_entries(history_file.read_text(encoding="utf-8")) if history_exists else []
    recent_entries = 0
    for entry in history_entries:
        ts = _entry_time(entry)
        if ts and ts >= cutoff:
            recent_entries += 1

    integrity_ok = memory_exists and history_exists and memory_non_empty and recent_entries > 0
    metrics.append(
        Metric(
            name="memory_file_integrity",
            status=_status(integrity_ok),
            summary=(
                f"memory_exists={memory_exists}, history_exists={history_exists}, "
                f"memory_non_empty={memory_non_empty}, recent_history_entries_{args.hours}h={recent_entries}"
            ),
        )
    )
    raw["memory_file_integrity"] = {
        "memory_exists": memory_exists,
        "history_exists": history_exists,
        "memory_non_empty": memory_non_empty,
        "recent_history_entries": recent_entries,
        "window_hours": args.hours,
        "status": _status(integrity_ok),
    }

    session_counts: dict[str, int] = {}
    parse_errors: dict[str, str] = {}
    if sessions_dir.exists():
        for jsonl in sessions_dir.glob("*.jsonl"):
            count, error = _count_messages(jsonl)
            key = jsonl.stem
            if error is not None:
                parse_errors[key] = error
            elif count is not None:
                session_counts[key] = count

    oversized_threshold = memory_window * 3
    oversized = {k: v for k, v in session_counts.items() if v > oversized_threshold}
    max_session = max(session_counts.values()) if session_counts else 0
    oversized_ok = len(oversized) == 0
    metrics.append(
        Metric(
            name="oversized_sessions",
            status=_status(oversized_ok),
            summary=(
                f"total_sessions={len(session_counts)}, max_messages={max_session}, "
                f"threshold={oversized_threshold}, oversized_count={len(oversized)}"
            ),
        )
    )
    raw["oversized_sessions"] = {
        "total_sessions": len(session_counts),
        "max_messages": max_session,
        "threshold": oversized_threshold,
        "oversized_count": len(oversized),
        "top_oversized": sorted(oversized.items(), key=lambda x: x[1], reverse=True)[:5],
        "status": _status(oversized_ok),
    }

    parse_ok = len(parse_errors) == 0
    metrics.append(
        Metric(
            name="session_jsonl_parse",
            status=_status(parse_ok),
            summary=f"parse_errors={len(parse_errors)}",
        )
    )
    raw["session_jsonl_parse"] = {
        "parse_errors": parse_errors,
        "status": _status(parse_ok),
    }

    fallback_entries = [e for e in history_entries if "Consolidation fallback" in e]
    total_entries = len(history_entries)
    ratio = (len(fallback_entries) / total_entries) if total_entries else 0.0
    fallback_ok = ratio <= 0.10
    metrics.append(
        Metric(
            name="history_fallback_ratio",
            status=_status(fallback_ok),
            summary=f"fallback={len(fallback_entries)}/{total_entries} ({ratio:.1%}), threshold=10.0%",
        )
    )
    raw["history_fallback_ratio"] = {
        "fallback_entries": len(fallback_entries),
        "total_entries": total_entries,
        "ratio": ratio,
        "threshold": 0.10,
        "status": _status(fallback_ok),
    }

    warnings = [m for m in metrics if m.status == "WARN"]
    raw["status"] = "WARN" if warnings else "OK"

    if args.json:
        print(json.dumps(raw, ensure_ascii=False, indent=2))
    else:
        print("nanobot Memory Health Monitor")
        print(f"generated_at: {raw['generated_at']}")
        print(f"workspace: {workspace}")
        print(f"sessions_dir: {sessions_dir}")
        print(f"memory_window: {memory_window}")
        print()
        for m in metrics:
            print(f"[{m.status}] {m.name}: {m.summary}")
        if oversized:
            print()
            print("Top oversized sessions:")
            for key, count in sorted(oversized.items(), key=lambda x: x[1], reverse=True)[:5]:
                print(f"- {key}: {count} messages")
        if parse_errors:
            print()
            print("Session parse errors:")
            for key, err in parse_errors.items():
                print(f"- {key}: {err}")

    return 1 if warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
