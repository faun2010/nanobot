#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


AUDIO_EXTS = {".flac", ".dsf", ".wv", ".ape", ".wav", ".aiff", ".aif"}


@dataclass
class StepResult:
    name: str
    ok: bool
    returncode: int
    command: str
    seconds: float
    stdout: str = ""
    stderr: str = ""


def run_cmd(
    cmd: Sequence[str],
    *,
    cwd: Path,
    env: Dict[str, str],
    dry_run: bool,
) -> StepResult:
    display = " ".join([subprocess.list2cmdline([x]) if " " in x else x for x in cmd])
    if dry_run:
        return StepResult(name="", ok=True, returncode=0, command=display, seconds=0.0)
    started = time.time()
    proc = subprocess.run(
        list(cmd),
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return StepResult(
        name="",
        ok=(proc.returncode == 0),
        returncode=proc.returncode,
        command=display,
        seconds=round(time.time() - started, 3),
        stdout=(proc.stdout or "").strip(),
        stderr=(proc.stderr or "").strip(),
    )


def has_audio_files(path: Path) -> bool:
    for p in path.iterdir():
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS and not p.name.startswith("."):
            return True
    return False


def discover_work_indices(album_dir: Path) -> List[int]:
    found: List[int] = []
    for child in sorted(album_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        if not child.name.isdigit():
            continue
        if has_audio_files(child):
            found.append(int(child.name))
    return found


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Strict non-interactive runme processor for split works.")
    p.add_argument("--album-dir", required=True, help="Album root directory")
    p.add_argument("--work-index", action="append", type=int, help="Specific work index to process (repeatable)")
    p.add_argument("--from-index", type=int, help="Start index (inclusive)")
    p.add_argument("--to-index", type=int, help="End index (inclusive)")
    p.add_argument("--skip-init", action="store_true", help="Skip runme template init stage")
    p.add_argument("--skip-fill", action="store_true", help="Skip bach_fillRunme stage")
    p.add_argument("--skip-enrich", action="store_true", help="Skip runme_enricher stage")
    p.add_argument("--skip-imslp-canonical", action="store_true", help="Skip IMSLP-based work canonicalization")
    p.add_argument("--publish", action="store_true", help="Run 'bash runme force' after validation")
    p.add_argument("--stop-on-error", action="store_true", help="Stop at first failed work")
    p.add_argument("--dry-run", action="store_true", help="Print commands only")
    p.add_argument("--json", action="store_true", help="Print JSON summary")
    p.add_argument("--debug", action="store_true", help="Verbose output")
    return p.parse_args()


def build_env(whitebull_dir: Path) -> Dict[str, str]:
    env = os.environ.copy()
    env["WHITEBULL_DIR"] = str(whitebull_dir)
    old_path = env.get("PATH", "")
    extra = f"{whitebull_dir / 'absolutely'}:{whitebull_dir / 'composer'}"
    env["PATH"] = f"{extra}:{old_path}" if old_path else extra
    env.setdefault("BACH_NO_INTERACTIVE", "1")
    return env


def pick_indices(album_dir: Path, args: argparse.Namespace) -> List[int]:
    if args.work_index:
        return sorted(set(int(x) for x in args.work_index if x is not None))
    if args.from_index is not None or args.to_index is not None:
        start = 0 if args.from_index is None else int(args.from_index)
        end = start if args.to_index is None else int(args.to_index)
        if start > end:
            start, end = end, start
        return list(range(start, end + 1))
    auto = discover_work_indices(album_dir)
    if auto:
        return auto
    return [0]


def ensure_runme_template(
    album_dir: Path,
    *,
    init_script: Path,
    env: Dict[str, str],
    dry_run: bool,
) -> StepResult:
    if (album_dir / "runme").exists():
        return StepResult(name="init-runme", ok=True, returncode=0, command="(exists)", seconds=0.0)
    step = run_cmd(["bash", str(init_script), str(album_dir)], cwd=album_dir, env=env, dry_run=dry_run)
    step.name = "init-runme"
    return step


def ensure_work_runme(work_dir: Path, root_runme: Path, *, dry_run: bool) -> Tuple[bool, str]:
    target = work_dir / "runme"
    if target.exists():
        return True, "exists"
    if not root_runme.exists():
        return False, "root runme missing"
    if dry_run:
        return True, "would copy root runme"
    shutil.copy2(root_runme, target)
    return True, "copied root runme"


def main() -> int:
    args = parse_args()
    album_dir = Path(args.album_dir).expanduser().resolve()
    if not album_dir.is_dir():
        print(json.dumps({"ok": False, "error": f"album directory not found: {album_dir}"}, ensure_ascii=False))
        return 2

    whitebull_dir = Path(os.environ.get("WHITEBULL_DIR", "")).expanduser().resolve() if os.environ.get("WHITEBULL_DIR") else Path(__file__).resolve().parents[3]
    env = build_env(whitebull_dir)

    init_script = whitebull_dir / "absolutely" / "handel_initCD.sh"
    fill_script = whitebull_dir / "absolutely" / "bach_fillRunme.sh"
    enrich_script = whitebull_dir / "absolutely" / "runme_enricher.py"
    validator_script = Path(__file__).resolve().parent / "validate_runme_write_strict.py"
    canonical_script = Path(__file__).resolve().parent / "canonicalize_work_from_imslp.py"
    publish_guard_script = Path(__file__).resolve().parent / "validate_publish_exact_guard.py"

    for required in (init_script, fill_script, enrich_script, validator_script, canonical_script, publish_guard_script):
        if not required.exists():
            print(json.dumps({"ok": False, "error": f"missing tool: {required}"}, ensure_ascii=False))
            return 3

    indices = pick_indices(album_dir, args)
    results: List[Dict[str, object]] = []

    if not args.skip_init:
        init_step = ensure_runme_template(album_dir, init_script=init_script, env=env, dry_run=args.dry_run)
        if not init_step.ok:
            payload = {
                "ok": False,
                "album_dir": str(album_dir),
                "error": "init-runme failed",
                "step": init_step.__dict__,
            }
            print(json.dumps(payload, ensure_ascii=False))
            return 4

    root_runme = album_dir / "runme"

    overall_ok = True
    for idx in indices:
        if idx == 0 and not (album_dir / "0").is_dir() and has_audio_files(album_dir):
            work_dir = album_dir
        else:
            work_dir = album_dir / str(idx)

        one: Dict[str, object] = {
            "index": idx,
            "work_dir": str(work_dir),
            "ok": True,
            "steps": [],
            "validator": None,
            "publish_guard": None,
            "errors": [],
        }

        if not work_dir.is_dir():
            one["ok"] = False
            one["errors"].append(f"work directory missing: {work_dir}")
            results.append(one)
            overall_ok = False
            if args.stop_on_error:
                break
            continue

        ok_runme, note = ensure_work_runme(work_dir, root_runme, dry_run=args.dry_run)
        one["steps"].append({"name": "ensure-work-runme", "ok": ok_runme, "note": note})
        if not ok_runme:
            one["ok"] = False
            one["errors"].append("ensure-work-runme failed")
            results.append(one)
            overall_ok = False
            if args.stop_on_error:
                break
            continue

        target_runme = work_dir / "runme"

        if not args.skip_fill:
            fill = run_cmd(
                ["bash", str(fill_script), "--output", str(target_runme), str(idx)],
                cwd=album_dir,
                env=env,
                dry_run=args.dry_run,
            )
            fill.name = "fill-runme"
            one["steps"].append(fill.__dict__)
            if not fill.ok:
                one["ok"] = False
                one["errors"].append("fill-runme failed")
                results.append(one)
                overall_ok = False
                if args.stop_on_error:
                    break
                continue

        if not args.skip_enrich:
            enrich = run_cmd(
                ["python3", str(enrich_script), "--album-dir", str(work_dir), "--skip-bach"],
                cwd=album_dir,
                env=env,
                dry_run=args.dry_run,
            )
            enrich.name = "enrich-runme"
            one["steps"].append(enrich.__dict__)
            if not enrich.ok:
                one["ok"] = False
                one["errors"].append("enrich-runme failed")
                results.append(one)
                overall_ok = False
                if args.stop_on_error:
                    break
                continue

        if not args.skip_imslp_canonical:
            canonical = run_cmd(
                [
                    "python3",
                    str(canonical_script),
                    "--runme",
                    str(target_runme),
                    "--work-dir",
                    str(work_dir),
                    "--album-dir",
                    str(album_dir),
                    "--whitebull-dir",
                    str(whitebull_dir),
                    "--json",
                ],
                cwd=album_dir,
                env=env,
                dry_run=args.dry_run,
            )
            canonical.name = "imslp-canonicalize-work"
            one["steps"].append(canonical.__dict__)
            if not canonical.ok:
                one["ok"] = False
                one["errors"].append("imslp-canonicalize-work failed")
                results.append(one)
                overall_ok = False
                if args.stop_on_error:
                    break
                continue

        validate = run_cmd(
            [
                "python3",
                str(validator_script),
                "--runme",
                str(target_runme),
                "--work-dir",
                str(work_dir),
                "--album-dir",
                str(album_dir),
                "--json",
            ],
            cwd=album_dir,
            env=env,
            dry_run=args.dry_run,
        )
        validate.name = "validate-runme-write"
        one["steps"].append(validate.__dict__)

        validator_payload: Dict[str, object] = {}
        if args.dry_run:
            validator_payload = {"ok": True, "dry_run": True}
        else:
            text = (validate.stdout or "").strip()
            if text:
                last = text.splitlines()[-1]
                try:
                    validator_payload = json.loads(last)
                except Exception:
                    validator_payload = {"ok": False, "error": "validator output parse failed", "raw": text}
            else:
                validator_payload = {"ok": False, "error": "validator produced no output"}

        one["validator"] = validator_payload
        if not validate.ok or not bool(validator_payload.get("ok", False)):
            one["ok"] = False
            one["errors"].append("validate-runme-write failed")
            results.append(one)
            overall_ok = False
            if args.stop_on_error:
                break
            continue

        if args.publish:
            guard = run_cmd(
                [
                    "python3",
                    str(publish_guard_script),
                    "--runme",
                    str(target_runme),
                    "--whitebull-dir",
                    str(whitebull_dir),
                    "--json",
                ],
                cwd=album_dir,
                env=env,
                dry_run=args.dry_run,
            )
            guard.name = "validate-publish-exact"
            one["steps"].append(guard.__dict__)

            guard_payload: Dict[str, object] = {}
            if args.dry_run:
                guard_payload = {"ok": True, "dry_run": True}
            else:
                text = (guard.stdout or "").strip()
                if text:
                    last = text.splitlines()[-1]
                    try:
                        guard_payload = json.loads(last)
                    except Exception:
                        guard_payload = {"ok": False, "error": "publish guard output parse failed", "raw": text}
                else:
                    guard_payload = {"ok": False, "error": "publish guard produced no output"}

            one["publish_guard"] = guard_payload
            if not guard.ok or not bool(guard_payload.get("ok", False)):
                one["ok"] = False
                one["errors"].append("validate-publish-exact failed")
                results.append(one)
                overall_ok = False
                if args.stop_on_error:
                    break
                continue

            pub = run_cmd(["bash", "runme", "force"], cwd=work_dir, env=env, dry_run=args.dry_run)
            pub.name = "runme-force-publish"
            one["steps"].append(pub.__dict__)
            if not pub.ok:
                one["ok"] = False
                one["errors"].append("runme-force-publish failed")
                overall_ok = False
                results.append(one)
                if args.stop_on_error:
                    break
                continue

        results.append(one)

    payload = {
        "ok": overall_ok,
        "album_dir": str(album_dir),
        "work_count": len(results),
        "indices": indices,
        "skip_init": bool(args.skip_init),
        "skip_fill": bool(args.skip_fill),
        "skip_enrich": bool(args.skip_enrich),
        "skip_imslp_canonical": bool(args.skip_imslp_canonical),
        "publish": bool(args.publish),
        "dry_run": bool(args.dry_run),
        "results": results,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"[runme-skill] album={album_dir} ok={overall_ok} works={len(results)}")
        for item in results:
            idx = item["index"]
            wdir = item["work_dir"]
            ok = item["ok"]
            errs = item.get("errors", [])
            print(f"[runme-skill] work={idx} ok={ok} dir={wdir}")
            if errs:
                print(f"[runme-skill] work={idx} errors={'; '.join(errs)}")

    return 0 if overall_ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
