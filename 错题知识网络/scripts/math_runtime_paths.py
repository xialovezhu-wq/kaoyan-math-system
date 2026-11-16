"""Machine-local paths and explicit maintenance for the existing math entries.

Repository data stays relative to its owning checkout. Companion projects are
siblings unless explicitly configured; a missing dependency is never an excuse
to create an empty database or fall back to a different checkout.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
import plistlib
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
INDEX_REL = Path("错题知识网络/个人知识点索引/index.sqlite3")
REPO_MARKERS = ("错题知识网络/scripts/wrongnet.py",
                "数学一回滚复习系统/scripts/quick_intake.py")


def is_math_repo(path: Path) -> bool:
    return all((Path(path) / marker).is_file() for marker in REPO_MARKERS)


def companion_root(name: str, env_name: str, repo: Path | None = None) -> Path:
    supplied = os.environ.get(env_name)
    path = Path(supplied).expanduser() if supplied else Path(repo or ROOT).resolve().parent / name
    if not path.is_absolute():
        raise ValueError(env_name + "_must_be_absolute")
    return path.resolve()


def bridge_root(repo: Path | None = None) -> Path:
    return companion_root("Study-Pro-Bridge", "STUDY_PRO_BRIDGE_ROOT", repo)


def storage_map_root(repo: Path | None = None) -> Path:
    return companion_root("Study-Storage-Map", "STUDY_STORAGE_MAP_ROOT", repo)


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()


def python_runtime(module: str | None = None, *, env_name: str = "MATH_PDF_PYTHON") -> Path:
    """Choose a real interpreter; probe an optional PDF dependency only on use."""
    override = os.environ.get(env_name)
    candidates = ([override] if override else [sys.executable,
        str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"),
        str(bridge_root() / ".venv-study-mcp/bin/python")])
    for candidate in candidates:
        found = shutil.which(candidate) if not Path(candidate).is_absolute() else candidate
        if not found or not Path(found).is_file() or not os.access(found, os.X_OK):
            continue
        if module:
            if Path(found).resolve() == Path(sys.executable).resolve():
                if importlib.util.find_spec(module) is None:
                    continue
            else:
                try:
                    probe = subprocess.run([found, "-c",
                        "import importlib.util,sys;sys.exit(importlib.util.find_spec(sys.argv[1]) is None)", module],
                        capture_output=True, timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    continue
                if probe.returncode:
                    continue
        return Path(found).absolute()
    raise ValueError("math_python_runtime_unavailable" + (":" + module if module else ""))


def rebase_backend_paths(value: dict, repo: Path) -> dict:
    """Relocate operational backend paths, never historical evidence or hashes.

    A copied config must use this checkout even while the old checkout exists.
    Only known runtime fields and the backend's own subtree are interpreted.
    Explicit paths outside these namespaces retain their original meaning.
    """
    fields = {"corpus_path", "database", "documents", "mathematical_reference_path",
              "local_model_path", "model_cache", "node", "python", "qmd_module",
              "runtime_root", "service_socket", "config_dir"}
    namespace = ("错题知识网络", "个人知识点索引", "memory-backends")
    original_homes = set()

    def collect_homes(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"corpus_path", "mathematical_reference_path"} and isinstance(child, str):
                    parts = Path(child).parts
                    if (len(parts) > 3 and parts[1] in {"Users", "home"}
                            and any(parts[i:i + 3] == namespace for i in range(len(parts) - 2))):
                        original_homes.add(Path(*parts[:3]))
                collect_homes(child)
        elif isinstance(item, list):
            for child in item:
                collect_homes(child)

    collect_homes(value)

    def relocate(text):
        path = Path(text)
        if not path.is_absolute():
            return text
        parts = path.parts
        for start in range(len(parts) - len(namespace) + 1):
            if parts[start:start + len(namespace)] == namespace:
                return str(Path(repo).resolve().joinpath(*parts[start:]))
        if len(original_homes) == 1:
            original_home = next(iter(original_homes))
            if path.is_relative_to(original_home):
                return str(Path.home() / path.relative_to(original_home))
        return text

    def visit(item):
        if isinstance(item, dict):
            return {key: relocate(child) if key in fields and isinstance(child, str)
                    else visit(child) for key, child in item.items()}
        if isinstance(item, list):
            return [visit(child) for child in item]
        return item

    return visit(copy.deepcopy(value))


def describe(repo: Path = ROOT) -> dict:
    root = Path(repo).expanduser().resolve()
    return {"repo_root": str(root), "bridge_root": str(bridge_root(root)),
            "storage_map_root": str(storage_map_root(root)), "codex_home": str(codex_home()),
            "python": sys.executable, "archive_root": "/Volumes/Study-Archive"}


def _stamp(path):
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino]


def index_status(repo: Path) -> dict:
    root = Path(repo).resolve()
    path = root / INDEX_REL
    if not path.is_file():
        return {"status": "missing", "repair_needed": True}
    if path.is_symlink():
        return {"status": "unsafe_symlink", "repair_needed": False}
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            conn.execute("BEGIN")
            integrity = [row[0] for row in conn.execute("PRAGMA quick_check")]
            if integrity != ["ok"]:
                return {"status": "corrupt", "repair_needed": True, "integrity": integrity}
            meta = {key: json.loads(value) for key, value in conn.execute("SELECT key,value FROM meta")}
            if meta.get("schema") != "math-concept-index-v1" or not all(
                    isinstance(meta.get(key), dict) for key in ("directories", "store_stamps")):
                return {"status": "metadata_incomplete", "repair_needed": True}
            changed = []
            for relative, stamp in {**meta["directories"], **meta["store_stamps"]}.items():
                p = Path(relative)
                if p.is_absolute() or ".." in p.parts:
                    return {"status": "invalid_source_path", "repair_needed": True}
                if _stamp(root / p) != stamp:
                    changed.append(relative)
            import math_concept_index
            query = math_concept_index.resolve_concepts(root, [], "protected", max_bytes=12000)
            changed = sorted(set(changed + query.get("changed_sources", [])))
            stale = bool(changed) or query.get("status") not in {"available", "no_match", "unknown_concept"}
            return {"status": "stale" if stale else "ready", "repair_needed": stale,
                    "changed_sources": changed, "version": meta.get("version"),
                    "source_identity_count": conn.execute("SELECT count(*) FROM source_identities").fetchone()[0]}
        finally:
            conn.close()
    except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        return {"status": "unreadable", "repair_needed": True, "error": str(exc)}


def check(repo: Path = ROOT) -> dict:
    root = Path(repo).expanduser().resolve()
    if not is_math_repo(root):
        raise ValueError("math_repository_markers_missing:" + str(root))
    result = {"paths": describe(root), "index": index_status(root),
              "formal_write_count": 0, "score_write_count": 0}
    scripts = root / "数学一回滚复习系统/scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import quick_intake
    try:
        ledger = root / "数学一回滚复习系统/快速入库事件.jsonl"
        if not ledger.is_file():
            raise ValueError("original_quick_intake_ledger_missing")
        state = quick_intake.replay(quick_intake.load_jsonl(ledger))
        result["ledger"] = {"status": "ready", "captures": len(state["captures"]),
                            "closeouts": len(state["closeouts"])}
    except (ValueError, OSError) as exc:
        result["ledger"] = {"status": "invalid", "error": str(exc)}
    result["dependencies"] = {"publisher": (bridge_root(root) / "study_publication.py").is_file(),
                              "cold_registry": (storage_map_root(root) / "cold_storage.py").is_file()}
    result["link_bridge"] = bridge_configuration_status(root)
    result["status"] = "ready" if (result["index"]["status"] == "ready"
        and result["ledger"]["status"] == "ready" and all(result["dependencies"].values())
        and result["link_bridge"]["status"] == "configured") else "needs_maintenance"
    return result


def bridge_configuration_status(repo: Path) -> dict:
    path = Path.home() / "Library/LaunchAgents/com.study-example.kaoyan-math-obsidian-bridge.plist"
    if not path.is_file():
        return {"status": "missing", "agent": str(path)}
    try:
        value = plistlib.loads(path.read_bytes())
        env = value.get("EnvironmentVariables", {})
        arguments = value.get("ProgramArguments", [])
        snapshot = codex_home() / "kaoyan-math-obsidian-bridge/records.json"
        recorded_root = env.get("KAOYAN_MATH_PROJECT_ROOT")
        matches = (isinstance(recorded_root, str) and Path(recorded_root).is_absolute()
                   and Path(recorded_root).resolve() == repo.resolve()
                   and env.get("KAOYAN_MATH_OBSIDIAN_BRIDGE_SNAPSHOT") == str(snapshot)
                   and len(arguments) >= 2 and all(Path(p).is_file() for p in arguments[:2])
                   and Path(arguments[1]) == snapshot.parent / "obsidian_link_bridge.py"
                   and value.get("WorkingDirectory") == str(snapshot.parent))
        return {"status": "configured" if matches else "stale", "agent": str(path)}
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
        return {"status": "invalid", "agent": str(path)}


def repair_bridge(repo: Path = ROOT) -> dict:
    root = Path(repo).expanduser().resolve()
    if root != ROOT or not is_math_repo(root):
        raise ValueError("bridge_install_requires_owning_checkout")
    script = root / "错题知识网络/scripts/refresh_obsidian_bridge_snapshot.py"
    snapshot = codex_home() / "kaoyan-math-obsidian-bridge/records.json"
    result = subprocess.run([sys.executable, str(script), "--project-root", str(root),
        "--snapshot", str(snapshot), "--install-service"], cwd=root, capture_output=True, text=True)
    configuration = bridge_configuration_status(root)
    return {"status": "ready" if result.returncode == 0 and configuration["status"] == "configured" else "pending", "returncode": result.returncode,
            "output": result.stdout + result.stderr, "configuration": configuration,
            "formal_write_count": 0, "score_write_count": 0}


def repair_index(repo: Path = ROOT, workspace: Path | None = None) -> dict:
    """Back up and atomically rebuild only the derived index, outside capture.

    Failed rebuilds leave the original database in place. Corrupt learning
    ledgers are reported for evidence-based recovery, never truncated or reset.
    """
    root = Path(repo).expanduser().resolve()
    before = check(root)
    if before["ledger"]["status"] != "ready":
        raise ValueError("repair_requires_valid_original_ledger")
    if not before["index"]["repair_needed"]:
        if before["index"]["status"] != "ready":
            raise ValueError("index_requires_manual_path_repair:" + before["index"]["status"])
        return {"status": "noop", "index": before["index"], "formal_write_count": 0, "score_write_count": 0}
    import math_workflow_storage as storage
    import math_concept_index as native
    folder = storage.ensure_workspace(workspace or storage.WORK_ROOT / "路径迁移维护" /
        (datetime.now().strftime("%Y-%m-%d-%H%M%S") + "-" + os.urandom(4).hex()))
    target = root / INDEX_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    with (target.parent / "build.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if any(Path(str(target) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise ValueError("index_has_active_sqlite_sidecars; close_the_index_writer_before_repair")
        if target.is_symlink():
            raise ValueError("index_symlink_forbidden")
        if target.is_file():
            original_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            backup = folder / "index-before.sqlite3"
            if backup.exists():
                raise ValueError("repair_workspace_already_contains_backup")
            shutil.copy2(target, backup)
            if hashlib.sha256(backup.read_bytes()).hexdigest() != original_hash or hashlib.sha256(target.read_bytes()).hexdigest() != original_hash:
                raise ValueError("index_backup_readback_failed")
        fd, name = tempfile.mkstemp(prefix=".index-repair-", suffix=".sqlite3", dir=target.parent)
        os.close(fd)
        temporary = Path(name)
        conn = None
        try:
            conn = native._db(temporary)
            built = native._build(root, conn, None, force_full=True)
            if [row[0] for row in conn.execute("PRAGMA integrity_check")] != ["ok"]:
                raise ValueError("rebuilt_index_integrity_failed")
            conn.close()
            conn = None
            os.replace(temporary, target)
            import math_memory_projection
            conn = sqlite3.connect(target)
            math_memory_projection.record_ready(root, conn, built["version"])
        finally:
            if conn is not None:
                conn.close()
            temporary.unlink(missing_ok=True)
    after = index_status(root)
    result = {"status": "rebuilt" if after["status"] == "ready" else "pending", "before": before["index"], "index": after,
              "backup_directory": str(folder), "formal_write_count": 0, "score_write_count": 0}
    (folder / "repair.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    try:
        result["registration"] = storage.register_cold_artifact(folder, purpose="math_migration_index_repair")
    except Exception as exc:
        result["registration"] = {"status": "pending", "error": str(exc),
                                  "resume": "register_existing_backup_directory_only"}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("command", choices=("paths", "check", "repair-index", "repair-bridge"))
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    if args.command == "paths":
        result = describe(args.repo)
    elif args.command == "check":
        result = check(args.repo)
    elif args.command == "repair-index":
        result = repair_index(args.repo, args.workspace)
    else:
        result = repair_bridge(args.repo)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") in {"pending", "needs_maintenance"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
