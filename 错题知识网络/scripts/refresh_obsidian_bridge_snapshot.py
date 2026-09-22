#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlencode


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VISUAL_DIR = PROJECT_ROOT / "错题知识网络" / "可视化错题详情"
CARD_DIR = PROJECT_ROOT / "错题知识网络" / "错题卡"
DEFAULT_SNAPSHOT = Path.home() / ".codex" / "kaoyan-math-obsidian-bridge" / "records.json"
MANAGED_START = "<!-- math-display-assets:start -->"
MANAGED_END = "<!-- math-display-assets:end -->"
STABLE_ASSET_ROOT = PurePosixPath("错题知识网络/assets/visual_wrong_questions")
FORMAL_ID_RE = re.compile(r"^(?:GS|LA|PR)-\d+$")
DETAIL_FILENAME_RE = re.compile(r"^((?:GS|LA|PR)-\d+)_.+\.md$")
CARD_FILENAME_RE = re.compile(r"^((?:GS|LA|PR)-\d+)(?:_|\.md$)")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


class BridgeSnapshotError(ValueError):
    """A derived visual route is ambiguous or cannot be proven safe."""


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def compact_record(rec: dict) -> dict:
    return {
        "visual_id": rec.get("visual_id", ""),
        "wrongnet_id": rec.get("wrongnet_id", ""),
        "title": rec.get("title", ""),
        "detail_note": rec.get("detail_note", ""),
        "obsidian_url": rec.get("obsidian_url", ""),
        "link_status": rec.get("link_status", ""),
        "search_text": rec.get("search_text", ""),
    }


def compact_asset(rec: dict) -> dict:
    return {
        "asset_path": rec.get("asset_path", ""),
        "asset_role": rec.get("asset_role", ""),
        "visual_id": rec.get("visual_id", ""),
        "wrongnet_id": rec.get("wrongnet_id", ""),
        "title": rec.get("title", ""),
        "detail_note": rec.get("detail_note", ""),
        "obsidian_url": rec.get("obsidian_url", ""),
        "link_status": rec.get("link_status", ""),
        "last_updated": rec.get("last_updated", ""),
    }


def obsidian_url(vault: str, detail_note: str) -> str:
    return "obsidian://open?" + urlencode({"vault": vault, "file": detail_note}, quote_via=quote)


def read_frontmatter_scalar(text: str, key: str) -> str:
    if not text.startswith("---"):
        return ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ""
    match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", parts[1], re.MULTILINE)
    if not match:
        return ""
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def formal_card_record(
    card_path: Path,
    existing_ids: set[str],
    vault: str,
    project_root: Path = PROJECT_ROOT,
) -> dict | None:
    if card_path.name == "README.md":
        return None
    text = card_path.read_text(encoding="utf-8", errors="replace")
    card_id = read_frontmatter_scalar(text, "id") or card_path.stem.split("_", 1)[0]
    if not card_id or card_id in existing_ids:
        return None
    detail_note = card_path.relative_to(project_root).as_posix()
    title = read_frontmatter_scalar(text, "title") or card_path.stem
    return {
        "visual_id": f"FORMAL-{card_id}",
        "wrongnet_id": card_id,
        "title": title,
        "detail_note": detail_note,
        "obsidian_url": obsidian_url(vault, detail_note),
        "link_status": "formal_wrong_card",
        "search_text": f"{card_id} {title} formal wrong card 正式错题卡",
    }


def _managed_section(text: str, page: Path) -> str | None:
    start_count = text.count(MANAGED_START)
    end_count = text.count(MANAGED_END)
    if start_count == 0 and end_count == 0:
        return None
    if start_count != 1 or end_count != 1:
        raise BridgeSnapshotError(f"managed_marker_invalid:{page}")
    start = text.index(MANAGED_START) + len(MANAGED_START)
    end = text.index(MANAGED_END)
    if end < start:
        raise BridgeSnapshotError(f"managed_marker_order_invalid:{page}")
    return text[start:end]


