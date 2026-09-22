#!/usr/bin/env python3
"""Read-only helper: old-question redo recommendations with full date history.

Two modes:

- --id GS-xxx      单题事实行（wraps `wrongnet.py related`），供点名查询相似题时使用。
- --seed-id ...     学习结束统一筛题数据；参数可重复，只合并调用方明确给出的
                    formal IDs。`--date` 指定排名参考日，默认今天。

Run only after the relevant single-question intake has completed a fresh rebuild. It joins each candidate with its
wrong_history dates / counts / mastery from 生成/wrong_questions.json, and prints
ready-to-quote data lines so the intake conversation does not have to open each old card.

Ranking facts only: the AI still writes the final 推荐原因 wording and may reorder by
fit (同错点/同方法入口/错因价值优先), per AI维护规则. Cards with status 已掌握 are skipped.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import intake_lib  # noqa: E402
import training_evidence  # noqa: E402

RELATED_LINE = re.compile(r"^- (\d+(?:\.\d+)?) (强关联|中关联|弱关联) ([A-Z]{2,3}-\d+)\s*(.*)$")
FORMAL_ID_RE = re.compile(r"^(?:GS|LA|PR|MX)-\d{3,}$")
LEVEL_RANK = {"强关联": 3, "中关联": 2, "弱关联": 1}
ROLLBACK_ROOT = intake_lib.PROJECT_ROOT / "数学一回滚复习系统"
ROLLBACK_UNITS_PATH = ROLLBACK_ROOT / "复习单元.json"
ROLLBACK_REVIEW_LOG_PATH = ROLLBACK_ROOT / "复习记录.jsonl"
ROLLBACK_WARMUP_LOG_PATH = ROLLBACK_ROOT / "学习前5题记录.jsonl"
ROLLBACK_SCHEDULER_PATH = ROLLBACK_ROOT / "scripts" / "scheduler.py"


def reference_date(value: str | None) -> date:
    if not value:
        return date.today()
    return datetime.strptime(value, "%Y-%m-%d").date()


def load_permanent_delivery_exclusion_ids(ranking_day: date) -> set[str]:
    """Use the scheduler's canonical no-hint independent-correct evidence gate."""

    if not ROLLBACK_SCHEDULER_PATH.exists():
        raise ValueError("缺少权威调度器，无法核验永久排除卡")
    spec = importlib.util.spec_from_file_location(
        "math_permanent_delivery_exclusions",
        ROLLBACK_SCHEDULER_PATH,
    )
    if spec is None or spec.loader is None:
        raise ValueError("无法加载权威调度器的永久排除规则")
    scheduler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scheduler)
    try:
        excluded = scheduler.load_permanent_delivery_exclusion_ids(ranking_day)
    except scheduler.RollbackSyncError as exc:
        raise ValueError(f"无法安全核验永久排除卡：{exc}") from exc
    if not isinstance(excluded, set) or any(
        not FORMAL_ID_RE.fullmatch(str(card_id)) for card_id in excluded
    ):
        raise ValueError("权威调度器返回了无效的永久排除集合")
    return {str(card_id) for card_id in excluded}


def days_since(iso_day: str, reference_day: date | None = None) -> int | None:
    try:
        return ((reference_day or date.today()) - datetime.strptime(iso_day, "%Y-%m-%d").date()).days
    except ValueError:
        return None


