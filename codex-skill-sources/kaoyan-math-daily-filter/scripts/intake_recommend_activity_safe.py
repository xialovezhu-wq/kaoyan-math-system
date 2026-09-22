#!/usr/bin/env python3
"""Compatibility entry; all activity attribution lives in the repository."""
from __future__ import annotations
import importlib.util
from pathlib import Path


def main() -> int:
    target = Path.cwd().resolve() / "错题知识网络/scripts/intake_recommend.py"
    spec = importlib.util.spec_from_file_location("math_intake_recommend_live", target)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load recommender: {target}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