def _managed_stable_image_refs(section: str) -> list[str]:
    refs: list[str] = []
    for raw in re.findall(r"!\[\[([^\]\n]+)\]\]", section):
        ref = raw.split("|", 1)[0].strip()
        suffix = PurePosixPath(ref.split("#", 1)[0].split("?", 1)[0]).suffix.lower()
        if ref.startswith(STABLE_ASSET_ROOT.as_posix() + "/") and suffix in IMAGE_SUFFIXES:
            refs.append(ref)
    for raw in re.findall(r"!\[[^\]\n]*\]\(([^)\n]+)\)", section):
        value = raw.strip()
        if value.startswith("<") and ">" in value:
            ref = value[1 : value.index(">")].strip()
        else:
            ref = value.split(None, 1)[0]
        suffix = PurePosixPath(ref.split("#", 1)[0].split("?", 1)[0]).suffix.lower()
        if ref.startswith(STABLE_ASSET_ROOT.as_posix() + "/") and suffix in IMAGE_SUFFIXES:
            refs.append(ref)
    return refs


def _filename_formal_id(path: Path) -> str:
    match = DETAIL_FILENAME_RE.fullmatch(path.name)
    return match.group(1) if match else ""


def _reject_symlink_components(path: Path, root: Path, field: str) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise BridgeSnapshotError(f"{field}_outside_project:{path}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise BridgeSnapshotError(f"{field}_symlink_forbidden:{path}")


def _validate_stable_asset(project_root: Path, formal_id: str, reference: str, page: Path) -> None:
    if "\\" in reference or "#" in reference or "?" in reference:
        raise BridgeSnapshotError(f"stable_asset_path_invalid:{page}:{reference}")
    raw_parts = reference.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise BridgeSnapshotError(f"stable_asset_path_invalid:{page}:{reference}")
    relative = PurePosixPath(reference)
    expected_prefix = (*STABLE_ASSET_ROOT.parts, formal_id)
    if (
        relative.is_absolute()
        or relative.parts[: len(expected_prefix)] != expected_prefix
        or len(relative.parts) <= len(expected_prefix)
    ):
        raise BridgeSnapshotError(f"stable_asset_id_mismatch:{page}:{reference}")

    asset = project_root.joinpath(*relative.parts)
    expected_dir = project_root.joinpath(*expected_prefix)
    _reject_symlink_components(asset, project_root, "stable_asset")
    if not asset.is_file():
        raise BridgeSnapshotError(f"stable_asset_missing:{page}:{reference}")
    try:
        asset.resolve(strict=True).relative_to(expected_dir.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise BridgeSnapshotError(f"stable_asset_outside_formal_id_dir:{page}:{reference}") from exc


def _formal_card_index(card_dir: Path) -> dict[str, list[tuple[Path, str, str]]]:
    index: dict[str, list[tuple[Path, str, str]]] = {}
    for card_path in sorted(card_dir.glob("*.md")):
        if card_path.name == "README.md":
            continue
        text = card_path.read_text(encoding="utf-8", errors="replace")
        frontmatter_id = read_frontmatter_scalar(text, "id")
        filename_match = CARD_FILENAME_RE.match(card_path.name)
        filename_id = filename_match.group(1) if filename_match else ""
        formal_id = frontmatter_id if FORMAL_ID_RE.fullmatch(frontmatter_id) else filename_id
        if formal_id:
            index.setdefault(formal_id, []).append((card_path, frontmatter_id, filename_id))
    return index


def _require_unique_formal_card(
    formal_id: str,
    card_index: dict[str, list[tuple[Path, str, str]]],
    project_root: Path,
    page: Path,
) -> None:
    matches = card_index.get(formal_id, [])
    if len(matches) != 1:
        raise BridgeSnapshotError(f"formal_card_not_unique:{formal_id}:{len(matches)}:{page}")
    card_path, frontmatter_id, filename_id = matches[0]
    if frontmatter_id and frontmatter_id != formal_id:
        raise BridgeSnapshotError(f"formal_card_frontmatter_id_mismatch:{formal_id}:{card_path}")
    if filename_id and filename_id != formal_id:
        raise BridgeSnapshotError(f"formal_card_filename_id_mismatch:{formal_id}:{card_path}")
    _reject_symlink_components(card_path, project_root, "formal_card")
    if not card_path.is_file():
        raise BridgeSnapshotError(f"formal_card_missing:{formal_id}:{card_path}")


def _first_heading(text: str) -> str:
    match = re.search(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def derived_visual_records(
    project_root: Path,
    visual_dir: Path,
    existing_ids: set[str],
    vault: str,
) -> list[dict]:
    card_index = _formal_card_index(project_root / "错题知识网络" / "错题卡")
    candidates: dict[str, list[dict]] = {}

    for page in sorted(visual_dir.rglob("*.md")):
        text = page.read_text(encoding="utf-8", errors="replace")
        section = _managed_section(text, page)
        if section is None:
            continue
        stable_refs = _managed_stable_image_refs(section)
        if not stable_refs:
            continue

        _reject_symlink_components(page, project_root, "visual_detail")
        if not page.is_file():
            raise BridgeSnapshotError(f"visual_detail_not_regular_file:{page}")

        frontmatter_id = read_frontmatter_scalar(text, "wrongnet_id")
        filename_id = _filename_formal_id(page)
        if frontmatter_id:
            if not FORMAL_ID_RE.fullmatch(frontmatter_id):
                raise BridgeSnapshotError(f"visual_detail_frontmatter_id_invalid:{page}:{frontmatter_id}")
            formal_id = frontmatter_id
            if filename_id and filename_id != formal_id:
                raise BridgeSnapshotError(f"visual_detail_filename_id_mismatch:{page}:{formal_id}:{filename_id}")
        else:
            if not filename_id:
                raise BridgeSnapshotError(f"visual_detail_identity_missing:{page}")
            formal_id = filename_id

        visual_id = read_frontmatter_scalar(text, "visual_id")
        if visual_id and re.fullmatch(r"VIS-(?:GS|LA|PR)-\d+", visual_id) and visual_id != f"VIS-{formal_id}":
            raise BridgeSnapshotError(f"visual_detail_visual_id_mismatch:{page}:{visual_id}:{formal_id}")

        for reference in stable_refs:
            _validate_stable_asset(project_root, formal_id, reference, page)
        _require_unique_formal_card(formal_id, card_index, project_root, page)

        detail_note = page.relative_to(project_root).as_posix()
        title = read_frontmatter_scalar(text, "title") or _first_heading(text) or page.stem
        record = {
            "wrongnet_id": formal_id,
            "title": title,
            "detail_note": detail_note,
            "obsidian_url": obsidian_url(vault, detail_note),
            "link_status": "linked_wrongnet",
            "search_text": f"{formal_id} {title} stable visual detail 稳定展示资产",
        }
        if visual_id:
            record["visual_id"] = visual_id
        candidates.setdefault(formal_id, []).append(compact_record(record))

    duplicate_ids = sorted(formal_id for formal_id, rows in candidates.items() if len(rows) != 1)
    if duplicate_ids:
        raise BridgeSnapshotError(f"visual_detail_id_not_unique:{','.join(duplicate_ids)}")

    return [
        candidates[formal_id][0]
        for formal_id in sorted(candidates)
        if formal_id not in existing_ids
    ]


def build_snapshot(project_root: Path, vault: str) -> tuple[dict, int, int]:
    project_root = project_root.resolve(strict=True)
    visual_dir = project_root / "错题知识网络" / "可视化错题详情"
    manifest = read_json(visual_dir / "manifest.json")
    asset_map_path = visual_dir / "asset_to_obsidian.json"
    asset_map = read_json(asset_map_path) if asset_map_path.exists() else {"records": []}

    records = [compact_record(rec) for rec in sorted(manifest.get("records", []), key=record_priority)]
    existing_ids = {rec.get("wrongnet_id", "") for rec in records if rec.get("wrongnet_id")}
    derived_records = derived_visual_records(project_root, visual_dir, existing_ids, vault)
    records.extend(sorted(derived_records, key=record_priority))
    existing_ids.update(rec["wrongnet_id"] for rec in derived_records)

    card_dir = project_root / "错题知识网络" / "错题卡"
    formal_records = [
        rec
        for card_path in sorted(card_dir.glob("*.md"))
        if (rec := formal_card_record(card_path, existing_ids, vault, project_root)) is not None
    ]
    records.extend(sorted(formal_records, key=record_priority))
    assets = [compact_asset(rec) for rec in asset_map.get("records", [])]

    snapshot = {
        "schema_version": "visual_obsidian_bridge_snapshot.v1",
        "updated_at": date.today().isoformat(),
        "description": (
            "Snapshot for Codex-clickable math visual wrong-question Obsidian bridge, "
            "with validated managed visual-detail routes and formal-card fallbacks."
        ),
        "records": records,
        "assets": assets,
    }
    return snapshot, len(formal_records), len(derived_records)


def record_priority(rec: dict) -> tuple[int, str, str]:
    status_priority = {
        "linked_wrongnet": 0,
        "imported": 1,
        "merged_into_wrongnet": 2,
        "visual_gap_registered": 7,
        "formal_wrong_card": 8,
    }
    return (
        status_priority.get(rec.get("link_status", ""), 9),
        rec.get("wrongnet_id", ""),
        rec.get("visual_id", ""),
    )


def request_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310 - local bridge only
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the Codex-clickable Obsidian bridge snapshot.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--bridge-url", default=os.environ.get("KAOYAN_MATH_OBSIDIAN_BRIDGE_URL", "http://127.0.0.1:8765"))
    parser.add_argument("--vault", default=os.environ.get("KAOYAN_MATH_OBSIDIAN_VAULT", "kaoyan-math"))
    parser.add_argument("--no-ping", action="store_true", help="Only write the snapshot; do not call the running bridge.")
    parser.add_argument(
        "--push-only",
        action="store_true",
        help="Only ask the local bridge to refresh the existing snapshot; run this outside the formal repo lock.",
    )
    args = parser.parse_args()

    if args.push_only:
        try:
            refresh = request_json(args.bridge_url.rstrip("/") + "/refresh")
            health = request_json(args.bridge_url.rstrip("/") + "/health")
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"bridge_refresh=failed reason={exc}")
            return 1
        print(
            "bridge_refresh=ok "
            f"refresh_records={refresh.get('records')} refresh_assets={refresh.get('assets')} "
            f"health_records={health.get('records')} health_assets={health.get('assets')}"
        )
        return 0

    try:
        snapshot, formal_record_count, derived_record_count = build_snapshot(args.project_root, args.vault)
    except (BridgeSnapshotError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"snapshot=failed reason={exc}")
        return 1
    records = snapshot["records"]
    assets = snapshot["assets"]

    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{args.snapshot.name}.", suffix=".tmp", dir=args.snapshot.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(args.snapshot)
        dir_fd = os.open(args.snapshot.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if tmp.exists():
            tmp.unlink()

    print(
        f"snapshot={args.snapshot} records={len(records)} "
        f"visual_records={len(records) - formal_record_count} "
        f"derived_visual_records={derived_record_count} "
        f"formal_fallbacks={formal_record_count} assets={len(assets)}"
    )

    if args.no_ping:
        return 0

    try:
        refresh = request_json(args.bridge_url.rstrip("/") + "/refresh")
        health = request_json(args.bridge_url.rstrip("/") + "/health")
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"bridge_refresh=skipped reason={exc}")
        return 0

    print(
        "bridge_refresh=ok "
        f"refresh_records={refresh.get('records')} refresh_assets={refresh.get('assets')} "
        f"health_records={health.get('records')} health_assets={health.get('assets')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