def related_candidates(card_id: str, pool: int) -> list[tuple[str, str, str, str, str]] | None:
    """Parsed `wrongnet.py related` lines as (id, score_str, level, title, reason); None on failure."""
    result = subprocess.run(
        [sys.executable or "python3", str(SCRIPT_DIR / "wrongnet.py"), "related", card_id, "--top", str(pool)],
        cwd=intake_lib.PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
        return None
    candidates: list[tuple[str, str, str, str, str]] = []
    for line in result.stdout.splitlines():
        match = RELATED_LINE.match(line.strip())
        if not match:
            continue
        score, level, cid, rest = match.groups()
        title, _, reason = rest.partition("：")
        candidates.append((cid, score, level, title.strip(), reason.strip()))
    return candidates


def load_context() -> tuple[list[dict[str, Any]], str, dict[str, dict[str, Any]], dict[str, str]]:
    cards, updated_at = intake_lib.load_generated_cards()
    briefs = {card.get("id"): intake_lib.card_brief(card) for card in cards}
    statuses = {card.get("id"): str(card.get("meta", {}).get("status", "")).strip() for card in cards}
    return cards, updated_at, briefs, statuses


def load_activity_dates(cards: list[dict[str, Any]] | None = None) -> dict[str, str]:
    """Latest deterministic activity per formal card from rollback state.

    Wrong-card history remains the source for error dates.  This read-only
    overlay closes the seven-day de-duplication gap for later formal scores and
    prior warmup delivery without treating file mtimes as learning evidence.
    """

    latest: dict[str, str] = {}

    def record(card_id: Any, raw_day: Any) -> None:
        normalized_id = str(card_id or "").strip()
        normalized_day = str(raw_day or "").strip()
        if not FORMAL_ID_RE.fullmatch(normalized_id):
            return
        try:
            datetime.strptime(normalized_day, "%Y-%m-%d")
        except ValueError:
            return
        if normalized_id not in latest or normalized_day > latest[normalized_id]:
            latest[normalized_id] = normalized_day

    units: list[dict[str, Any]] = []
    if ROLLBACK_UNITS_PATH.exists():
        try:
            raw_units = json.loads(ROLLBACK_UNITS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("复习单元.json 不是有效 JSON，无法安全执行七天去重") from exc
        if not isinstance(raw_units, list):
            raise ValueError("复习单元.json 顶层必须是数组，无法安全执行七天去重")
        units = [item for item in raw_units if isinstance(item, dict)]

    card_by_unit_id: dict[str, str] = {}
    for unit in units:
        card_id = str(unit.get("关联错题ID") or "").strip()
        unit_id = str(unit.get("复习单元ID") or "").strip()
        if FORMAL_ID_RE.fullmatch(card_id) and unit_id:
            card_by_unit_id[unit_id] = card_id
        # A transfer score can update the anchor unit while a different card
        # was actually delivered. Only the immutable event identifies that
        # delivery; the unit's last-review date is not activity for its anchor.
        for field in ("首次学习日期", "最近复发日期"):
            record(card_id, unit.get(field))

    if cards is None:
        snapshot = ROLLBACK_UNITS_PATH.parent.parent / "错题知识网络/生成/wrong_questions.json"
        document = json.loads(snapshot.read_text(encoding="utf-8")) if snapshot.exists() else {}
        cards = document.get("cards", []) if isinstance(document, dict) else []
    for card in cards:
        meta = card.get("meta") if isinstance(card.get("meta"), dict) else {}
        card_id = card.get("id") or meta.get("id")
        record(card_id, meta.get("date"))
        for field in ("wrong_history", "mastery_history"):
            for event_day in intake_lib.extract_dates(meta.get(field)):
                record(card_id, event_day)

    def jsonl(path: Path, label: str) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        result: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{label} 第 {line_number} 行不是有效 JSON，无法安全执行七天去重"
                ) from exc
            if not isinstance(item, dict):
                raise ValueError(
                    f"{label} 第 {line_number} 行必须是对象，无法安全执行七天去重"
                )
            result.append(item)
        return result

    for event in jsonl(ROLLBACK_REVIEW_LOG_PATH, "复习记录.jsonl"):
        card_id = str(event.get("delivered_card_id") or "").strip()
        if not card_id:
            card_id = card_by_unit_id.get(str(event.get("unit_id") or "").strip(), "")
        record(card_id, event.get("date"))

    for queue in jsonl(ROLLBACK_WARMUP_LOG_PATH, "学习前5题记录.jsonl"):
        queue_day = queue.get("date")
        selected = queue.get("selected", [])
        if not isinstance(selected, list):
            raise ValueError("学习前5题记录.jsonl 的 selected 必须是数组")
        for item in selected:
            if isinstance(item, dict):
                card_id = item.get("delivered_card_id") or item.get("id")
            else:
                card_id = item
            record(card_id, queue_day)
    return latest


def effective_activity_date(
    brief: dict[str, Any], card_id: str, activity_dates: dict[str, str]
) -> tuple[str, bool]:
    history_day = str(brief.get("latest") or "").strip()
    rollback_day = str(activity_dates.get(card_id) or "").strip()
    if rollback_day and (not history_day or rollback_day > history_day):
        return rollback_day, True
    return history_day, False


def print_ranked(preferred: list[str], recent: list[str], top: int, tail_note: str) -> None:
    shown = 0
    for line in preferred + recent:
        if shown >= top:
            break
        shown += 1
        print(f"{shown}. {line}")
    leftover = len(preferred) + len(recent) - shown
    if shown < top:
        print(f"不足 {top} 道：可用候选只有 {shown} 道，不用弱边硬凑。")
    else:
        print(f"（候选池剩余 {leftover} 道。{tail_note}）")


def evidence_text(brief: dict[str, Any]) -> str:
    evidence = brief.get("evidence") if isinstance(brief.get("evidence"), dict) else {}
    method_gap = evidence.get("method_gap") if isinstance(evidence.get("method_gap"), dict) else {}
    parts = [f"来源：{evidence.get('origin_label', '具体错因缺失')}"]
    for field, label in (
        ("missed_action", "漏掉动作"),
        ("expected_first_action", "第一动作"),
        ("method_trigger", "方法触发"),
        ("action_gap_type", "断点类型"),
        ("confidence", "置信度"),
    ):
        if method_gap.get(field):
            parts.append(f"{label}：{method_gap[field]}")
    parts.append(f"需确认：{'是' if method_gap.get('need_user_confirmation') else '否'}")
    parts.append(f"源版本：{evidence.get('source_version', '')}")
    return "｜".join(parts)


def run_single(args: argparse.Namespace) -> int:
    candidates = related_candidates(args.id, args.pool)
    if candidates is None:
        return 1

    _cards, updated_at, briefs, statuses = load_context()
    activity_dates = load_activity_dates(_cards)
    ranking_day = reference_date(getattr(args, "date", None))
    permanent_exclusions = load_permanent_delivery_exclusion_ids(ranking_day)

    print(f"# redo recommendations for {args.id}")
    print(f"generated_json_updated_at={updated_at}（须为本次 closeout rebuild 之后）")
    if not candidates:
        print("related 没有返回候选：这可能是该知识点/错因节点的第一题，请在报告中说明。")
        return 0

    preferred: list[str] = []
    recent: list[str] = []
    skipped_mastered = 0
    skipped_independent_correct = 0
    for card_id, score, level, title, reason in candidates:
        if statuses.get(card_id) == intake_lib.MASTERED:
            skipped_mastered += 1
            continue
        if card_id in permanent_exclusions:
            skipped_independent_correct += 1
            continue
        brief = briefs.get(card_id)
        if brief is None:
            preferred.append(f"{card_id}｜{title}｜数据未入 generated JSON（rebuild 后重试）｜{level}{score}：{reason}")
            continue
        latest_day, from_rollback = effective_activity_date(brief, card_id, activity_dates)
        gap = days_since(latest_day, ranking_day) if latest_day else None
        line = f"{intake_lib.redo_line(brief)}｜{level}{score}：{reason or '标签相似'}"
        if from_rollback:
            line += f"｜系统最近活动 {latest_day}"
        if gap is not None and gap < 0:
            recent.append(f"{line}｜⚠️ 最近记录晚于参考日 {ranking_day.isoformat()}，历史排名需人工核对")
        elif gap is not None and gap <= args.gap_days:
            recent.append(f"{line}｜⚠️ 相对参考日 {gap} 天内做过")
        else:
            preferred.append(line)

    print(
        f"（已跳过 {skipped_mastered} 道已掌握题，"
        f"{skipped_independent_correct} 道曾无提示独立做对题。）"
    )
    print_ranked(preferred, [], args.top, "最终顺序仍按贴合度人工确认。")
    if recent:
        print("\n近 7 天排除（不进入正式 shortlist）：")
        for line in recent:
            print(f"- {line}")
    return 0


def run_unified(args: argparse.Namespace) -> int:
    ranking_day = reference_date(getattr(args, "date", None))
    day = ranking_day.isoformat()
    seed_ids: list[str] = []
    for raw_id in getattr(args, "seed_id", []) or []:
        card_id = str(raw_id).strip()
        if not FORMAL_ID_RE.fullmatch(card_id):
            raise ValueError(f"无效 --seed-id: {card_id}")
        if card_id not in seed_ids:
            seed_ids.append(card_id)
    if not seed_ids:
        raise ValueError("统一筛题必须显式提供至少一个 --seed-id；不再扫描全库当日 touched 卡")
    cards, updated_at, briefs, statuses = load_context()
    activity_dates = load_activity_dates(cards)
    permanent_exclusions = load_permanent_delivery_exclusion_ids(ranking_day)
    if not cards:
        print(
            f"generated JSON 不可用（{updated_at}）：请先完成相关单题入库并直接运行 wrongnet.py rebuild",
            file=sys.stderr,
        )
        return 1
    missing_seed_ids = [card_id for card_id in seed_ids if card_id not in briefs]
    if missing_seed_ids:
        raise ValueError(
            "--seed-id 不在当前 generated JSON 中；拒绝用 stale/误拼 ID 筛题："
            + ", ".join(missing_seed_ids)
        )

    print(f"# unified redo shortlist for {day}")
    print(f"generated_json_updated_at={updated_at}（须为相关单题入库的 rebuild 之后）")
    print(f"明确 seed {len(seed_ids)} 道（排名参考日 {day}；未扫描全库 touched 卡）：")
    for tid in seed_ids:
        brief = briefs.get(tid)
        assert brief is not None
        head = f"{tid}｜{brief['source'] or brief['title']}" if (brief["source"] or brief["title"]) else tid
        extra = f"｜错点：{brief['wrong_point']}" if brief["wrong_point"] else ""
        status = f"｜status：{brief['status']}" if brief["status"] else ""
        print(f"- {head}{extra}{status}｜{evidence_text(brief)}")

    seed_set = set(seed_ids)
    merged: dict[str, dict[str, Any]] = {}
    failures = 0
    skipped_mastered: set[str] = set()
    skipped_independent_correct: set[str] = set()
    for tid in seed_ids:
        candidates = related_candidates(tid, args.pool)
        if candidates is None:
            failures += 1
            continue
        for cid, score, level, title, reason in candidates:
            if cid in seed_set:
                continue
            if statuses.get(cid) == intake_lib.MASTERED:
                skipped_mastered.add(cid)
                continue
            if cid in permanent_exclusions:
                skipped_independent_correct.add(cid)
                continue
            entry = merged.setdefault(
                cid,
                {
                    "level": "",
                    "score": 0.0,
                    "score_str": "",
                    "title": title,
                    "reason": "",
                    "hits": set(),
                    "evidence_hits": set(),
                    "evidence_score": 0,
                    "evidence_reasons": set(),
                    "knowledge_hits": set(),
                    "knowledge_reasons": set(),
                },
            )
            entry["hits"].add(tid)
            candidate_brief = briefs.get(cid)
            anchor_brief = briefs.get(tid)
            if candidate_brief is not None and anchor_brief is not None:
                match_score, match_reasons = training_evidence.exact_evidence_match(
                    anchor_brief.get("evidence", {}),
                    candidate_brief.get("evidence", {}),
                )
                if match_score > 0:
                    entry["evidence_hits"].add(tid)
                    entry["evidence_score"] = max(entry["evidence_score"], match_score)
                    entry["evidence_reasons"].update(match_reasons)
                shared = training_evidence.shared_knowledge(
                    anchor_brief.get("evidence", {}),
                    candidate_brief.get("evidence", {}),
                )
                if shared:
                    entry["knowledge_hits"].add(tid)
                    entry["knowledge_reasons"].update(shared)
            if (LEVEL_RANK.get(level, 0), float(score)) > (LEVEL_RANK.get(entry["level"], 0), entry["score"]):
                entry["level"] = level
                entry["score"] = float(score)
                entry["score_str"] = score
                entry["reason"] = reason or entry["reason"]

    # The relationship graph may not contain a candidate for a newly exposed
    # personal gap.  The user explicitly prefers an existing in-library
    # knowledge fallback over generated questions, so search the current
    # formal snapshot for shared knowledge after exact evidence collection.
    for cid, candidate_brief in briefs.items():
        if cid in seed_set or statuses.get(cid) == intake_lib.MASTERED:
            continue
        if cid in permanent_exclusions:
            skipped_independent_correct.add(cid)
            continue
        for tid in seed_ids:
            anchor_brief = briefs.get(tid)
            if anchor_brief is None:
                continue
            shared = training_evidence.shared_knowledge(
                anchor_brief.get("evidence", {}),
                candidate_brief.get("evidence", {}),
            )
            if not shared:
                continue
            entry = merged.setdefault(
                cid,
                {
                    "level": "",
                    "score": 0.0,
                    "score_str": "",
                    "title": candidate_brief.get("title") or cid,
                    "reason": "",
                    "hits": set(),
                    "evidence_hits": set(),
                    "evidence_score": 0,
                    "evidence_reasons": set(),
                    "knowledge_hits": set(),
                    "knowledge_reasons": set(),
                },
            )
            entry["hits"].add(tid)
            entry["knowledge_hits"].add(tid)
            entry["knowledge_reasons"].update(shared)

    print(
        f"\n合并旧题候选（已排除本次 seed 本身，"
        f"已跳过 {len(skipped_mastered)} 道已掌握，"
        f"{len(skipped_independent_correct)} 道曾无提示独立做对）："
    )
    if failures:
        print(f"⚠️ {failures} 道 seed 的 related 查询失败，候选可能不完整。")
    if not merged:
        print("- 无旧题候选：可能均为对应知识点/错因节点的第一题，请在复盘中说明。")
        return 0

    ordered = sorted(
        merged.items(),
        key=lambda kv: (
            0 if kv[1]["evidence_score"] > 0 else 1,
            -len(kv[1]["evidence_hits"]),
            -kv[1]["evidence_score"],
            -len(kv[1]["knowledge_hits"]),
            -len(kv[1]["knowledge_reasons"]),
            -len(kv[1]["hits"]),
            -LEVEL_RANK.get(kv[1]["level"], 0),
            -kv[1]["score"],
            kv[0],
        ),
    )
    preferred: list[str] = []
    recent: list[str] = []
    semantic_review: list[str] = []
    for cid, entry in ordered:
        hits = f"命中 seed {len(entry['hits'])} 道：{'、'.join(sorted(entry['hits']))}"
        level_score = f"{entry['level']}{entry['score_str']}"
        brief = briefs.get(cid)
        if brief is None:
            semantic_review.append(
                f"{cid}｜{entry['title']}｜数据未入 generated JSON，不能证明具体错因｜{level_score}｜{hits}"
            )
            continue
        if entry["evidence_score"] <= 0 and not entry["knowledge_hits"]:
            semantic_review.append(
                f"{intake_lib.redo_line(brief)}｜{level_score}：{entry['reason'] or '仅网络相似'}｜{hits}｜"
                "没有确定性具体错因命中；只可由模型读取双方证据后语义复核，不进入正式排序"
            )
            continue
        latest_day, from_rollback = effective_activity_date(brief, cid, activity_dates)
        gap = days_since(latest_day, ranking_day) if latest_day else None
        if entry["evidence_score"] > 0:
            evidence_reason = "、".join(sorted(entry["evidence_reasons"]))
            line = (
                f"{intake_lib.redo_line(brief)}｜具体错因命中 {entry['evidence_score']}：{evidence_reason}｜"
                f"{level_score}：{entry['reason'] or '网络关系仅作佐证'}｜{hits}"
            )
        else:
            shared_knowledge = "、".join(sorted(entry["knowledge_reasons"]))
            line = (
                f"{intake_lib.redo_line(brief)}｜知识点补位：{shared_knowledge}｜"
                "不代表命中同一具体错因｜"
                f"{hits}"
            )
        if from_rollback:
            line += f"｜系统最近活动 {latest_day}"
        if gap is not None and gap < 0:
            recent.append(f"{line}｜⚠️ 最近记录晚于参考日 {day}，历史排名需人工核对")
        elif gap is not None and gap <= args.gap_days:
            recent.append(f"{line}｜⚠️ 相对参考日 {gap} 天内做过")
        else:
            preferred.append(line)

    print_ranked(
        preferred,
        [],
        args.top,
        "最终顺序先取确定性具体错因命中；不足时才取已入库知识点补位，不生成新题。",
    )
    if recent:
        print("\n近 7 天排除（不进入正式 shortlist）：")
        for line in recent:
            print(f"- {line}")
    if semantic_review:
        print("\n待语义复核（宽泛知识点或网络分数不能直接入选）：")
        for line in semantic_review:
            print(f"- {line}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Old-question recommendations with redo dates.")
    parser.add_argument("--id", help="单题模式：编号，例如 GS-666（点名查询相似题时用）")
    parser.add_argument("--seed-id", action="append", default=[], help="统一筛题 seed formal ID；可重复")
    parser.add_argument("--today", action="store_true", help="仅将排名参考日设为今天；仍必须显式 --seed-id")
    parser.add_argument("--date", help="排名参考日 YYYY-MM-DD（默认今天）")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--pool", type=int, default=14, help="每道题从 related 拉取的候选数")
    parser.add_argument(
        "--gap-days",
        type=int,
        default=7,
        help="排除当天至恰好第 N 天内活动的题；第 N+1 天起可推荐",
    )
    args = parser.parse_args()

    if args.today and args.date:
        parser.error("--today 与 --date 不能同时使用")
    if args.date:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            parser.error("--date 需要 YYYY-MM-DD 格式")
    unified = bool(args.seed_id)
    if bool(args.id) == unified:
        parser.error("需要且只能选一种模式：--id {编号}，或一个及以上 --seed-id FORMAL-ID")
    if args.today and not unified:
        parser.error("--today 不再扫描全库 touched 卡；请显式提供 --seed-id")
    for seed_id in args.seed_id:
        if not FORMAL_ID_RE.fullmatch(seed_id):
            parser.error(f"无效 --seed-id: {seed_id}")

    try:
        return run_unified(args) if unified else run_single(args)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
