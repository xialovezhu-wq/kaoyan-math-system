#!/usr/bin/env python3
"""Locate the current math checkout and invoke its existing native scripts.

This bootstrap is installed with the skill. It reads workspace/vault metadata,
never searches the disk or initializes a repository/database.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


MARKERS = ("错题知识网络/scripts/wrongnet.py",
           "数学一回滚复习系统/scripts/quick_intake.py")


def valid_root(path):
    return all((path / name).is_file() for name in MARKERS)


def discover_repo(explicit=None, *, cwd=None, home=None, anchor=None):
    supplied = explicit or os.environ.get("KAOYAN_MATH_PROJECT_ROOT")
    if supplied:
        root = Path(supplied).expanduser().resolve()
        if not valid_root(root):
            raise ValueError("configured_math_repository_unavailable:" + str(root))
        return root
    for start in (Path(cwd or Path.cwd()).resolve(), Path(anchor or __file__).resolve().parent):
        for path in (start, *start.parents):
            if valid_root(path):
                return path
    home = Path(home or Path.home())
    registry = home / "Library/Application Support/obsidian/obsidian.json"
    candidates = set()
    if registry.is_file():
        try:
            value = json.loads(registry.read_text())
            for vault in value.get("vaults", {}).values():
                raw = vault.get("path") if isinstance(vault, dict) else None
                if isinstance(raw, str) and Path(raw).is_absolute():
                    path = Path(raw).expanduser().resolve()
                    if valid_root(path):
                        candidates.add(path)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    if len(candidates) == 1:
        return candidates.pop()
    if candidates:
        raise ValueError("multiple_math_vaults; select_the_workspace_or_pass_--repo")
    default = home / "Documents/kaoyan-math"
    if valid_root(default):
        return default.resolve()
    raise ValueError("math_repository_not_found; select_the_math_workspace_or_pass_--repo")


def native_command(root, relative, arguments):
    part = Path(relative)
    if part.is_absolute() or ".." in part.parts:
        raise ValueError("native_script_must_be_repository_relative")
    if len(part.parts) != 3 or tuple(part.parts[:2]) not in {
            ("错题知识网络", "scripts"), ("数学一回滚复习系统", "scripts")}:
        raise ValueError("native_script_outside_math_entries")
    script = (root / part).resolve()
    if not script.is_relative_to(root) or not script.is_file() or script.suffix != ".py":
        raise ValueError("native_script_missing_or_unsafe")
    return [sys.executable, str(script), *arguments]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("root")
    sub.add_parser("paths")
    sub.add_parser("check")
    sub.add_parser("repair-bridge")
    repair = sub.add_parser("repair-index")
    repair.add_argument("--workspace", type=Path)
    run = sub.add_parser("run")
    run.add_argument("script")
    run.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        root = discover_repo(args.repo)
        if args.command == "root":
            print(root)
            return
        if args.command == "run":
            command = native_command(root, args.script, args.arguments)
        else:
            tail = ["--repo", str(root), args.command]
            if args.command == "repair-index" and args.workspace:
                tail += ["--workspace", str(args.workspace)]
            command = native_command(root, "错题知识网络/scripts/math_runtime_paths.py", tail)
        env = dict(os.environ, KAOYAN_MATH_PROJECT_ROOT=str(root))
        completed = subprocess.run(command, cwd=root, env=env)
        raise SystemExit(completed.returncode)
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "unavailable", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
