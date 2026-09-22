#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEDULER_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCHEDULER_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCHEDULER_SCRIPTS_DIR))
UNITS_PATH = ROOT / "复习单元.json"
LOG_PATH = ROOT / "复习记录.jsonl"
PROGRESS_PATH = ROOT / "学习进度.json"
WARMUP_LOG_PATH = ROOT / "学习前5题记录.jsonl"
QUICK_INTAKE_EVENTS_PATH = ROOT / "快速入库事件.jsonl"
OUT_DIR = ROOT / "生成"
REPO_ROOT = ROOT.parent
WRONGNET_CARDS_DIR = REPO_ROOT / "错题知识网络" / "错题卡"
WRONGNET_SCRIPTS_DIR = REPO_ROOT / "错题知识网络" / "scripts"
if str(WRONGNET_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(WRONGNET_SCRIPTS_DIR))

MODULES = ["高等数学", "线性代数", "概率论与数理统计"]
DIFFICULTY_WEIGHT = {
    "A简单": 1,
    "B中等": 2,
    "C困难": 3,
    "A": 1,
    "B": 2,
    "C": 3,
}
DEFAULT_CYCLE = [0, 1, 2, 4, 7, 14, 21, 30, 45, 60]
DELAYED_SUCCESS_INTERVALS = [3, 7, 14, 30, 45]
MASTERED_STATUSES = {"已掌握", "复做正确", "已做对"}
INDEPENDENT_CORRECT_SCORE_MINIMUM = 4
WARMUP_SCHEMA_VERSION = "prestudy-warmup-v4"
SEMANTIC_WARMUP_SCHEMA_VERSION = "prestudy-warmup-v5"
SUPPORTED_WARMUP_SCHEMA_VERSIONS = {
    "prestudy-warmup-v3",
    WARMUP_SCHEMA_VERSION,
    SEMANTIC_WARMUP_SCHEMA_VERSION,
}
PLACEHOLDERS = {"", "待补充", "无", "未知", "none", "null", "-"}
CARD_ID_PATTERN = re.compile(r"^(GS|LA|PR)-\d{3,}$")
DATE_PATTERN = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
WRONG_EVENT_PATTERN = re.compile(
    r"第\s*\d+\s*次(?:做错|错)|首次做错|再次.{0,40}(?:做错|出错|错误)|"
    r"复发|仍(?:然)?(?:做错|出错|不会)|无法启动|选错(?:方法|入口)|做错"
)
NEGATED_WRONG_EVENT_PATTERN = re.compile(
    r"(?:没有|未|并未|不再|并没有|无).{0,12}(?:再次)?(?:做错|出错|犯错|错误)|"
    r"(?:没有|未|并未|不再|并没有|无).{0,8}复发"
)
PREVENTIVE_WRONG_EVENT_PATTERN = re.compile(
    r"(?:避免|防止|以免|不要|不应|谨防|预防|容易).{0,16}"
    r"(?:再次|再)?(?:做错|出错|犯错|错误|复发)"
)
SUCCESS_EVENT_PATTERN = re.compile(
    r"复做(?:正确|做对|成功)|纠错(?:通过|成功)|独立做对|已经修正|已掌握"
)
INDEPENDENT_HISTORY_PATTERN = re.compile(
    r"无提示|未使用提示|没有任何提示|独立|闭卷"
)
WHOLE_QUESTION_HISTORY_PATTERN = re.compile(
    r"整题|全题|本题|这道题|完整(?:作答|复做|完成)"
)
CORRECT_HISTORY_RESULT_PATTERN = re.compile(
    r"正确|做对|答对|通过|完成|做出"
)
EXPLICIT_USER_CORRECT_REPORT_PATTERN = re.compile(
    r"用户(?:明确)?(?:反馈|确认|表示|说明)"
)
USER_REPORTED_CORRECT_RESULT_PATTERN = re.compile(
    r"复做(?:结果|作答结果)?正确|作答正确|做对|答对|算对"
)
PARTIAL_HISTORY_OBJECT_PATTERN = re.compile(
    r"小问|第一问|第\s*[一二三四五六七八九十\d]+\s*问|局部|第一步|这一步|某一步|步骤|公式|"
    r"部分(?:计算|过程|方法)|一个(?:小问|步骤|局部)|"
    r"(?:只|仅)[^\n；。]{0,8}(?:做对|答对|算对)[^\n；。]{0,6}"
    r"(?:一半|前半(?:部分)?|后半(?:部分)?|部分)"
)
NEGATED_CORRECT_RESULT_PATTERN = re.compile(
    r"(?:没有|没|未|并未|尚未|无法|不能|不算|并非|不是|并不是)[^\n；。]{0,8}"
    r"(?:复做(?:结果|作答结果)?正确|作答正确|做对|答对|算对|通过|完成)"
)
STRICT_INDEPENDENT_CORRECT_PATTERN = re.compile(
    r"(?:无提示[^\n；。]{0,8}独立|独立[^\n；。]{0,8}无提示)"
    r"[^\n；。]{0,10}(?:做对|答对|正确|完成)"
)
INCOMPLETE_WHOLE_QUESTION_PATTERN = re.compile(
    r"(?:整题|全题|本题|这道题)[^\n；。]{0,10}"
    r"(?:未|尚未|没有|无法|不能|不算)[^\n；。]{0,8}"
    r"(?:完成|做对|答对|正确|通过)|"
    r"(?:整题|全题|本题|这道题)[^\n；。]{0,8}(?:仍|尚)?待(?:完整)?复做|"
    r"(?:未|尚未|没有|无法|不能|不算)[^\n；。]{0,8}"
    r"(?:完成|做对|答对|正确|通过)[^\n；。]{0,10}"
    r"(?:整题|全题|本题|这道题)"
)
HINTED_CORRECT_HISTORY_PATTERN = re.compile(
    r"提示(?:后|之后|下|才)|经过?提示|"
    r"(?:根据|借助|依靠|依赖|看过|得到|收到)[^\n；。]{0,12}提示|"
    r"在[^\n；。]{0,12}(?:提示|引导)下|"
    r"(?:经过?|在)?讲解后|经讲解|"
    r"看过[^\n；。]{0,6}(?:答案|解析)|参考(?:答案|解析)后"
)
STRONG_WRONG_EVENT_PATTERN = re.compile(
    r"第\s*\d+\s*次(?:做错|错)|首次做错|明确复发|仍(?:然)?(?:做错|出错|不会)|"
    r"无法启动|选错(?:方法|入口)"
)
CORE_UNIT_FIELDS = {
    "复习单元ID",
    "科目",
    "模块",
    "内容名称",
    "类型",
    "首次学习日期",
    "上次复习日期",
    "下次复习日期",
    "当前间隔天数",
    "掌握度",
    "错误次数",
    "重要程度",
    "难度等级",
    "复习方式",
    "备注",
}
WRONGNET_METADATA_FIELDS = {
    "模块",
    "内容名称",
    "知识点",
    "错因类型",
    "难度等级",
    "重要程度",
    "源错点",
    "源卡状态",
}
BROAD_KNOWLEDGE = {
    "一元函数微分学应用",
    "极限与连续",
    "定积分",
    "高等数学综合待精分",
    "线性代数综合待精分",
    "概率论综合待精分",
    "多元函数微分学",
    "矩阵运算",
    "不定积分",
    "数列极限",
    "无穷级数",
    "数项级数敛散性判别",
    "正项级数敛散性判别",
}


class RollbackSyncError(ValueError):
    """定点回滚无法在证据与结构门禁内安全完成。"""


VERSION_UNCHECKED = object()


@contextmanager
def exclusive_file_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def append_jsonl_entry(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def safe_parse_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return parse_date(str(value))
    except ValueError:
        return None


def format_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def today_from_arg(value: str | None) -> date:
    return parse_date(value) or date.today()


def load_units() -> list[dict[str, Any]]:
    if not UNITS_PATH.exists():
        return []
    return json.loads(UNITS_PATH.read_text(encoding="utf-8"))


def load_units_with_version() -> tuple[list[dict[str, Any]], str | None]:
    if not UNITS_PATH.exists():
        return [], None
    raw = UNITS_PATH.read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def validate_iso_date(value: Any, field: str, *, nullable: bool = True) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        raise RollbackSyncError(f"{field} 必须是 YYYY-MM-DD" + (" 或 null" if nullable else ""))
    try:
        parse_date(value)
    except ValueError as exc:
        raise RollbackSyncError(f"{field} 不是有效日期：{value}") from exc


def validate_units_document(
    units: Any,
    *,
    target_unit_id: str | None = None,
    exam_date: date | None = None,
) -> None:
    if not isinstance(units, list):
        raise RollbackSyncError("复习单元根结构必须是数组")

    seen: set[str] = set()
    target: dict[str, Any] | None = None
    for index, unit in enumerate(units):
        if not isinstance(unit, dict):
            raise RollbackSyncError(f"第 {index + 1} 个复习单元不是对象")
        unit_id = unit.get("复习单元ID")
        if not isinstance(unit_id, str) or not unit_id.strip():
            raise RollbackSyncError(f"第 {index + 1} 个复习单元缺少有效 ID")
        if unit_id in seen:
            raise RollbackSyncError(f"复习单元 ID 重复：{unit_id}")
        seen.add(unit_id)
        if target_unit_id and unit_id == target_unit_id:
            target = unit

    if not target_unit_id:
        return
    if target is None:
        raise RollbackSyncError(f"写入后未找到目标复习单元：{target_unit_id}")

    missing = sorted(CORE_UNIT_FIELDS - target.keys())
    if missing:
        raise RollbackSyncError(f"目标复习单元缺少字段：{', '.join(missing)}")
    for field in ("首次学习日期", "上次复习日期", "下次复习日期", "最近复发日期"):
        if field in target:
            validate_iso_date(target.get(field), field, nullable=field != "首次学习日期")
    for field in ("当前间隔天数", "错误次数", "重要程度"):
        value = target.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RollbackSyncError(f"目标字段 {field} 必须是非负整数")
    for field in ("延迟复习阶段", "连续延迟成功次数", "复发次数", "同方法断点复发次数"):
        if field in target:
            value = target[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RollbackSyncError(f"目标字段 {field} 必须是非负整数")
    for field in ("知识点", "错因类型", "调度事件历史"):
        if field in target and not isinstance(target[field], list):
            raise RollbackSyncError(f"目标字段 {field} 必须是数组")
    score_events = target.get("评分事件历史", [])
    if not isinstance(score_events, list):
        raise RollbackSyncError("评分事件历史必须是数组")
    score_event_ids: list[str] = []
    for event in score_events:
        if not isinstance(event, dict):
            raise RollbackSyncError("评分事件历史每项必须是对象")
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise RollbackSyncError("评分事件缺少 event_id")
        score_event_ids.append(event_id)
    if len(score_event_ids) != len(set(score_event_ids)):
        raise RollbackSyncError("评分事件 event_id 不能重复")
    if target.get("调度优先级") not in {None, "高", "普通"}:
        raise RollbackSyncError("调度优先级只能是高或普通")
    sync_state = target.get("定点同步状态")
    if sync_state is not None:
        if not isinstance(sync_state, dict):
            raise RollbackSyncError("定点同步状态必须是对象")
        source_version = sync_state.get("源版本")
        if not isinstance(source_version, str) or not re.fullmatch(r"[0-9a-f]{64}", source_version):
            raise RollbackSyncError("定点同步状态.源版本必须是 SHA-256")
        event_ids = sync_state.get("已处理错题事件ID", [])
        if not isinstance(event_ids, list) or not all(isinstance(item, str) for item in event_ids):
            raise RollbackSyncError("定点同步状态.已处理错题事件ID 必须是字符串数组")
        if len(event_ids) != len(set(event_ids)):
            raise RollbackSyncError("定点同步状态.已处理错题事件ID 不能重复")
    if exam_date and target.get("下次复习日期"):
        next_date = parse_date(target["下次复习日期"])
        if next_date and next_date > exam_date:
            raise RollbackSyncError("下次复习日期不得晚于考试日期")


def atomic_save_units(
    units: list[dict[str, Any]],
    *,
    target_unit_id: str | None = None,
    exam_date: date | None = None,
    expected_version: str | None | object = VERSION_UNCHECKED,
) -> None:
    validate_units_document(units, target_unit_id=target_unit_id, exam_date=exam_date)
    UNITS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(units, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    lock_path = UNITS_PATH.with_name(f".{UNITS_PATH.name}.lock")
    lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    temp_path: Path | None = None
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        descriptor, temp_name = tempfile.mkstemp(
            dir=UNITS_PATH.parent,
            prefix=f".{UNITS_PATH.name}.",
            suffix=".tmp",
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            staged = json.loads(temp_path.read_text(encoding="utf-8"))
            validate_units_document(staged, target_unit_id=target_unit_id, exam_date=exam_date)

            if expected_version is not VERSION_UNCHECKED:
                if expected_version is None:
                    if UNITS_PATH.exists():
                        raise RollbackSyncError("复习单元文件在写入前由其他进程创建，拒绝覆盖")
                else:
                    if not UNITS_PATH.exists():
                        raise RollbackSyncError("复习单元文件在写入前被其他进程删除")
                    current_version = hashlib.sha256(UNITS_PATH.read_bytes()).hexdigest()
                    if current_version != expected_version:
                        raise RollbackSyncError("复习单元文件已被其他进程修改，拒绝覆盖")

            os.replace(temp_path, UNITS_PATH)
            directory_fd = os.open(UNITS_PATH.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temp_path.exists():
                temp_path.unlink()
    finally:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(lock_descriptor)


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def strip_matching_outer_quotes(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1].strip()
    return text


def priority_score(unit: dict[str, Any], today: date) -> int:
    mistake_count = to_int(unit.get("错误次数"))
    importance = to_int(unit.get("重要程度"), 3)
    mastery = to_int(unit.get("掌握度"))
    difficulty = DIFFICULTY_WEIGHT.get(str(unit.get("难度等级", "")), 2)
    scheduling_priority = 30 if unit.get("调度优先级") == "高" else 0
    return (
        overdue_days(unit, today) * 3
        + mistake_count * 2
        + importance * 2
        + difficulty
        + scheduling_priority
        - mastery
    )


def overdue_days(unit: dict[str, Any], today: date) -> int:
    next_date = parse_date(unit.get("下次复习日期"))
    return 0 if not next_date else max(0, (today - next_date).days)


def sort_key(unit: dict[str, Any], today: date) -> tuple[int, int, int, int]:
    # 下次复习日期只决定是否到期；到期超过日容量时，由综合优先级先排序。
    type_rank = {
        "错题": 0,
        "题型": 1,
        "方法模板": 2,
        "定理": 3,
        "公式": 4,
    }.get(str(unit.get("类型")), 5)
    mastery = to_int(unit.get("掌握度"))
    return (-priority_score(unit, today), -overdue_days(unit, today), type_rank, mastery)


def due_units(units: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    result = []
    for unit in units:
        next_date = parse_date(unit.get("下次复习日期"))
        if next_date and next_date <= today:
            result.append(unit)
    return sorted(result, key=lambda u: sort_key(u, today))


def tomorrow_units(units: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    tomorrow = today + timedelta(days=1)
    return sorted(
        [u for u in units if parse_date(u.get("下次复习日期")) == tomorrow],
        key=lambda u: sort_key(u, today),
    )


def workload_bucket(unit: dict[str, Any], today: date) -> str:
    mastery = to_int(unit.get("掌握度"))
    mistakes = to_int(unit.get("错误次数"))
    importance = to_int(unit.get("重要程度"), 3)
    unit_type = unit.get("类型")
    days_overdue = overdue_days(unit, today)

    if (
        unit.get("调度优先级") == "高"
        or mastery <= 2
        or mistakes >= 3
        or unit_type == "错题"
        or days_overdue >= 2
    ):
        return "必须完成"
    if mastery == 3 or importance >= 4:
        return "尽量完成"
    return "有空再做"


def assign_workload_buckets(due: list[dict[str, Any]], today: date) -> dict[str, str]:
    raw = {unit["复习单元ID"]: workload_bucket(unit, today) for unit in due}
    if len(due) <= 8:
        return raw

    # 任务爆炸时不把所有高危项硬塞进同一天；先保住前 6 个最该做的。
    assigned: dict[str, str] = {}
    must_limit = 6
    try_limit = 5
    for index, unit in enumerate(due):
        unit_id = unit["复习单元ID"]
        if index < must_limit:
            assigned[unit_id] = "必须完成"
        elif index < must_limit + try_limit:
            assigned[unit_id] = "尽量完成"
        else:
            assigned[unit_id] = "有空再做"
    return assigned


def estimate_minutes(unit: dict[str, Any]) -> str:
    unit_type = unit.get("类型")
    mastery = to_int(unit.get("掌握度"))
    if unit_type == "错题":
        return "12-18 分钟" if mastery <= 2 else "8-12 分钟"
    if unit_type == "方法模板":
        return "8-12 分钟"
    if unit_type in {"公式", "定理"}:
        return "3-6 分钟"
    return "10-15 分钟"


def render_unit_item(
    index: int,
    unit: dict[str, Any],
    today: date,
    bucket_map: dict[str, str],
) -> list[str]:
    return [
        f"{index}. 复习单元：{unit.get('内容名称')}",
        f"   类型：{unit.get('类型')}",
        f"   上次掌握度：{unit.get('掌握度')} 分",
        f"   本次复习方式：{unit.get('复习方式')}",
        f"   预计时间：{estimate_minutes(unit)}",
        f"   任务等级：{bucket_map.get(unit.get('复习单元ID'), workload_bucket(unit, today))}",
        f"   复习后需要评分：0-5 分，并更新 `{unit.get('复习单元ID')}`",
    ]


def render_today(units: list[dict[str, Any]], today: date) -> str:
    detail_limit = 30
    due = due_units(units, today)
    by_module = defaultdict(list)
    for unit in due:
        by_module[unit.get("模块", "未分类")].append(unit)
    bucket_map = assign_workload_buckets(due, today)

    wrong_count = sum(1 for unit in due if unit.get("类型") == "错题")
    high_risk_count = sum(
        1
        for unit in due
        if to_int(unit.get("掌握度")) <= 2 or to_int(unit.get("错误次数")) >= 3
    )
    new_today = [u for u in units if parse_date(u.get("首次学习日期")) == today]
    tomorrow = tomorrow_units(units, today)

    lines: list[str] = [f"# 【{today.isoformat()}】", ""]
    lines.extend(
        [
            "## 一、今日到期复习总览",
            f"- 高等数学：{len(by_module.get('高等数学', []))} 个复习单元",
            f"- 线性代数：{len(by_module.get('线性代数', []))} 个复习单元",
            f"- 概率论与数理统计：{len(by_module.get('概率论与数理统计', []))} 个复习单元",
            f"- 错题重做：{wrong_count} 个",
            f"- 高危漏洞：{high_risk_count} 个",
            "",
        ]
    )

    lines.append("## 二、今日最高优先级任务")
    if due:
        for index, unit in enumerate(due[:5], start=1):
            score = priority_score(unit, today)
            lines.append(
                f"{index}. {unit.get('内容名称')}（优先级分数 {score}）：{unit.get('备注')}"
            )
    else:
        lines.append("今天没有到期复习单元；可以入库新学内容或做低频保持。")
    lines.append("")

    lines.append("## 三、今日数学一复习清单")
    if due:
        for bucket in ["必须完成", "尽量完成", "有空再做"]:
            bucket_units = [u for u in due if bucket_map.get(u.get("复习单元ID")) == bucket]
            if bucket_units:
                lines.extend([f"### {bucket}", ""])
                for unit in bucket_units[:12]:
                    lines.append(f"- {unit.get('内容名称')}")
                if len(bucket_units) > 12:
                    lines.append(f"- 另有 {len(bucket_units) - 12} 个低位单元暂不展开。")
                lines.append("")

    detail_ids = {unit.get("复习单元ID") for unit in due[:detail_limit]}
    for module in MODULES:
        lines.append(f"### 【{module}】")
        module_units = [u for u in by_module.get(module, []) if u.get("复习单元ID") in detail_ids]
        if not module_units:
            if by_module.get(module):
                lines.append("该模块有到期单元，但不在今日优先展开范围内。")
            else:
                lines.append("今天暂无到期复习单元。")
            lines.append("")
            continue
        for index, unit in enumerate(module_units, start=1):
            lines.extend(render_unit_item(index, unit, today, bucket_map))
            lines.append("")
        hidden = len(by_module.get(module, [])) - len(module_units)
        if hidden > 0:
            lines.append(f"该模块另有 {hidden} 个到期单元，今天先不展开，避免任务爆炸。")
            lines.append("")

    lines.append("## 四、今日新学内容入库")
    if new_today:
        lines.append("下面这些内容已作为 D0 单元入库，今天先做快速回滚，复习后按掌握度滚动到下一次。")
        for unit in new_today:
            cycle = ", ".join(f"D{day}" for day in DEFAULT_CYCLE)
            lines.append(f"- {unit.get('复习单元ID')}：{unit.get('内容名称')}；默认周期：{cycle}")
    else:
        lines.append("今天还没有登记新学内容。新学后用 `add` 命令拆成公式、题型、错题或方法模板。")
    lines.append("")

    lines.append("## 五、今日复习后更新")
    lines.extend(
        [
            "完成每个复习单元后记录 0-5 分；我会据此更新下次复习日期、当前间隔、错误次数和风险等级。",
            "",
            "评分更新格式：",
            "",
            "```bash",
            "python3 数学一回滚复习系统/scripts/scheduler.py score 复习单元ID 分数",
            "```",
            "",
            "如果评分为 0-2 分，该单元继续留在薄弱/高危队列；如果评分为 4-5 分，间隔会拉长。",
            "",
        ]
    )

    lines.append("## 六、明日预告")
    if tomorrow:
        for index, unit in enumerate(tomorrow[:12], start=1):
            lines.append(f"{index}. {unit.get('内容名称')}（当前掌握度 {unit.get('掌握度')} 分）")
    else:
        lines.append("目前账本里没有已经排到明天的单元；今天评分后，D0 内容通常会进入明天 D1。")
    lines.append("")

    return "\n".join(lines)


def next_interval_days(score: int, current_interval: int) -> int:
    base = max(1, current_interval)
    if score <= 2:
        return 1
    if current_interval <= 0 and score > 0:
        return 1
    if score == 5:
        return max(1, math.ceil(base * 2.5))
    if score == 4:
        return max(1, math.ceil(base * 2))
    if score == 3:
        return min(3, max(1, math.ceil(base * 1.4)))
    return 1


def infer_delayed_stage(unit: dict[str, Any]) -> int:
    if "延迟复习阶段" in unit:
        return min(len(DELAYED_SUCCESS_INTERVALS), to_int(unit.get("延迟复习阶段"), 0))
    interval = to_int(unit.get("当前间隔天数"), 0)
    stage = 0
    for index, candidate in enumerate(DELAYED_SUCCESS_INTERVALS, start=1):
        if interval >= candidate:
            stage = index
    return stage


def unit_is_high_risk(unit: dict[str, Any]) -> bool:
    return (
        unit.get("调度优先级") == "高"
        or to_int(unit.get("重要程度"), 3) >= 5
        or to_int(unit.get("错误次数"), 0) >= 3
        or to_int(unit.get("掌握度"), 3) <= 2
    )


def apply_exam_constraints(
    *,
    unit: dict[str, Any],
    current_date: date,
    exam_date: date,
    proposed_interval: int,
    stable: bool,
    unstable: bool,
) -> tuple[int, str | None, str]:
    remaining = (exam_date - current_date).days
    if remaining < 0:
        raise RollbackSyncError("评分日期晚于考试日期")
    if remaining == 0:
        if stable:
            return to_int(unit.get("当前间隔天数"), 0), None, "考前稳定暂缓"
        raise RollbackSyncError("考试日当天无法安排下一次短周期复习")

    if remaining <= 14 and stable:
        return to_int(unit.get("当前间隔天数"), 0), None, "考前稳定暂缓"

    interval = max(1, proposed_interval)
    high_risk = unit_is_high_risk(unit)
    if 15 <= remaining <= 30:
        if high_risk:
            interval = min(interval, 7)
        elif unstable:
            interval = min(interval, 14)
    elif remaining <= 14:
        interval = min(interval, 7)

    due = current_date + timedelta(days=interval)
    if due <= exam_date:
        return interval, due.isoformat(), "正常扩张" if stable else "不稳定短周期"

    if stable:
        if high_risk and remaining > 21:
            representative = exam_date - timedelta(days=18)
            if representative > current_date:
                return (
                    (representative - current_date).days,
                    representative.isoformat(),
                    "考前代表性检查",
                )
        return to_int(unit.get("当前间隔天数"), 0), None, "考前稳定暂缓"

    interval = min(interval, remaining)
    if interval <= 0:
        raise RollbackSyncError("考试期限内无法安排下一次复习")
    return interval, (current_date + timedelta(days=interval)).isoformat(), "不稳定短周期"


def append_log(entry: dict[str, Any]) -> None:
    append_jsonl_entry(LOG_PATH, entry)


def load_review_logs() -> list[dict[str, Any]]:
    if not LOG_PATH.exists():
        return []
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(LOG_PATH.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RollbackSyncError(f"复习记录第 {line_number} 行不是有效 JSON") from exc
        if not isinstance(item, dict):
            raise RollbackSyncError(f"复习记录第 {line_number} 行必须是对象")
        result.append(item)
    return result


def score_attempt_identity(unit_id: str, current_date: date, explicit_attempt_id: str | None) -> tuple[str, str]:
    attempt_id = (explicit_attempt_id or f"delayed:{unit_id}:{current_date.isoformat()}").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", attempt_id):
        raise RollbackSyncError("attempt_id 只能包含字母、数字、点、下划线、冒号或连字符")
    payload = f"{unit_id}\n{current_date.isoformat()}\n{attempt_id}"
    event_id = f"SCORE-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"
    return attempt_id, event_id


def score_event_matches(
    event: dict[str, Any],
    *,
    event_id: str,
    unit_id: str,
    current_date: date,
    score: int,
    attempt_type: str = "delayed",
) -> bool:
    return (
        event.get("event_id") == event_id
        and event.get("unit_id") == unit_id
        and event.get("date") == current_date.isoformat()
        and to_int(event.get("score"), -1) == score
        and event.get("attempt_type") == attempt_type
    )


def cmd_today(args: argparse.Namespace) -> None:
    current_date = today_from_arg(args.date)
    units = load_units()
    OUT_DIR.mkdir(exist_ok=True)
    content = render_today(units, current_date)
    output_path = OUT_DIR / f"{current_date.isoformat()}_今日复习队列.md"
    output_path.write_text(content, encoding="utf-8")
    print(f"已生成：{output_path}")


def frontmatter_block(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    return parts[1]


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"", "null", "None"}:
        return None
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.isdigit():
        return int(value)
    return strip_matching_outer_quotes(value)


def parse_card_frontmatter(path: Path) -> dict[str, Any] | None:
    block = frontmatter_block(path.read_text(encoding="utf-8"))
    if not block:
        return None

    data: dict[str, Any] = {}
    current_key: str | None = None
    current_nested: str | None = None
    current_list_item: dict[str, Any] | None = None
    current_list_indent: int | None = None
    lines = block.splitlines()

    def line_indent(raw_line: str) -> int:
        return len(raw_line) - len(raw_line.lstrip(" "))

    def is_block_scalar(value: str) -> bool:
        return value in {">", ">-", ">+", "|", "|-", "|+"}

    def collect_block(start_index: int, indent_level: int, folded: bool) -> tuple[str, int]:
        block_lines: list[str] = []
        index = start_index
        while index < len(lines):
            block_raw = lines[index]
            if not block_raw.strip():
                block_lines.append("")
                index += 1
                continue
            if line_indent(block_raw) < indent_level:
                break
            block_lines.append(block_raw[indent_level:])
            index += 1
        if not folded:
            return "\n".join(block_lines).strip(), index
        paragraphs: list[str] = []
        current: list[str] = []
        for block_line in block_lines:
            stripped = block_line.strip()
            if stripped:
                current.append(stripped)
            elif current:
                paragraphs.append(" ".join(current))
                current = []
        if current:
            paragraphs.append(" ".join(current))
        return "\n".join(paragraphs).strip(), index

    index = 0
    while index < len(lines):
        raw_line = lines[index]
        index += 1
        if not raw_line.strip():
            continue
        indent = line_indent(raw_line)
        stripped = raw_line.strip()
        if (
            indent in {2, 4}
            and stripped.startswith("- ")
            and current_key
            and current_nested
            and isinstance(data.get(current_key), dict)
        ):
            nested = data[current_key].setdefault(current_nested, [])
            if not isinstance(nested, list):
                raise RollbackSyncError(
                    f"{path.name} 的 {current_key}.{current_nested} 列表结构无效"
                )
            nested.append(parse_scalar(stripped[2:].strip()))
            continue
        if indent in {0, 2} and stripped.startswith("- ") and current_key:
            container = data.get(current_key)
            if container in (None, {}):
                container = []
                data[current_key] = container
            if not isinstance(container, list):
                raise RollbackSyncError(f"{path.name} 的 {current_key} 列表结构无效")
            item_text = stripped[2:].strip()
            mapping_match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", item_text)
            if mapping_match:
                key, value = mapping_match.groups()
                current_list_item = {key: parse_scalar(value) if value else None}
                current_list_indent = indent
                container.append(current_list_item)
            else:
                current_list_item = None
                current_list_indent = None
                container.append(parse_scalar(item_text))
            current_nested = None
            continue
        if (
            current_list_indent is not None
            and indent >= current_list_indent + 2
            and current_key
            and current_list_item is not None
            and isinstance(data.get(current_key), list)
            and not stripped.startswith("- ")
            and ":" in stripped
        ):
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if is_block_scalar(value):
                block_value, index = collect_block(index, indent + 2, value.startswith(">"))
                current_list_item[key] = block_value
            else:
                current_list_item[key] = parse_scalar(value) if value else None
            continue
        if indent == 2 and current_key and ":" in stripped:
            if not isinstance(data.get(current_key), dict):
                raise RollbackSyncError(f"{path.name} 的 {current_key} 映射结构无效")
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            current_nested = key
            current_list_item = None
            current_list_indent = None
            if is_block_scalar(value):
                block_value, index = collect_block(index, line_indent(raw_line) + 2, value.startswith(">"))
                data.setdefault(current_key, {})[key] = block_value
            else:
                data.setdefault(current_key, {})[key] = parse_scalar(value) if value else []
            continue
        if indent != 0 or ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key = key.strip()
        value = value.strip()
        current_key = key
        current_nested = None
        current_list_item = None
        current_list_indent = None
        if is_block_scalar(value):
            block_value, index = collect_block(index, line_indent(raw_line) + 2, value.startswith(">"))
            data[key] = block_value
        elif value:
            data[key] = parse_scalar(value)
        else:
            if key in {"knowledge", "error_causes", "methods", "traps", "keywords", "wrong_history"}:
                data[key] = []
            else:
                data[key] = {}
    return data


def normalize_date_match(match: tuple[str, str, str]) -> str:
    year, month, day = match
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def history_text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value or "")


def dates_from_card(data: dict[str, Any]) -> list[str]:
    text_parts = [
        str(data.get("title") or ""),
        str(data.get("source") or ""),
        str(data.get("date") or ""),
        " ".join(history_text(item) for item in (data.get("wrong_history") or [])),
    ]
    text = "\n".join(text_parts)
    matches = re.findall(r"(20\d{2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})", text)
    dates = sorted({normalize_date_match(match) for match in matches})
    return dates


def history_dates_from_card(data: dict[str, Any]) -> list[str]:
    text_parts = [
        str(data.get("title") or ""),
        str(data.get("source") or ""),
        " ".join(history_text(item) for item in (data.get("wrong_history") or [])),
    ]
    text = "\n".join(text_parts)
    matches = re.findall(r"(20\d{2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})", text)
    return sorted({normalize_date_match(match) for match in matches})


def first_date_from_history_entry(value: Any) -> date | None:
    text = history_text(value)
    match = re.search(r"(20\d{2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})", text)
    if not match:
        return None
    return safe_parse_date(normalize_date_match(match.groups()))


def formal_mastery_history_records_correct(
    data: dict[str, Any],
    *,
    on_or_before: date,
) -> bool:
    """Return explicit whole-question correctness recorded by the formal card.

    A numeric rating or a current mastery label alone is not enough: historical
    4/5 entries can describe only a partial method check.  Legacy text must
    establish whole-question correctness and either no-hint independence or an
    explicit user report that this problem was done correctly.  The latter is
    safe because the user's stated vocabulary defines "I did it correctly" as
    no-hint independent completion.  Later downgrade or failure entries never
    erase an earlier independent-correct record.
    """

    history = data.get("mastery_history")
    if isinstance(history, (str, dict)):
        history = [history]
    if not isinstance(history, list):
        return False

    for entry in history:
        if isinstance(entry, dict):
            entry_date = safe_parse_date(entry.get("date")) or first_date_from_history_entry(
                entry
            )
            result = str(entry.get("result") or "").strip().lower()
            if entry_date and entry_date > on_or_before:
                continue
            independent = entry.get("independent") is True
            hints_used = entry.get("hints_used")
            if (
                result in {"correct", "passed", "正确", "做对", "通过"}
                and independent
                and hints_used not in (True, 1, "true", "yes", "是")
            ):
                return True
            # Structured fields are authoritative.  Do not let a free-text
            # note override explicit independent=false or hints_used=true.
            continue
        else:
            entry_date = first_date_from_history_entry(entry)
            if entry_date and entry_date > on_or_before:
                continue

        text = history_text(entry)
        for claim in re.split(r"[\n；。]", text):
            claim = claim.strip()
            if not claim or HINTED_CORRECT_HISTORY_PATTERN.search(claim):
                continue
            if NEGATED_CORRECT_RESULT_PATTERN.search(claim):
                continue
            if INCOMPLETE_WHOLE_QUESTION_PATTERN.search(claim):
                continue
            whole_question = bool(WHOLE_QUESTION_HISTORY_PATTERN.search(claim))
            correct_result = bool(CORRECT_HISTORY_RESULT_PATTERN.search(claim))
            partial_object = bool(PARTIAL_HISTORY_OBJECT_PATTERN.search(claim))
            if STRICT_INDEPENDENT_CORRECT_PATTERN.search(claim) and not partial_object:
                return True
            if (
                whole_question
                and correct_result
                and INDEPENDENT_HISTORY_PATTERN.search(claim)
            ):
                return True
            if (
                EXPLICIT_USER_CORRECT_REPORT_PATTERN.search(claim)
                and USER_REPORTED_CORRECT_RESULT_PATTERN.search(claim)
                and not partial_object
            ):
                return True
    return False


def quick_intake_mastery_confirmed_card_ids(
    cards_by_id: dict[str, tuple[Path, dict[str, Any]]],
    *,
    on_or_before: date,
) -> set[str]:
    """Read committed nightly mastery decisions through the canonical ledger replay.

    A closeout decision is accepted for permanent delivery exclusion only when
    its frozen capture records a correct result, a score of at least 4, no
    hints, and at least one independent correct step.  This bridges the formal
    nightly transaction to the scheduler without manufacturing a SCORE event.
    """

    if not QUICK_INTAKE_EVENTS_PATH.exists():
        return set()
    quick_intake_path = Path(__file__).with_name("quick_intake.py")
    spec = importlib.util.spec_from_file_location(
        "math_quick_intake_for_scheduler",
        quick_intake_path,
    )
    if spec is None or spec.loader is None:
        raise RollbackSyncError("无法加载快速入库账本校验器")
    quick_intake = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(quick_intake)
        state = quick_intake.replay(
            quick_intake.load_jsonl(QUICK_INTAKE_EVENTS_PATH)
        )
    except Exception as exc:
        raise RollbackSyncError("快速入库账本无法通过完整性回放，拒绝选题") from exc

    result: set[str] = set()
    invalidated = state.get("invalidated_closeouts", set())
    for closeout_id, closeout in state.get("closeouts", {}).items():
        if closeout_id in invalidated:
            continue
        supported_closeout_schemas = getattr(
            quick_intake,
            "SUPPORTED_CLOSEOUT_SCHEMAS",
            {quick_intake.CLOSEOUT_SCHEMA},
        )
        if closeout.get("closeout_schema_version") not in supported_closeout_schemas:
            raise RollbackSyncError("正式 closeout 缺少受支持的事务版本")
        study_date = safe_parse_date(closeout.get("study_date"))
        if study_date is None:
            raise RollbackSyncError("正式 mastery closeout 缺少有效学习日期")
        if study_date > on_or_before:
            continue
        freeze = state.get("freezes", {}).get(closeout.get("freeze_id"))
        if not isinstance(freeze, dict) or freeze.get("freeze_schema_version") != quick_intake.FREEZE_SCHEMA:
            raise RollbackSyncError("正式 closeout 未绑定受支持的 freeze")
        if freeze.get("study_date") != closeout.get("study_date"):
            raise RollbackSyncError("正式 closeout 与 freeze 学习日期不一致")

        snapshots = freeze.get("capture_snapshots")
        targets = freeze.get("targets")
        capture_results = closeout.get("capture_results")
        formal_results = closeout.get("formal_results")
        if not all(isinstance(items, list) for items in (snapshots, targets, capture_results, formal_results)):
            raise RollbackSyncError("正式 closeout 缺少冻结快照或结果集合")
        snapshot_by_id = {
            str(item.get("capture_event_id") or ""): item
            for item in snapshots
            if isinstance(item, dict)
        }
        formal_by_id = {
            str(item.get("formal_id") or ""): item
            for item in formal_results
            if isinstance(item, dict)
        }
        if len(snapshot_by_id) != len(snapshots) or len(formal_by_id) != len(formal_results):
            raise RollbackSyncError("正式 closeout 冻结快照或正式结果身份重复")

        for item in capture_results:
            if not isinstance(item, dict) or item.get("outcome") != "mastery_confirmed":
                continue
            formal_id = str(item.get("formal_id") or "").strip()
            capture_id = str(item.get("capture_event_id") or "").strip()
            if state.get("closed_by", {}).get(capture_id) != closeout_id:
                raise RollbackSyncError("mastery closeout 未真实关闭对应 capture")
            capture = state.get("captures", {}).get(capture_id)
            snapshot = snapshot_by_id.get(capture_id)
            formal = formal_by_id.get(formal_id)
            if not all(isinstance(value, dict) for value in (capture, snapshot, formal)):
                raise RollbackSyncError("mastery closeout 缺少 capture、freeze 或正式卡结果")
            if (
                capture.get("study_date") != closeout.get("study_date")
                or capture.get("requested_action") != "mastery_candidate"
                or snapshot.get("requested_action") != "mastery_candidate"
                or snapshot.get("capture_content_hash") != capture.get("content_hash")
            ):
                raise RollbackSyncError("mastery closeout 的日期、动作或 capture 哈希不一致")

            amendments = state.get("amendments", {}).get(capture_id)
            if not isinstance(amendments, list):
                raise RollbackSyncError("mastery capture 缺少 amendment 链")
            if snapshot.get("amendment_event_ids") != [
                amendment.get("event_id") for amendment in amendments
            ]:
                raise RollbackSyncError("mastery freeze 未绑定完整 amendment 链")
            evidence = quick_intake.effective_capture_facts(capture, amendments)
            target = quick_intake.effective_target(capture, amendments)
            if (
                not isinstance(evidence, dict)
                or quick_intake.sha256_value(evidence) != snapshot.get("effective_evidence_hash")
                or quick_intake.sha256_value(target) != snapshot.get("effective_target_hash")
                or target.get("formal_id") != formal_id
            ):
                raise RollbackSyncError("mastery freeze 的有效证据或目标哈希不一致")
            target_groups = [
                target_group
                for target_group in targets
                if isinstance(target_group, dict)
                and capture_id in target_group.get("capture_event_ids", [])
            ]
            if len(target_groups) != 1 or target_groups[0].get("formal_id") != formal_id:
                raise RollbackSyncError("mastery capture 未唯一映射到正式目标")

            durable = item.get("durable_record")
            if (
                not isinstance(durable, dict)
                or durable.get("store") != "formal_card"
                or durable.get("record_id") != formal_id
                or durable.get("record_hash") != formal.get("card_hash_after")
            ):
                raise RollbackSyncError("mastery closeout 未绑定正式卡 durable record")
            if formal_id not in cards_by_id:
                continue
            score = to_int(evidence.get("mastery_score"), -1)
            correct_steps = evidence.get("independent_correct_steps")
            hints_needed = evidence.get("hints_needed")
            user_grounded_correct_step = isinstance(correct_steps, list) and any(
                isinstance(step, dict)
                and step.get("origin") in {"user_observed", "user_confirmed"}
                for step in correct_steps
            )
            if (
                evidence.get("result") == "correct"
                and score >= INDEPENDENT_CORRECT_SCORE_MINIMUM
                and user_grounded_correct_step
                and isinstance(hints_needed, list)
                and not hints_needed
            ):
                result.add(formal_id)
    return result


def module_from_card(card_id: str, subject: str | None) -> str:
    subject = subject or ""
    if "线" in subject or card_id.startswith("LA-"):
        return "线性代数"
    if "概率" in subject or card_id.startswith(("PR-", "GL-", "PL-")):
        return "概率论与数理统计"
    return "高等数学"


def unit_id_from_card(card_id: str, module: str) -> str:
    prefix = {
        "高等数学": "GS",
        "线性代数": "LA",
        "概率论与数理统计": "PR",
    }[module]
    normalized_card_id = card_id.replace("-", "")
    return f"MATH1-{prefix}-WQ-{normalized_card_id}"


def difficulty_from_card(value: Any) -> str:
    mapping = {1: "A简单", 2: "B中等", 3: "C困难", "1": "A简单", "2": "B中等", "3": "C困难"}
    return mapping.get(value, "B中等")


def importance_from_priority(value: Any) -> int:
    return {"A": 5, "B": 4, "C": 3}.get(str(value or "").upper(), 3)


def mastery_from_card(status: str | None, mistakes: int) -> int:
    if status == "已掌握":
        return 4
    if mistakes >= 2:
        return 2
    return 3


def truncate(value: Any, length: int = 180) -> str:
    text = str(value or "待补充").replace("\n", " ").strip()
    return text if len(text) <= length else text[: length - 1] + "…"


def unit_from_card(path: Path) -> dict[str, Any] | None:
    data = parse_card_frontmatter(path)
    if not data:
        return None
    card_id = str(data.get("id") or path.stem.split("_", 1)[0])
    status = str(data.get("status") or "待复做")
    if status == "已掌握":
        return None

    module = module_from_card(card_id, str(data.get("subject") or ""))
    dates = dates_from_card(data)
    review = data.get("review") if isinstance(data.get("review"), dict) else {}
    mistakes = to_int(data.get("mistake_count"), 1)
    title = str(data.get("title") or card_id)
    question_type = str(data.get("question_type") or data.get("chapter") or "错题复做")

    return {
        "复习单元ID": unit_id_from_card(card_id, module),
        "科目": "数学一",
        "模块": module,
        "内容名称": f"{card_id} {title}：{question_type}",
        "类型": "错题",
        "首次学习日期": dates[0] if dates else str(data.get("date") or "2026-05-20"),
        "上次复习日期": None,
        "下次复习日期": str(review.get("next") or data.get("date") or "2026-05-20"),
        "当前间隔天数": to_int(review.get("interval_days"), 1),
        "掌握度": mastery_from_card(status, mistakes),
        "错误次数": mistakes,
        "重要程度": importance_from_priority(data.get("priority")),
        "难度等级": difficulty_from_card(data.get("difficulty")),
        "复习方式": "闭卷重做原题或题目摘要：先判断题型和核心知识点，再独立写关键步骤；对照错点复盘并打 0-5 分。",
        "备注": truncate(data.get("wrong_point")),
        "关联错题ID": card_id,
        "知识点": data.get("knowledge") or ["待补充"],
        "错因类型": data.get("error_causes") or [],
        "最近复发日期": dates[-1] if dates else str(data.get("date") or "2026-05-20"),
    }


def clean_string_list(value: Any) -> list[str]:
    values = value if isinstance(value, list) else ([] if value is None else [value])
    result: list[str] = []
    for item in values:
        text = strip_matching_outer_quotes(item)
        if text and text.lower() not in PLACEHOLDERS:
            result.append(text)
    return result


def validate_card_id(card_id: str) -> None:
    if not CARD_ID_PATTERN.fullmatch(card_id):
        raise RollbackSyncError(f"无效错题 ID：{card_id}")


def find_wrongnet_card(card_id: str) -> Path:
    validate_card_id(card_id)
    matches = sorted(WRONGNET_CARDS_DIR.glob(f"{card_id}_*.md"))
    if not matches:
        raise RollbackSyncError(f"未找到正式错题卡：{card_id}")
    if len(matches) != 1:
        names = "、".join(path.name for path in matches)
        raise RollbackSyncError(f"错题卡身份不唯一：{names}")
    return matches[0]


def normalized_history_text(value: Any) -> str:
    return re.sub(r"\s+", " ", strip_matching_outer_quotes(value))


def parse_rollback_claim(data: dict[str, Any]) -> dict[str, Any] | None:
    raw = data.get("rollback")
    if not isinstance(raw, dict):
        return None
    values = {
        "event_id": str(raw.get("event_id") or "").strip(),
        "event_date": str(raw.get("event_date") or "").strip(),
        "event_type": str(raw.get("event_type") or "").strip(),
        "same_method_gap": raw.get("same_method_gap", False),
        "method_gap_evidence": str(raw.get("method_gap_evidence") or "").strip(),
    }
    if not any(value not in ("", False, None) for value in values.values()):
        return None
    if not values["event_id"] or not re.fullmatch(r"[A-Za-z0-9._:-]+", values["event_id"]):
        raise RollbackSyncError("rollback.event_id 缺失或格式无效")
    validate_iso_date(values["event_date"], "rollback.event_date", nullable=False)
    if values["event_type"] not in {"wrong", "recurrence", "做错", "复发"}:
        raise RollbackSyncError("rollback.event_type 必须明确为 wrong 或 recurrence")
    if not isinstance(values["same_method_gap"], bool):
        raise RollbackSyncError("rollback.same_method_gap 必须是 true 或 false")
    invalid_evidence = PLACEHOLDERS | {">", ">-", "|", "|-"}
    if (
        values["same_method_gap"]
        and values["method_gap_evidence"].lower() in invalid_evidence
    ):
        raise RollbackSyncError("声明同方法断点复发时必须提供 method_gap_evidence")
    return values


def extract_explicit_wrong_events(card_id: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    history = data.get("wrong_history")
    if not isinstance(history, list):
        return []

    events: list[dict[str, Any]] = []
    sequential_number = 0
    for raw_entry in history:
        text = normalized_history_text(raw_entry)
        if not text:
            continue
        strong_failure = STRONG_WRONG_EVENT_PATTERN.search(text) is not None
        if not strong_failure and NEGATED_WRONG_EVENT_PATTERN.search(text):
            continue
        if not strong_failure and PREVENTIVE_WRONG_EVENT_PATTERN.search(text):
            continue
        if not strong_failure and SUCCESS_EVENT_PATTERN.search(text):
            continue
        if not WRONG_EVENT_PATTERN.search(text):
            continue
        date_matches = {
            normalize_date_match(match)
            for match in re.findall(r"(20\d{2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})", text)
        }
        if len(date_matches) != 1:
            # 遗留卡允许保留不可调度的无日期/多日期历史；它不能成为新复发证据。
            continue
        event_date = next(iter(date_matches))
        sequential_number += 1
        number_match = re.search(r"第\s*(\d+)\s*次(?:做错|错)", text)
        if number_match:
            ordinal = int(number_match.group(1))
        elif "首次做错" in text:
            ordinal = 1
        else:
            ordinal = sequential_number
        events.append(
            {
                "id": f"{card_id}|{event_date}|{ordinal}",
                "date": event_date,
                "ordinal": ordinal,
                "text": text,
            }
        )

    claim = parse_rollback_claim(data)
    if claim:
        matching = [event for event in events if event["date"] == claim["event_date"]]
        if not matching:
            raise RollbackSyncError("rollback 事件在 wrong_history 中没有对应做错证据")
        claimed_event = matching[-1]
        claimed_event["declared_event_id"] = claim["event_id"]
        claimed_event["declared"] = True

    event_ids = [event["id"] for event in events]
    if len(event_ids) != len(set(event_ids)):
        raise RollbackSyncError("wrong_history 中存在无法唯一识别的重复做错事件")
    return events


def method_gap_fingerprint(data: dict[str, Any]) -> str | None:
    method_gap = data.get("method_gap")
    if not isinstance(method_gap, dict) or method_gap.get("enabled") is not True:
        return None
    fields = {
        key: normalized_history_text(method_gap.get(key))
        for key in (
            "method_trigger",
            "expected_first_action",
            "missed_action",
            "action_gap_type",
            "related_method_card_id",
        )
    }
    invalid_values = PLACEHOLDERS | {">", ">-", "|", "|-"}
    if not fields["expected_first_action"] or fields["expected_first_action"].lower() in invalid_values:
        return None
    if not fields["missed_action"] or fields["missed_action"].lower() in invalid_values:
        return None
    payload = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def same_method_recurrence_is_verified(
    data: dict[str, Any],
    claim: dict[str, Any] | None,
    previous_fingerprint: str | None,
    current_fingerprint: str | None,
) -> bool:
    if not claim or claim.get("same_method_gap") is not True:
        return False
    method_gap = data.get("method_gap") if isinstance(data.get("method_gap"), dict) else {}
    confidence = str(method_gap.get("confidence") or "").strip().lower()
    if confidence not in {"high", "高"} or method_gap.get("need_user_confirmation") is not False:
        raise RollbackSyncError("同方法断点复发缺少高置信、无需用户确认的结构化证据")
    if not current_fingerprint:
        raise RollbackSyncError("同方法断点复发缺少可验证的方法断点指纹")
    if not previous_fingerprint:
        return False
    if previous_fingerprint != current_fingerprint:
        raise RollbackSyncError("声明同方法断点复发，但前后方法断点指纹不一致")
    return True


def wrongnet_metadata_from_card(card_id: str, data: dict[str, Any]) -> dict[str, Any]:
    module = module_from_card(card_id, str(data.get("subject") or ""))
    title = str(data.get("title") or card_id).strip()
    question_type = str(data.get("question_type") or data.get("chapter") or "错题复做").strip()
    return {
        "模块": module,
        "内容名称": f"{card_id} {title}：{question_type}",
        "知识点": clean_string_list(data.get("knowledge")) or ["待补充"],
        "错因类型": clean_string_list(data.get("error_causes")),
        "难度等级": difficulty_from_card(data.get("difficulty")),
        "重要程度": importance_from_priority(data.get("priority")),
        "源错点": truncate(data.get("wrong_point")),
        "源卡状态": str(data.get("status") or "待复做"),
    }


def source_sync_version(
    card_id: str,
    data: dict[str, Any],
    metadata: dict[str, Any],
    events: list[dict[str, Any]],
    method_fingerprint: str | None,
) -> str:
    payload = {
        "card_id": card_id,
        "metadata": metadata,
        "mistake_count": to_int(data.get("mistake_count"), 0),
        "events": [
            {"id": event["id"], "date": event["date"], "ordinal": event["ordinal"]}
            for event in events
        ],
        "rollback": parse_rollback_claim(data),
        "method_gap_fingerprint": method_fingerprint,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_target_index(
    units: list[dict[str, Any]],
    *,
    card_id: str,
    module: str,
) -> tuple[int | None, str]:
    target_id = unit_id_from_card(card_id, module)
    matches = [index for index, unit in enumerate(units) if unit.get("复习单元ID") == target_id]
    if len(matches) > 1:
        raise RollbackSyncError(f"规范错题单元重复：{target_id}")
    if matches:
        index = matches[0]
        target = units[index]
        if target.get("类型") != "错题" or target.get("关联错题ID") != card_id:
            raise RollbackSyncError(f"规范单元身份与错题卡不一致：{target_id}")
        return index, target_id

    conflicting = [
        unit.get("复习单元ID")
        for unit in units
        if unit.get("关联错题ID") == card_id and unit.get("类型") == "错题"
    ]
    if conflicting:
        raise RollbackSyncError(f"发现非规范错题单元，拒绝另建：{conflicting[0]}")
    return None, target_id


def require_next_day(current_date: date, exam_date: date) -> str:
    if current_date >= exam_date:
        raise RollbackSyncError("考试日当天无法同时满足次日复习与不越过考试日期")
    return (current_date + timedelta(days=1)).isoformat()


def source_state_from_unit(unit: dict[str, Any]) -> dict[str, Any]:
    value = unit.get("定点同步状态")
    return deepcopy(value) if isinstance(value, dict) else {}


def select_new_recurrence_events(
    *,
    unit: dict[str, Any],
    data: dict[str, Any],
    events: list[dict[str, Any]],
    current_date: date,
    expect_recurrence: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    for event in events:
        event_date = parse_date(event["date"])
        if event_date and event_date > current_date:
            raise RollbackSyncError(f"做错事件日期晚于运行日期：{event['date']}")

    state = source_state_from_unit(unit)
    processed = set(state.get("已处理错题事件ID") or [])
    current_ids = {event["id"] for event in events}
    missing = processed - current_ids
    if missing:
        raise RollbackSyncError("源卡删除或改写了已处理做错事件，拒绝丢失历史")

    claim = parse_rollback_claim(data)
    claimed_id = claim["event_id"] if claim else None
    latest_marker = safe_parse_date(unit.get("最近复发日期"))
    new_events: list[dict[str, Any]] = []

    if state:
        previous_source_count = to_int(state.get("源做错次数"), 0)
        source_count = to_int(data.get("mistake_count"), 0)
        if source_count < previous_source_count:
            raise RollbackSyncError("源卡 mistake_count 回退，拒绝删除复发历史")
        unseen = [event for event in events if event["id"] not in processed]
        for event in unseen:
            event_date = parse_date(event["date"])
            if (
                (claimed_id is not None and event.get("declared_event_id") == claimed_id)
                or not latest_marker
                or (event_date and event_date > latest_marker)
            ):
                new_events.append(event)
        source_delta = source_count - previous_source_count
        if source_delta != len(new_events):
            if source_delta > 0 and not new_events:
                raise RollbackSyncError("mistake_count 增加但没有新的明确做错事件")
            if new_events and source_delta <= 0:
                raise RollbackSyncError("新增做错事件但 mistake_count 未同步增加")
            raise RollbackSyncError("mistake_count 增量与新做错事件数量不一致")
    else:
        source_count = to_int(data.get("mistake_count"), 0)
        existing_errors = to_int(unit.get("错误次数"), 0)
        unbacked_current_events = [
            event
            for event in events
            if event["ordinal"] >= 2
            and parse_date(event["date"]) == current_date
            and (
                not latest_marker
                or parse_date(event["date"]) > latest_marker
            )
            and not (
                claimed_id is not None and event.get("declared_event_id") == claimed_id
            )
        ]
        if unbacked_current_events and source_count <= existing_errors:
            raise RollbackSyncError("新增做错事件但 mistake_count 未同步增加")
        for event in events:
            event_date = parse_date(event["date"])
            is_declared = (
                claimed_id is not None and event.get("declared_event_id") == claimed_id
            )
            is_current_later_recurrence = (
                event["ordinal"] >= 2
                and event_date == current_date
                and (not latest_marker or event_date > latest_marker)
                and source_count > existing_errors
            )
            if is_declared or is_current_later_recurrence:
                new_events.append(event)
        if source_count > existing_errors and not new_events:
            dated_events = [parse_date(event["date"]) for event in events]
            marker_covers_history = bool(
                latest_marker
                and dated_events
                and source_count == len(events)
                and all(event_date and event_date <= latest_marker for event_date in dated_events)
            )
            if not marker_covers_history:
                raise RollbackSyncError("源错误次数增加但无法定位新的正式做错事件")

    if expect_recurrence and not new_events:
        raise RollbackSyncError("预期本轮有新复发，但正式错题卡没有可唯一识别的新证据")
    return new_events, [event["id"] for event in events]


def recurrence_history_entry(
    event: dict[str, Any],
    *,
    current_date: date,
    source_version: str,
    before: dict[str, Any] | None,
    same_method_gap: bool,
) -> dict[str, Any]:
    snapshot_fields = (
        "上次复习日期",
        "下次复习日期",
        "当前间隔天数",
        "掌握度",
        "调度优先级",
        "复习状态",
        "延迟复习阶段",
        "连续延迟成功次数",
    )
    entry = {
        "类型": "正式错题复发",
        "事件ID": event["id"],
        "复发日期": event["date"],
        "同步日期": current_date.isoformat(),
        "证据": truncate(event["text"], 240),
        "同方法断点复发": same_method_gap,
        "源版本": source_version,
        "复发前": {field: before.get(field) for field in snapshot_fields} if before else None,
    }
    if event.get("declared_event_id"):
        entry["声明事件ID"] = event["declared_event_id"]
    return entry


def build_new_target_unit(
    *,
    card_id: str,
    data: dict[str, Any],
    metadata: dict[str, Any],
    events: list[dict[str, Any]],
    current_date: date,
    exam_date: date,
    source_version: str,
    method_fingerprint: str | None,
) -> dict[str, Any]:
    if not events:
        raise RollbackSyncError("创建回滚单元需要至少一条明确的正式做错事件")
    if any(parse_date(event["date"]) > current_date for event in events):
        raise RollbackSyncError("做错事件日期不得晚于运行日期")
    source_count = to_int(data.get("mistake_count"), 0)
    if source_count <= 0:
        raise RollbackSyncError("创建回滚单元需要有效的 mistake_count")
    if source_count != len(events):
        raise RollbackSyncError("创建单元时 mistake_count 与明确做错事件数量不一致")
    if source_count < max(event["ordinal"] for event in events):
        raise RollbackSyncError("新增做错事件但 mistake_count 未同步增加")
    mistakes = max(source_count, len(events), 1)
    mastery = mastery_from_card(str(data.get("status") or "待复做"), mistakes)
    recurrence_count = max(0, len(events) - 1)
    high_priority = mistakes >= 2 or metadata["重要程度"] >= 5 or mastery <= 2
    unit = {
        "复习单元ID": unit_id_from_card(card_id, metadata["模块"]),
        "科目": "数学一",
        "模块": metadata["模块"],
        "内容名称": metadata["内容名称"],
        "类型": "错题",
        "首次学习日期": events[0]["date"],
        "上次复习日期": None,
        "下次复习日期": require_next_day(current_date, exam_date),
        "当前间隔天数": 1,
        "掌握度": mastery,
        "错误次数": mistakes,
        "重要程度": metadata["重要程度"],
        "难度等级": metadata["难度等级"],
        "复习方式": "第二天独立闭卷重做：先辨认题型与方法入口，再完成关键步骤；当天即时纠错不计长期成功。",
        "备注": metadata["源错点"],
        "关联错题ID": card_id,
        "知识点": metadata["知识点"],
        "错因类型": metadata["错因类型"],
        "源错点": metadata["源错点"],
        "源卡状态": metadata["源卡状态"],
        "最近复发日期": events[-1]["date"],
        "调度策略版本": "wrongnet-targeted-v1",
        "调度优先级": "高" if high_priority else "普通",
        "复习状态": "复发待延迟复做" if recurrence_count else "待首次延迟复做",
        "延迟复习阶段": 0,
        "连续延迟成功次数": 0,
        "复发次数": recurrence_count,
        "同方法断点复发次数": 0,
        "调度事件历史": [
            recurrence_history_entry(
                event,
                current_date=current_date,
                source_version=source_version,
                before=None,
                same_method_gap=False,
            )
            for event in events[1:]
        ],
        "定点同步状态": {
            "源版本": source_version,
            "源做错次数": source_count,
            "已处理错题事件ID": [event["id"] for event in events],
            "当前方法断点指纹": method_fingerprint,
        },
    }
    return unit


def plan_wrongnet_upsert(
    *,
    card_id: str,
    data: dict[str, Any],
    units: list[dict[str, Any]],
    current_date: date,
    expect_recurrence: bool,
) -> tuple[str, dict[str, Any] | None, dict[str, Any], int | None, date | None]:
    parsed_id = str(data.get("id") or "").strip()
    if parsed_id != card_id:
        raise RollbackSyncError(f"文件名与 frontmatter ID 不一致：{card_id} / {parsed_id or '缺失'}")
    events = extract_explicit_wrong_events(card_id, data)
    metadata = wrongnet_metadata_from_card(card_id, data)
    method_fingerprint = method_gap_fingerprint(data)
    source_version = source_sync_version(card_id, data, metadata, events, method_fingerprint)
    index, target_id = canonical_target_index(units, card_id=card_id, module=metadata["模块"])

    if index is None:
        if expect_recurrence and len(events) < 2:
            raise RollbackSyncError("预期本轮有复发，但新单元只有首次做错证据")
        exam_date = load_exam_date(required=True)
        assert exam_date is not None
        after = build_new_target_unit(
            card_id=card_id,
            data=data,
            metadata=metadata,
            events=events,
            current_date=current_date,
            exam_date=exam_date,
            source_version=source_version,
            method_fingerprint=method_fingerprint,
        )
        return "create", None, after, None, exam_date

    # 已有目标先严格校验，不能靠后续补丁把坏历史静默“修好”或覆盖。
    validate_units_document(units, target_unit_id=target_id)
    before = deepcopy(units[index])
    old_state = source_state_from_unit(before)
    configured_exam_date = load_exam_date(required=False)
    existing_next = safe_parse_date(before.get("下次复习日期"))
    if old_state.get("源版本") == source_version:
        if configured_exam_date and existing_next and existing_next > configured_exam_date:
            raise RollbackSyncError(
                "现有下次复习日期晚于 exam_date；同源同步不得擅自改写调度"
            )
        return "noop", before, deepcopy(before), index, configured_exam_date

    new_events, all_event_ids = select_new_recurrence_events(
        unit=before,
        data=data,
        events=events,
        current_date=current_date,
        expect_recurrence=expect_recurrence,
    )
    if new_events and to_int(data.get("mistake_count"), 0) < max(
        event["ordinal"] for event in new_events
    ):
        raise RollbackSyncError("新增做错事件但 mistake_count 未同步增加")
    if (
        not new_events
        and configured_exam_date
        and existing_next
        and existing_next > configured_exam_date
    ):
        raise RollbackSyncError(
            "现有下次复习日期晚于 exam_date；普通元数据同步不得擅自改写调度"
        )
    after = deepcopy(before)
    for field in WRONGNET_METADATA_FIELDS:
        after[field] = deepcopy(metadata[field])

    claim = parse_rollback_claim(data)
    previous_fingerprint = old_state.get("当前方法断点指纹")
    if new_events and claim:
        latest_new_event = new_events[-1]
        if latest_new_event.get("declared_event_id") != claim["event_id"]:
            raise RollbackSyncError("rollback 声明未指向本轮最新新复发事件")
    same_method_gap = same_method_recurrence_is_verified(
        data,
        claim,
        previous_fingerprint if isinstance(previous_fingerprint, str) else None,
        method_fingerprint,
    )
    after["定点同步状态"] = {
        "源版本": source_version,
        "源做错次数": to_int(data.get("mistake_count"), 0),
        "已处理错题事件ID": all_event_ids,
        "当前方法断点指纹": method_fingerprint,
    }

    exam_date: date | None = configured_exam_date
    if new_events:
        exam_date = load_exam_date(required=True)
        assert exam_date is not None
        baseline_event_count = max(0, len(events) - len(new_events))
        default_recurrences = max(0, baseline_event_count - 1)
        after["调度策略版本"] = "wrongnet-targeted-v1"
        after["调度优先级"] = "高"
        after["复习状态"] = "复发待延迟复做"
        after["延迟复习阶段"] = 0
        after["连续延迟成功次数"] = 0
        after["复发次数"] = to_int(before.get("复发次数"), default_recurrences) + len(new_events)
        # score 失败可能已记录同一次做错；与源计数取最大值可避免再次叠加。
        after["错误次数"] = max(
            to_int(before.get("错误次数"), 0),
            to_int(data.get("mistake_count"), 0),
        )
        after["当前间隔天数"] = 1
        after["下次复习日期"] = require_next_day(current_date, exam_date)
        after["最近复发日期"] = max(event["date"] for event in new_events)
        after["已掌握"] = False
        after["掌握状态"] = "复发待复做"
        history = deepcopy(before.get("调度事件历史")) if isinstance(before.get("调度事件历史"), list) else []
        for event in new_events:
            history.append(
                recurrence_history_entry(
                    event,
                    current_date=current_date,
                    source_version=source_version,
                    before=before,
                    same_method_gap=same_method_gap and event is new_events[-1],
                )
            )
        after["调度事件历史"] = history
        after["同方法断点复发次数"] = to_int(before.get("同方法断点复发次数"), 0)
        if same_method_gap:
            after["同方法断点复发次数"] += 1

    action = "update-recurrence" if new_events else "update-metadata"
    if after.get("复习单元ID") != target_id:
        raise RollbackSyncError("定点计划意外改变了目标身份")
    return action, before, after, index, exam_date


def top_level_diff(
    before: dict[str, Any] | None,
    after: dict[str, Any],
) -> list[dict[str, Any]]:
    before_map = before or {}
    changes: list[dict[str, Any]] = []
    for field in sorted(set(before_map) | set(after)):
        before_exists = field in before_map
        after_exists = field in after
        if before_exists == after_exists and before_map.get(field) == after.get(field):
            continue
        changes.append(
            {
                "field": field,
                "before": {"exists": before_exists, "value": before_map.get(field)},
                "after": {"exists": after_exists, "value": after.get(field)},
            }
        )
    return changes


def default_progress_config() -> dict[str, Any]:
    return {
        "exam_date": None,
        "default_count": 5,
        "active_gap_days": 7,
        "exclude_recent_days": 7,
        "stage_windows": {
            "unstable": [1, 2],
            "first_independent_correct": [5, 10],
            "second_independent_correct": [18, 35],
            "third_independent_correct": [40, 75],
            "long_term_maintenance": [75, 120],
        },
        "same_item_repair_window": [1, 2],
        "progress_note": "当前错题库内容均视为已学范围；后续学习进度变化时再更新本文件。",
        "date_missing_policy": "日期缺失题视为已学历史整合题，可按知识点参与回滚；不保证每一道都曾亲自做过。",
        "modules": {
            module: {
                "enabled": True,
                "knowledge_allowlist": [],
                "knowledge_denylist": [],
            }
            for module in MODULES
        },
    }


def load_progress_config() -> dict[str, Any]:
    config = default_progress_config()
    if not PROGRESS_PATH.exists():
        return config

    raw = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    for key in (
        "exam_date",
        "default_count",
        "active_gap_days",
        "exclude_recent_days",
        "stage_windows",
        "same_item_repair_window",
        "progress_note",
        "date_missing_policy",
    ):
        if key in raw:
            config[key] = raw[key]

    raw_modules = raw.get("modules", {})
    if isinstance(raw_modules, dict):
        for module in MODULES:
            module_config = raw_modules.get(module, {})
            if not isinstance(module_config, dict):
                continue
            config["modules"][module].update(module_config)
    return config


def load_exam_date(*, required: bool) -> date | None:
    value = load_progress_config().get("exam_date")
    if value in (None, ""):
        if required:
            raise RollbackSyncError(
                "请先在 数学一回滚复习系统/学习进度.json 配置 exam_date"
            )
        return None
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        raise RollbackSyncError("exam_date 必须是 YYYY-MM-DD 或 null")
    try:
        return parse_date(value)
    except ValueError as exc:
        raise RollbackSyncError(f"exam_date 不是有效日期：{value}") from exc


def as_clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = [value]

    items: list[str] = []
    for item in raw_items:
        text = str(item).strip()
        if text.lower() not in PLACEHOLDERS:
            items.append(text)
    return items


def primary_knowledge(knowledge: list[str]) -> str:
    for item in knowledge:
        if item not in BROAD_KNOWLEDGE:
            return item
    return knowledge[0] if knowledge else "待补充"


def module_is_enabled(config: dict[str, Any], module: str) -> bool:
    module_config = config.get("modules", {}).get(module, {})
    return bool(module_config.get("enabled", True))


def module_allows_knowledge(config: dict[str, Any], module: str, knowledge: list[str]) -> bool:
    module_config = config.get("modules", {}).get(module, {})
    allowlist = as_clean_list(module_config.get("knowledge_allowlist"))
    denylist = as_clean_list(module_config.get("knowledge_denylist"))
    if denylist and set(knowledge) & set(denylist):
        return False
    if not allowlist:
        return True
    return bool(set(knowledge) & set(allowlist))


def load_warmup_logs() -> list[dict[str, Any]]:
    if not WARMUP_LOG_PATH.exists():
        return []

    logs: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        WARMUP_LOG_PATH.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RollbackSyncError(f"学习前队列日志第 {line_number} 行不是有效 JSON") from exc
        if not isinstance(item, dict):
            raise RollbackSyncError(f"学习前队列日志第 {line_number} 行必须是对象")
        logs.append(item)
    return logs


def last_warmup_selection_by_card(before_date: date | None = None) -> dict[str, date]:
    result: dict[str, date] = {}
    for log in load_warmup_logs():
        log_date = safe_parse_date(log.get("date"))
        if not log_date:
            continue
        if before_date and log_date >= before_date:
            # 本日队列不能反过来改变同一输入的重跑结果。
            continue
        selected = log.get("selected", [])
        if not isinstance(selected, list):
            continue
        for item in selected:
            if isinstance(item, dict):
                card_id = str(item.get("id") or "").strip()
            else:
                card_id = str(item).strip()
            if not card_id:
                continue
            if card_id not in result or log_date > result[card_id]:
                result[card_id] = log_date
    return result


def last_scored_delivery_by_card(
    units: list[dict[str, Any]],
    before_date: date | None = None,
) -> dict[str, date]:
    """Return activity for the card actually answered, not its score target.

    A proxy warmup answer updates the anchor unit's schedule.  That scheduling
    write must not make the anchor's original card look recently delivered.
    """

    card_by_unit_id = {
        str(unit.get("复习单元ID") or "").strip(): str(
            unit.get("关联错题ID") or ""
        ).strip()
        for unit in units
        if str(unit.get("复习单元ID") or "").strip()
    }
    result: dict[str, date] = {}
    for event in load_review_logs():
        event_date = safe_parse_date(event.get("date"))
        if not event_date or (before_date and event_date >= before_date):
            continue
        delivered_card_id = str(event.get("delivered_card_id") or "").strip()
        if not delivered_card_id:
            delivered_card_id = card_by_unit_id.get(
                str(event.get("unit_id") or "").strip(),
                "",
            )
        if not CARD_ID_PATTERN.fullmatch(delivered_card_id):
            continue
        if (
            delivered_card_id not in result
            or event_date > result[delivered_card_id]
        ):
            result[delivered_card_id] = event_date
    return result


def date_values_from_card_and_unit(data: dict[str, Any], unit: dict[str, Any] | None) -> list[date]:
    date_values = [safe_parse_date(value) for value in dates_from_card(data)]
    if unit:
        for field in ("首次学习日期", "上次复习日期", "最近复发日期"):
            date_values.append(safe_parse_date(unit.get(field)))
    return sorted({value for value in date_values if value})


def date_list_text(
    dates: list[date],
    attempts: int,
    *,
    fallback_dates: list[date] | None = None,
    actual_history_missing: bool = False,
) -> str:
    if dates and not actual_history_missing:
        all_dates = "、".join(value.isoformat() for value in dates)
        if attempts > len(dates):
            missing_count = attempts - len(dates)
            return (
                f"最近 {dates[-1].isoformat()}（已做 {attempts} 遍；"
                f"已记录日期：{all_dates}；另 {missing_count} 次记录无明确日期）"
            )
        return f"最近 {dates[-1].isoformat()}（已做 {attempts} 遍：{all_dates}）"
    if actual_history_missing:
        fallback_dates = fallback_dates or []
        if fallback_dates:
            fallback_text = "、".join(value.isoformat() for value in fallback_dates)
            return (
                f"历史日期未确认（系统记录/录入日期：{fallback_text}；"
                f"历史整合题；记录次数 {attempts}；不保证是亲自做过）"
            )
        return f"历史日期未确认（历史整合题；记录次数 {attempts}；不保证是亲自做过）"
    if attempts > 0:
        return f"日期未确认（历史整合题；记录次数 {attempts}；不保证是亲自做过）"
    return "日期未确认（历史整合题；次数未记录；不保证是亲自做过）"


def warmup_age_days(current_date: date, value: date | None, fallback: int = 9999) -> int:
    if not value:
        return fallback
    return max(0, (current_date - value).days)


def unit_by_card_id(units: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for unit in units:
        card_id = str(unit.get("关联错题ID") or "").strip()
        if not card_id or unit.get("类型") != "错题":
            continue
        module = str(unit.get("模块") or module_from_card(card_id, ""))
        if unit.get("复习单元ID") != unit_id_from_card(card_id, module):
            continue
        if card_id in result:
            raise RollbackSyncError(f"规范错题单元重复：{card_id}")
        result[card_id] = unit
    return result


def unit_schedule_source_version(unit: dict[str, Any]) -> str:
    fields = {
        key: unit.get(key)
        for key in (
            "复习单元ID",
            "关联错题ID",
            "类型",
            "模块",
            "知识点",
            "首次学习日期",
            "下次复习日期",
            "上次复习日期",
            "当前间隔天数",
            "掌握度",
            "错误次数",
            "重要程度",
            "难度等级",
            "调度优先级",
            "复发次数",
            "最近复发日期",
            "调度策略版本",
        )
    }
    payload = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_warmup_candidates(
    current_date: date,
    config: dict[str, Any],
    units: list[dict[str, Any]],
    exam_date: date | None = None,
) -> list[dict[str, Any]]:
    # Keep review-selection semantics out of the single-card upsert startup
    # path; this module is only needed when warmup candidates are built.
    import training_evidence

    units_by_card = unit_by_card_id(units)
    last_selected_by_card = last_warmup_selection_by_card(before_date=current_date)
    last_scored_by_card = last_scored_delivery_by_card(
        units,
        before_date=current_date,
    )
    candidates: list[dict[str, Any]] = []
    cards_by_id: dict[str, tuple[Path, dict[str, Any]]] = {}

    for path in sorted(WRONGNET_CARDS_DIR.glob("*.md")):
        data = parse_card_frontmatter(path)
        if not data:
            continue
        card_id = str(data.get("id") or path.stem.split("_", 1)[0]).strip()
        if not CARD_ID_PATTERN.fullmatch(card_id):
            continue
        if card_id in cards_by_id:
            raise RollbackSyncError(f"正式错题 ID 存在多张卡：{card_id}")
        cards_by_id[card_id] = (path, data)

    independent_correct_sources_by_id = independent_correct_sources_by_card(
        units,
        cards_by_id,
        on_or_before=current_date,
    )

    # The delivery pool is the formal card library, not merely the subset that
    # already has a long-term review unit.  A unit is required for an anchor or
    # a directly due card, but an already-ingested formal card can safely serve
    # as the delivered proxy because score-warmup only mutates the anchor unit.
    for card_id, card in sorted(cards_by_id.items()):
        path, data = card
        unit = units_by_card.get(card_id)
        unit_data = unit or {}
        status = str(data.get("status") or "待复做").strip()
        independent_correct_sources = list(
            independent_correct_sources_by_id.get(card_id, [])
        )
        module = module_from_card(card_id, str(data.get("subject") or ""))
        if not module_is_enabled(config, module):
            continue

        knowledge = as_clean_list(data.get("knowledge")) or as_clean_list(
            unit_data.get("知识点")
        )
        if not module_allows_knowledge(config, module, knowledge):
            continue

        due_text = unit_data.get("下次复习日期")
        due_date = safe_parse_date(due_text)
        if due_text not in (None, "") and due_date is None:
            raise RollbackSyncError(
                f"{unit_data.get('复习单元ID')} 的下次复习日期无效"
            )
        if exam_date and due_date and due_date > exam_date:
            raise RollbackSyncError(
                f"{unit_data.get('复习单元ID')} 的下次复习日期晚于考试日期"
            )

        fallback_dates = date_values_from_card_and_unit(data, unit)
        history_dates = [safe_parse_date(value) for value in history_dates_from_card(data)]
        history_dates = sorted({value for value in history_dates if value})
        actual_history_missing = not history_dates
        dates = history_dates if history_dates else fallback_dates
        card_mistakes = to_int(data.get("mistake_count"), 1)
        unit_mistakes = to_int(unit_data.get("错误次数"), card_mistakes)
        attempts = max(card_mistakes, unit_mistakes, len(dates))
        mastery = to_int(
            unit_data.get("掌握度"),
            mastery_from_card(status, max(card_mistakes, unit_mistakes)),
        )
        last_selected_date = last_selected_by_card.get(card_id)
        last_scored_date = last_scored_by_card.get(card_id)
        intrinsic_unit_dates = [
            safe_parse_date(unit_data.get("首次学习日期")),
            safe_parse_date(unit_data.get("最近复发日期")),
        ]
        card_activity_dates = [safe_parse_date(value) for value in dates_from_card(data)]
        activity_dates = sorted(
            {
                value
                for value in [
                    *card_activity_dates,
                    *intrinsic_unit_dates,
                    last_selected_date,
                    last_scored_date,
                ]
                if isinstance(value, date)
            }
        )
        # Delivery de-duplication follows the formal card that was actually
        # selected or answered.  The anchor unit's 上次复习日期 is a scheduling
        # fact and may come from a different proxy card, so it is excluded here.
        last_activity_date = activity_dates[-1] if activity_dates else None
        evidence = training_evidence.extract_error_evidence(data, card_id)
        card_source_version = hashlib.sha256(path.read_bytes()).hexdigest()
        sync_state = (
            unit_data.get("定点同步状态")
            if isinstance(unit_data.get("定点同步状态"), dict)
            else {}
        )
        processed_event_ids = sync_state.get("已处理错题事件ID", [])
        if not isinstance(processed_event_ids, list):
            processed_event_ids = []
        latest_wrong_event_id = (
            str(processed_event_ids[-1]).strip()
            if processed_event_ids and str(processed_event_ids[-1]).strip()
            else f"{card_id}:{unit_data.get('最近复发日期') or unit_data.get('首次学习日期') or 'undated'}"
        )

        candidates.append(
            {
                "id": card_id,
                "unit_id": unit_data.get("复习单元ID"),
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "module": module,
                "title": str(data.get("title") or card_id),
                "source": str(data.get("source") or "未记录"),
                "status": status,
                "independently_correct": bool(independent_correct_sources),
                "independent_correct_sources": independent_correct_sources,
                "knowledge": knowledge,
                "primary_knowledge": primary_knowledge(knowledge),
                "evidence": evidence,
                "evidence_source_version": evidence.get("source_version"),
                "card_source_version": card_source_version,
                "unit_source_version": (
                    unit_schedule_source_version(unit_data) if unit is not None else None
                ),
                "dates": dates,
                "fallback_dates": fallback_dates,
                "actual_history_missing": actual_history_missing,
                "attempts": attempts,
                "last_activity_date": last_activity_date,
                "last_selected_date": last_selected_date,
                "last_scored_delivery_date": last_scored_date,
                "mastery": mastery,
                "mistakes": max(card_mistakes, unit_mistakes),
                "importance": to_int(
                    unit_data.get("重要程度"),
                    importance_from_priority(data.get("priority")),
                ),
                "difficulty": unit_data.get("难度等级")
                or difficulty_from_card(data.get("difficulty")),
                "priority": str(data.get("priority") or "C"),
                "due_date": due_date,
                "is_due": bool(due_date and due_date <= current_date),
                "overdue_days": overdue_days(unit_data, current_date) if unit else 0,
                "dynamic_priority": priority_score(unit_data, current_date) if unit else 0,
                "recurrence_count": to_int(unit_data.get("复发次数")),
                "scheduling_priority": str(unit_data.get("调度优先级") or "普通"),
                "targeted_schedule": unit_data.get("调度策略版本")
                == "wrongnet-targeted-v1",
                "review_state": str(unit_data.get("复习状态") or ""),
                "recent_failure_date": safe_parse_date(
                    unit_data.get("最近复发日期")
                    or unit_data.get("首次学习日期")
                ),
                "latest_wrong_event_id": latest_wrong_event_id,
            }
        )
    return candidates


def warmup_due_sort_key(candidate: dict[str, Any]) -> tuple[int, int, int, int, int, int, str]:
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    return (
        -to_int(candidate.get("dynamic_priority")),
        -to_int(candidate.get("recurrence_count")),
        to_int(candidate.get("mastery"), 3),
        -to_int(candidate.get("mistakes")),
        -to_int(candidate.get("overdue_days")),
        -to_int(evidence.get("selection_value")),
        str(candidate.get("id") or ""),
    )


def warmup_supplemental_sort_key(
    candidate: dict[str, Any], current_date: date
) -> tuple[int, int, int, int, int, str]:
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    due_date = candidate.get("due_date")
    days_until_due = (due_date - current_date).days if isinstance(due_date, date) else 9999
    return (
        -to_int(evidence.get("selection_value")),
        -to_int(candidate.get("recurrence_count")),
        to_int(candidate.get("mastery"), 3),
        -to_int(candidate.get("mistakes")),
        days_until_due,
        str(candidate.get("id") or ""),
    )


def within_recent_window(current_date: date, event_date: date | None, days: int) -> bool:
    if not isinstance(event_date, date) or days <= 0:
        return False
    age = (current_date - event_date).days
    return 0 <= age <= days


def delivery_card_is_old_enough(
    candidate: dict[str, Any], current_date: date, exclude_recent_days: int
) -> bool:
    last_activity = candidate.get("last_activity_date")
    if not isinstance(last_activity, date):
        return True
    return (current_date - last_activity).days > exclude_recent_days


def gap_occurrence_id(anchor: dict[str, Any]) -> str:
    payload = {
        "anchor_id": anchor.get("id"),
        "wrong_event_id": anchor.get("latest_wrong_event_id"),
        "failure_date": format_date(anchor.get("recent_failure_date")),
        "gap_key": (anchor.get("evidence") or {}).get("gap_key"),
        "evidence_source_version": anchor.get("evidence_source_version"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"GAPO-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:24]}"


def validated_event_evidence_snapshot(event: dict[str, Any]) -> dict[str, Any] | None:
    import training_evidence

    snapshot = event.get("delivered_evidence_snapshot")
    expected_version = str(event.get("delivered_evidence_source_version") or "").strip()
    if not isinstance(snapshot, dict) or not re.fullmatch(r"[0-9a-f]{64}", expected_version):
        return None
    if snapshot.get("source_version") != expected_version:
        return None
    normalized = training_evidence.normalized_evidence_snapshot(
        snapshot,
        str(event.get("delivered_card_id") or "").strip(),
    )
    if normalized is None or normalized.get("source_version") != expected_version:
        return None
    return normalized


def score_marker_events(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for unit in units:
        markers = unit.get("评分事件历史")
        if not isinstance(markers, list):
            continue
        events.extend(deepcopy(item) for item in markers if isinstance(item, dict))
    return events


def merged_score_evidence_events(
    logs: list[dict[str, Any]],
    markers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for event in [*logs, *markers]:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            anonymous.append(event)
            continue
        existing = by_id.get(event_id)
        if existing is not None and existing != event:
            raise RollbackSyncError(f"评分日志与单元幂等标记冲突：{event_id}")
        by_id[event_id] = event
    return [*by_id.values(), *anonymous]


def independently_correct_scored_card_ids(
    units: list[dict[str, Any]],
    cards_by_id: dict[str, tuple[Path, dict[str, Any]]],
    *,
    on_or_before: date,
) -> set[str]:
    """Resolve formal 4-5 scores to the card that was actually answered.

    A score of 3 may be assigned after hints, so it cannot trigger permanent
    exclusion.  Proxy answers belong to delivered_card_id, never to the anchor
    unit.  Unit markers are merged with JSONL so a crash after the atomic unit
    write cannot make an independently correct card eligible again.
    """

    card_id_by_unit_id: dict[str, str] = {}
    for unit in units:
        unit_id = str(unit.get("复习单元ID") or "").strip()
        card_id = str(unit.get("关联错题ID") or "").strip()
        if not unit_id or not CARD_ID_PATTERN.fullmatch(card_id):
            continue
        existing = card_id_by_unit_id.get(unit_id)
        if existing is not None and existing != card_id:
            raise RollbackSyncError(f"复习单元到错题卡的映射不唯一：{unit_id}")
        card_id_by_unit_id[unit_id] = card_id

    # Old mastered units may already have been removed from the live unit file.
    # Recover only the deterministic WQ unit identity of an existing formal card;
    # method/template scores must never fan out to several question cards.
    for card_id, (_, data) in cards_by_id.items():
        expected_unit_id = unit_id_from_card(
            card_id,
            module_from_card(card_id, str(data.get("subject") or "")),
        )
        card_id_by_unit_id.setdefault(expected_unit_id, card_id)

    events = merged_score_evidence_events(
        load_review_logs(),
        score_marker_events(units),
    )
    result: set[str] = set()
    for event in events:
        outcome = event.get("review_outcome")
        explicit_independent = False
        if isinstance(outcome, dict):
            import math_learning_state
            if event.get("review_outcome_sha256") != math_learning_state.digest(outcome):
                raise RollbackSyncError("正式复盘作答证据哈希不一致，拒绝推断独立掌握")
            explicit_independent = (
                outcome.get("independent_correct") is True
                and outcome.get("hint_dependency") == "none"
                and outcome.get("evidence_origin") in {"user_observed", "user_confirmed"}
                and outcome.get("formal_id") == event.get("delivered_card_id")
                and bool(str(outcome.get("user_answer_text") or "").strip())
            )
        if to_int(event.get("score"), -1) < INDEPENDENT_CORRECT_SCORE_MINIMUM and not explicit_independent:
            continue
        event_date = safe_parse_date(event.get("date"))
        if event_date is None:
            raise RollbackSyncError("独立做对评分缺少有效日期，拒绝继续选题")
        if event_date > on_or_before:
            continue

        delivered_card_id = str(event.get("delivered_card_id") or "").strip()
        if delivered_card_id:
            if not CARD_ID_PATTERN.fullmatch(delivered_card_id):
                raise RollbackSyncError(
                    f"独立做对评分的 delivered_card_id 无效：{delivered_card_id}"
                )
        else:
            delivered_card_id = card_id_by_unit_id.get(
                str(event.get("unit_id") or "").strip(),
                "",
            )
            if not delivered_card_id:
                # A score for a method/template unit is not evidence that any
                # particular question card was independently answered.
                continue

        if delivered_card_id in cards_by_id:
            result.add(delivered_card_id)
    return result


def independent_correct_sources_by_card(
    units: list[dict[str, Any]],
    cards_by_id: dict[str, tuple[Path, dict[str, Any]]],
    *,
    on_or_before: date,
) -> dict[str, list[str]]:
    scored_ids = independently_correct_scored_card_ids(
        units,
        cards_by_id,
        on_or_before=on_or_before,
    )
    closeout_ids = quick_intake_mastery_confirmed_card_ids(
        cards_by_id,
        on_or_before=on_or_before,
    )
    result: dict[str, list[str]] = {}
    for card_id, (_, data) in cards_by_id.items():
        sources: list[str] = []
        if card_id in scored_ids:
            sources.append("formal_score_4_to_5")
        if formal_mastery_history_records_correct(data, on_or_before=on_or_before):
            sources.append("formal_mastery_history")
        if card_id in closeout_ids:
            sources.append("formal_closeout_mastery_confirmed")
        if sources:
            result[card_id] = sources
    return result


def load_permanent_delivery_exclusion_ids(on_or_before: date) -> set[str]:
    """Public read-only boundary shared by every old-question recommender."""

    units = load_units()
    cards_by_id: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted(WRONGNET_CARDS_DIR.glob("*.md")):
        data = parse_card_frontmatter(path)
        if not data:
            continue
        card_id = str(data.get("id") or path.stem.split("_", 1)[0]).strip()
        if not CARD_ID_PATTERN.fullmatch(card_id):
            continue
        if card_id in cards_by_id:
            raise RollbackSyncError(f"正式错题 ID 存在多张卡：{card_id}")
        cards_by_id[card_id] = (path, data)
    return set(
        independent_correct_sources_by_card(
            units,
            cards_by_id,
            on_or_before=on_or_before,
        )
    )


def active_gap_resolution_event(
    anchor: dict[str, Any],
    candidates_by_id: dict[str, dict[str, Any]],
    card_id_by_unit_id: dict[str, str],
    current_date: date,
    marker_events: list[dict[str, Any]] | None = None,
    *,
    respect_schedule_origin: bool = True,
) -> dict[str, Any] | None:
    import training_evidence

    failure_date = anchor.get("recent_failure_date")
    if not isinstance(failure_date, date):
        return None
    occurrence_id = gap_occurrence_id(anchor)
    anchor_evidence = anchor.get("evidence") if isinstance(anchor.get("evidence"), dict) else {}
    logs = merged_score_evidence_events(
        load_review_logs(),
        marker_events or [],
    )

    resolution_after = failure_date
    if respect_schedule_origin:
        # A prior score on this same anchor may be the event that created the
        # currently due 1/3/7-day schedule.  It resolves the recent-gap view,
        # but must not cancel the future schedule it created.
        due_text = format_date(anchor.get("due_date"))
        for event in logs:
            event_date = safe_parse_date(event.get("date"))
            new_state = event.get("new") if isinstance(event.get("new"), dict) else {}
            if (
                event_date
                and event_date <= current_date
                and event.get("unit_id") == anchor.get("unit_id")
                and event.get("attempt_type") in {None, "delayed"}
                and new_state.get("下次复习日期") == due_text
                and event_date > resolution_after
            ):
                resolution_after = event_date

    for event in logs:
        event_date = safe_parse_date(event.get("date"))
        # Same-day records have no trustworthy ordering, so they cannot close
        # a failure occurrence from that day.
        if not event_date or event_date <= resolution_after or event_date > current_date:
            continue
        if to_int(event.get("score"), -1) < 4:
            continue
        if (
            event.get("coverage_resolves_active_gap") is True
            and event.get("anchor_gap_occurrence_id") == occurrence_id
        ):
            return event
        if (
            event.get("unit_id") == anchor.get("unit_id")
            and event.get("attempt_type") in {None, "delayed"}
        ):
            return event

        # Cross-card coverage is interpreted from the immutable evidence
        # snapshot captured when the answer was scored.  Current card metadata
        # must never retroactively change the meaning of a historical event.
        delivered_evidence = validated_event_evidence_snapshot(event)
        if delivered_evidence is None:
            continue
        exact_score, _ = training_evidence.exact_evidence_match(
            anchor_evidence,
            delivered_evidence,
        )
        if exact_score > 0:
            return event
        if training_evidence.shared_knowledge(anchor_evidence, delivered_evidence):
            return event
    return None


def attach_warmup_anchor(
    delivered: dict[str, Any],
    anchor: dict[str, Any],
    *,
    selection_mode: str,
    match_mode: str,
    match_reasons: list[str],
    matched_knowledge: list[str] | None = None,
) -> dict[str, Any]:
    item = deepcopy(delivered)
    item["delivered_unit_id"] = delivered.get("unit_id")
    item["delivered_due_date"] = delivered.get("due_date")
    item["delivered_unit_source_version"] = delivered.get("unit_source_version")
    item["anchor_id"] = anchor.get("id")
    item["anchor_unit_id"] = anchor.get("unit_id")
    item["anchor_due_date"] = anchor.get("due_date")
    item["anchor_card_source_version"] = anchor.get("card_source_version")
    item["anchor_unit_source_version"] = anchor.get("unit_source_version")
    item["anchor_evidence_source_version"] = anchor.get("evidence_source_version")
    item["anchor_evidence"] = deepcopy(anchor.get("evidence") or {})
    item["anchor_wrong_event_id"] = anchor.get("latest_wrong_event_id")
    item["anchor_gap_occurrence_id"] = gap_occurrence_id(anchor)
    item["anchor_failure_date"] = anchor.get("recent_failure_date")
    item["selection_mode"] = selection_mode
    item["match_mode"] = match_mode
    item["match_reasons"] = list(match_reasons)
    item["matched_knowledge"] = list(matched_knowledge or [])
    # The score target is the due anchor.  The delivered card's own schedule is
    # deliberately preserved.
    item["unit_id"] = anchor.get("unit_id")
    item["unit_source_version"] = anchor.get("unit_source_version")
    item["due_date"] = anchor.get("due_date")
    anchor_label = (
        "近 7 天活跃错点"
        if selection_mode.startswith("recent_gap_")
        else "正式到期单元的代理检查"
    )
    item["selection_reason"] = (
        f"{anchor_label} {anchor.get('id')}；"
        f"实际投递已入库旧题 {delivered.get('id')}；"
        f"匹配层级 {match_mode}"
    )
    identity = {
        "anchor_gap_occurrence_id": item["anchor_gap_occurrence_id"],
        "delivered_id": item.get("id"),
        "delivered_card_source_version": item.get("card_source_version"),
        "match_mode": match_mode,
        "match_reasons": item["match_reasons"],
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    item["queue_item_id"] = f"QI-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:20]}"
    return item


def attach_direct_due(candidate: dict[str, Any]) -> dict[str, Any]:
    item = deepcopy(candidate)
    item["anchor_id"] = candidate.get("id")
    item["anchor_unit_id"] = candidate.get("unit_id")
    item["anchor_due_date"] = candidate.get("due_date")
    item["anchor_card_source_version"] = candidate.get("card_source_version")
    item["anchor_unit_source_version"] = candidate.get("unit_source_version")
    item["anchor_evidence_source_version"] = candidate.get("evidence_source_version")
    item["anchor_evidence"] = deepcopy(candidate.get("evidence") or {})
    item["anchor_wrong_event_id"] = candidate.get("latest_wrong_event_id")
    item["anchor_gap_occurrence_id"] = gap_occurrence_id(candidate)
    item["anchor_failure_date"] = candidate.get("recent_failure_date")
    item["delivered_unit_id"] = candidate.get("unit_id")
    item["delivered_due_date"] = candidate.get("due_date")
    item["delivered_unit_source_version"] = candidate.get("unit_source_version")
    item["selection_mode"] = "formal_due"
    item["match_mode"] = "direct_due"
    item["match_reasons"] = ["七天外原题本身正式到期"]
    item["matched_knowledge"] = []
    identity = {
        "anchor_gap_occurrence_id": item["anchor_gap_occurrence_id"],
        "delivered_id": item.get("id"),
        "match_mode": "direct_due",
        "unit_source_version": item.get("unit_source_version"),
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    item["queue_item_id"] = f"QI-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:20]}"
    item["selection_reason"] = (
        f"七天外原题正式到期 {format_date(candidate.get('due_date'))}；"
        f"动态优先级 {candidate.get('dynamic_priority')}"
    )
    return item


def prepare_warmup_selection(
    current_date: date,
    count: int,
    config: dict[str, Any],
    units: list[dict[str, Any]],
    exam_date: date | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], date]:
    import training_evidence

    active_gap_days = max(1, to_int(config.get("active_gap_days"), 7))
    exclude_recent_days = to_int(config.get("exclude_recent_days"), 7)
    delivery_cutoff = current_date - timedelta(days=exclude_recent_days + 1)
    candidates = build_warmup_candidates(current_date, config, units, exam_date=exam_date)
    candidates_by_id = {str(candidate.get("id")): candidate for candidate in candidates}
    card_id_by_unit_id = {
        str(candidate.get("unit_id")): str(candidate.get("id"))
        for candidate in candidates
        if candidate.get("unit_id")
    }

    due_candidates = sorted(
        [candidate for candidate in candidates if candidate.get("is_due")],
        key=warmup_due_sort_key,
    )
    active_anchors: list[dict[str, Any]] = []
    resolved_anchors: list[dict[str, Any]] = []
    formal_proxy_anchors: list[dict[str, Any]] = []
    covered_formal_proxy_anchors: list[dict[str, Any]] = []
    marker_events = score_marker_events(units)
    for candidate in due_candidates:
        recent_gap = (
            candidate.get("targeted_schedule")
            and within_recent_window(
                current_date,
                candidate.get("recent_failure_date"),
                active_gap_days,
            )
        )
        needs_proxy_delivery = bool(candidate.get("independently_correct")) or not (
            delivery_card_is_old_enough(
                candidate,
                current_date,
                exclude_recent_days,
            )
        )
        recent_resolution: dict[str, Any] | None = None
        if recent_gap:
            recent_resolution = active_gap_resolution_event(
                candidate,
                candidates_by_id,
                card_id_by_unit_id,
                current_date,
                marker_events,
                respect_schedule_origin=False,
            )
            if recent_resolution:
                resolved = deepcopy(candidate)
                resolved["resolution_event_id"] = recent_resolution.get("event_id")
                resolved_anchors.append(resolved)
            else:
                active_anchors.append(candidate)

        # A formal due schedule remains valid after the recent-gap occurrence
        # is resolved.  If the original card is still inside its own delivery
        # window, use a separately labeled proxy instead of pretending the gap
        # is still a recent active error.  A knowledge fallback that covered the
        # still-current due schedule suppresses repeated daily proxy delivery.
        if needs_proxy_delivery and (not recent_gap or recent_resolution):
            due_coverage = active_gap_resolution_event(
                candidate,
                candidates_by_id,
                card_id_by_unit_id,
                current_date,
                marker_events,
                respect_schedule_origin=True,
            )
            if due_coverage:
                covered = deepcopy(candidate)
                covered["resolution_event_id"] = due_coverage.get("event_id")
                covered_formal_proxy_anchors.append(covered)
            else:
                formal_proxy_anchors.append(candidate)
    active_anchors.sort(key=warmup_due_sort_key)
    formal_proxy_anchors.sort(key=warmup_due_sort_key)

    proxy_anchor_ids = {
        str(anchor.get("id"))
        for anchor in [*active_anchors, *formal_proxy_anchors]
    }
    delivery_pool = [
        candidate
        for candidate in candidates
        if str(candidate.get("status") or "") not in MASTERED_STATUSES
        and not candidate.get("independently_correct")
        and str(candidate.get("id")) not in proxy_anchor_ids
        and delivery_card_is_old_enough(candidate, current_date, exclude_recent_days)
    ]

    selected: list[dict[str, Any]] = []
    used_delivery_ids: set[str] = set()

    def exact_choices(anchor: dict[str, Any]) -> list[tuple[int, dict[str, Any], list[str]]]:
        choices: list[tuple[int, dict[str, Any], list[str]]] = []
        anchor_evidence = anchor.get("evidence") if isinstance(anchor.get("evidence"), dict) else {}
        for delivered in delivery_pool:
            delivered_id = str(delivered.get("id") or "")
            if delivered_id in used_delivery_ids or delivered_id == anchor.get("id"):
                continue
            delivered_evidence = (
                delivered.get("evidence") if isinstance(delivered.get("evidence"), dict) else {}
            )
            score, reasons = training_evidence.exact_evidence_match(
                anchor_evidence,
                delivered_evidence,
            )
            if score > 0:
                choices.append((score, delivered, reasons))
        choices.sort(key=lambda value: (-value[0], warmup_due_sort_key(value[1])))
        return choices

    def knowledge_choices(
        anchor: dict[str, Any],
    ) -> list[tuple[int, int, dict[str, Any], list[str]]]:
        choices: list[tuple[int, int, dict[str, Any], list[str]]] = []
        anchor_evidence = anchor.get("evidence") if isinstance(anchor.get("evidence"), dict) else {}
        for delivered in delivery_pool:
            delivered_id = str(delivered.get("id") or "")
            if delivered_id in used_delivery_ids or delivered_id == anchor.get("id"):
                continue
            delivered_evidence = (
                delivered.get("evidence") if isinstance(delivered.get("evidence"), dict) else {}
            )
            shared = training_evidence.shared_knowledge(anchor_evidence, delivered_evidence)
            if not shared:
                continue
            fine_count = sum(1 for item in shared if item not in BROAD_KNOWLEDGE)
            choices.append((fine_count, len(shared), delivered, shared))
        choices.sort(
            key=lambda value: (-value[0], -value[1], warmup_due_sort_key(value[2]))
        )
        return choices

    def append_proxy_for_anchor(anchor: dict[str, Any], *, recent: bool) -> bool:
        exact = exact_choices(anchor)
        if exact:
            score, delivered, reasons = exact[0]
            item = attach_warmup_anchor(
                delivered,
                anchor,
                selection_mode=(
                    "recent_gap_exact" if recent else "formal_due_proxy_exact"
                ),
                match_mode="exact_gap",
                match_reasons=[*reasons, f"确定性匹配分 {score}"],
            )
        else:
            fallback = knowledge_choices(anchor)
            if not fallback:
                return False
            _, _, delivered, shared = fallback[0]
            item = attach_warmup_anchor(
                delivered,
                anchor,
                selection_mode=(
                    "recent_gap_knowledge_fallback"
                    if recent
                    else "formal_due_proxy_knowledge_fallback"
                ),
                match_mode="knowledge_fallback",
                match_reasons=["精确错点候选不足，仅按已入库知识点补位"],
                matched_knowledge=shared,
            )
        selected.append(item)
        used_delivery_ids.add(str(item.get("id")))
        return True

    # Each active recent gap first receives one representative old card.  This
    # protected pass prevents a large overdue backlog from burying a fresh
    # recurrence.  Exact personal-gap evidence wins; knowledge is fallback.
    for anchor in active_anchors:
        if len(selected) >= count:
            break
        append_proxy_for_anchor(anchor, recent=True)

    # A later formal stage may still be due after the recent occurrence has
    # been resolved.  Keep that schedule, but label its proxy independently.
    for anchor in formal_proxy_anchors:
        if len(selected) >= count:
            break
        append_proxy_for_anchor(anchor, recent=False)

    direct_due_pool = [
        candidate
        for candidate in due_candidates
        if str(candidate.get("id")) not in proxy_anchor_ids
        and str(candidate.get("id"))
        not in {str(anchor.get("id")) for anchor in covered_formal_proxy_anchors}
        and str(candidate.get("id")) not in used_delivery_ids
        and str(candidate.get("status") or "") not in MASTERED_STATUSES
        and not candidate.get("independently_correct")
        and delivery_card_is_old_enough(candidate, current_date, exclude_recent_days)
    ]
    for candidate in direct_due_pool:
        if len(selected) >= count:
            break
        item = attach_direct_due(candidate)
        selected.append(item)
        used_delivery_ids.add(str(item.get("id")))

    supplemental_pool: list[dict[str, Any]] = []
    if len(selected) < count and not active_anchors and not formal_proxy_anchors:
        for candidate in candidates:
            if candidate.get("is_due"):
                continue
            due_date = candidate.get("due_date")
            if not isinstance(due_date, date) or due_date <= current_date:
                continue
            if str(candidate.get("status") or "") in MASTERED_STATUSES:
                continue
            if candidate.get("independently_correct"):
                continue
            if str(candidate.get("id")) in used_delivery_ids:
                continue
            if not delivery_card_is_old_enough(candidate, current_date, exclude_recent_days):
                continue
            evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
            if not evidence.get("structured_targetable"):
                continue
            candidate["selection_mode"] = "supplemental_training"
            candidate["selection_reason"] = (
                f"正式到期不足时的非到期补位；"
                f"证据 {evidence.get('origin_label')}；"
                f"下次正式到期 {format_date(due_date)}"
            )
            supplemental_pool.append(candidate)
        supplemental_pool.sort(key=lambda item: warmup_supplemental_sort_key(item, current_date))
        for candidate in supplemental_pool[: count - len(selected)]:
            item = deepcopy(candidate)
            item["selection_mode"] = "supplemental_training"
            item["match_mode"] = "unanchored_supplemental"
            item["delivered_unit_id"] = item.get("unit_id")
            item["delivered_due_date"] = item.get("due_date")
            item["queue_item_id"] = f"QI-{hashlib.sha256((str(item.get('id')) + str(item.get('card_source_version'))).encode('utf-8')).hexdigest()[:20]}"
            selected.append(item)
            used_delivery_ids.add(str(item.get("id")))

    stats = {
        "candidate_total": len(candidates),
        "permanent_independent_correct_total": sum(
            1 for candidate in candidates if candidate.get("independently_correct")
        ),
        "formal_due_total": len(due_candidates),
        "active_gap_days": active_gap_days,
        "active_gap_total": len(active_anchors),
        "resolved_recent_gap_total": len(resolved_anchors),
        "formal_due_proxy_total": len(formal_proxy_anchors),
        "covered_formal_due_proxy_total": len(covered_formal_proxy_anchors),
        "selected_recent_gap_exact_count": sum(
            1
            for candidate in selected
            if candidate.get("selection_mode") == "recent_gap_exact"
        ),
        "selected_knowledge_fallback_count": sum(
            1 for candidate in selected if candidate.get("match_mode") == "knowledge_fallback"
        ),
        "selected_formal_due_proxy_count": sum(
            1
            for candidate in selected
            if str(candidate.get("selection_mode") or "").startswith("formal_due_proxy_")
        ),
        "selected_due_count": sum(
            1 for candidate in selected if candidate.get("selection_mode") == "formal_due"
        ),
        "supplemental_eligible_total": len(supplemental_pool),
        "selected_supplemental_count": sum(
            1 for candidate in selected if candidate.get("selection_mode") == "supplemental_training"
        ),
        "evidence_pending_due_count": sum(
            1
            for candidate in due_candidates
            if not candidate.get("evidence", {}).get("structured_targetable")
        ),
        "enabled_modules": [module for module in MODULES if module_is_enabled(config, module)],
    }
    return selected, stats, delivery_cutoff


def warmup_public_output_path(current_date: date, count: int) -> Path:
    suffix = "学习前5题" if count == 5 else f"学习前{count}题"
    return OUT_DIR / f"{current_date.isoformat()}_{suffix}.md"


def warmup_internal_output_path(current_date: date, count: int) -> Path:
    return warmup_public_output_path(current_date, count).with_suffix(".internal.json")


def existing_warmup_request(
    current_date: date,
    count: int,
) -> dict[str, Any] | None:
    matches = [
        item
        for item in load_warmup_logs()
        if item.get("date") == current_date.isoformat()
        and item.get("mode") == "prestudy"
        and to_int(item.get("requested_count"), -1) == count
    ]
    if len(matches) > 1:
        superseded_ids = {
            str(item.get("supersedes_queue_id") or "").strip()
            for item in matches
            if str(item.get("supersedes_queue_id") or "").strip()
        }
        active = [
            item
            for item in matches
            if str(item.get("queue_id") or "").strip() not in superseded_ids
        ]
        if len(active) != 1:
            raise RollbackSyncError(
                f"同一日期和数量的学习前队列 successor 图不唯一："
                f"{current_date.isoformat()} / {count}"
            )
        return active[0]
    return matches[0] if matches else None


def validate_existing_warmup_request(
    log_entry: dict[str, Any],
    current_date: date,
    count: int,
) -> tuple[Path, str]:
    queue_id = str(log_entry.get("queue_id") or "").strip()
    if not re.fullmatch(r"WQ-[0-9a-f]{24}", queue_id):
        raise RollbackSyncError("已记录学习前队列的 queue_id 无效")
    public_relative = str(log_entry.get("public_path") or "").strip()
    internal_relative = str(log_entry.get("internal_path") or "").strip()
    output_path = (
        (REPO_ROOT / public_relative).resolve()
        if public_relative
        else warmup_public_output_path(current_date, count).resolve()
    )
    internal_path = (
        (REPO_ROOT / internal_relative).resolve()
        if internal_relative
        else warmup_internal_output_path(current_date, count).resolve()
    )
    for path in (output_path, internal_path):
        try:
            path.relative_to(REPO_ROOT.resolve())
        except ValueError as exc:
            raise RollbackSyncError("已记录队列输出路径越出仓库") from exc
    if not output_path.exists() or not internal_path.exists():
        raise RollbackSyncError("已记录队列缺少输出文件，拒绝伪装为完成")
    expected_public_sha = str(log_entry.get("public_sha256") or "").strip()
    expected_internal_sha = str(log_entry.get("internal_sha256") or "").strip()
    if expected_public_sha and hashlib.sha256(output_path.read_bytes()).hexdigest() != expected_public_sha:
        raise RollbackSyncError("已记录队列公开文件哈希漂移")
    if expected_internal_sha and hashlib.sha256(internal_path.read_bytes()).hexdigest() != expected_internal_sha:
        raise RollbackSyncError("已记录队列内部文件哈希漂移")
    try:
        manifest = json.loads(internal_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RollbackSyncError("已记录队列的内部溯源包无效") from exc
    if not isinstance(manifest, dict):
        raise RollbackSyncError("已记录队列的内部溯源包必须是对象")
    if (
        manifest.get("queue_id") != queue_id
        or manifest.get("date") != current_date.isoformat()
        or to_int(manifest.get("requested_count"), -1) != count
    ):
        raise RollbackSyncError("已记录队列的日期、数量或队列身份冲突")

    def selected_identity(item: Any) -> tuple[str, str]:
        if not isinstance(item, dict):
            return "", ""
        return (
            str(item.get("queue_item_id") or "").strip(),
            str(item.get("delivered_card_id") or item.get("id") or "").strip(),
        )

    log_selected = log_entry.get("selected")
    manifest_selected = manifest.get("selected")
    if not isinstance(log_selected, list) or not isinstance(manifest_selected, list):
        raise RollbackSyncError("已记录队列的选题清单无效")
    if [selected_identity(item) for item in log_selected] != [
        selected_identity(item) for item in manifest_selected
    ]:
        raise RollbackSyncError("队列日志与内部溯源包的交付题身份冲突")
    public = output_path.read_text(encoding="utf-8")
    if f"队列 ID：{queue_id}" not in public:
        raise RollbackSyncError("已记录队列的公开题面缺少正确 queue_id")
    return output_path, queue_id


def warmup_internal_item(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = deepcopy(candidate.get("evidence") or {})
    return {
        "queue_item_id": candidate.get("queue_item_id"),
        "id": candidate.get("id"),
        "delivered_card_id": candidate.get("id"),
        "delivered_unit_id": candidate.get("delivered_unit_id"),
        "unit_id": candidate.get("unit_id"),
        "score_target_unit_id": candidate.get("anchor_unit_id") or candidate.get("unit_id"),
        "anchor_id": candidate.get("anchor_id"),
        "anchor_unit_id": candidate.get("anchor_unit_id"),
        "anchor_wrong_event_id": candidate.get("anchor_wrong_event_id"),
        "anchor_gap_occurrence_id": candidate.get("anchor_gap_occurrence_id"),
        "anchor_failure_date": format_date(candidate.get("anchor_failure_date")),
        "selection_mode": candidate.get("selection_mode"),
        "match_mode": candidate.get("match_mode"),
        "match_reasons": list(candidate.get("match_reasons") or []),
        "matched_knowledge": list(candidate.get("matched_knowledge") or []),
        "due_date": format_date(candidate.get("due_date")),
        "anchor_due_date": format_date(candidate.get("anchor_due_date")),
        "delivered_due_date": format_date(candidate.get("delivered_due_date")),
        "overdue_days": to_int(candidate.get("overdue_days")),
        "dynamic_priority": to_int(candidate.get("dynamic_priority")),
        "recurrence_count": to_int(candidate.get("recurrence_count")),
        "mastery": to_int(candidate.get("mastery"), 3),
        "mistakes": to_int(candidate.get("mistakes")),
        "selection_reason": candidate.get("selection_reason"),
        "formal_card_path": candidate.get("path"),
        "source": candidate.get("source"),
        "card_source_version": candidate.get("card_source_version"),
        "unit_source_version": candidate.get("unit_source_version"),
        "delivered_unit_source_version": candidate.get("delivered_unit_source_version"),
        "anchor_card_source_version": candidate.get("anchor_card_source_version"),
        "anchor_unit_source_version": candidate.get("anchor_unit_source_version"),
        "anchor_evidence_source_version": candidate.get("anchor_evidence_source_version"),
        "evidence_source_version": candidate.get("evidence_source_version"),
        "evidence": evidence,
        "anchor_evidence": deepcopy(candidate.get("anchor_evidence") or {}),
    }


def warmup_queue_id(
    selected: list[dict[str, Any]],
    stats: dict[str, Any],
    current_date: date,
    count: int,
    config: dict[str, Any],
    exam_date: date,
) -> str:
    payload = {
        "schema": WARMUP_SCHEMA_VERSION,
        "date": current_date.isoformat(),
        "mode": "prestudy",
        "requested_count": count,
        "exam_date": exam_date.isoformat(),
        "selection_stats": stats,
        "config": {
            "active_gap_days": to_int(config.get("active_gap_days"), 7),
            "exclude_recent_days": to_int(config.get("exclude_recent_days"), 7),
            "modules": config.get("modules", {}),
        },
        "selected": [
            {
                "queue_item_id": candidate.get("queue_item_id"),
                "id": candidate.get("id"),
                "mode": candidate.get("selection_mode"),
                "match_mode": candidate.get("match_mode"),
                "anchor_id": candidate.get("anchor_id"),
                "anchor_gap_occurrence_id": candidate.get("anchor_gap_occurrence_id"),
                "formal_card_path": candidate.get("path"),
                "card_source_version": candidate.get("card_source_version"),
                "evidence_source_version": candidate.get("evidence_source_version"),
                "unit_source_version": candidate.get("unit_source_version"),
                "anchor_evidence_source_version": candidate.get(
                    "anchor_evidence_source_version"
                ),
            }
            for candidate in selected
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"WQ-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:24]}"


def render_warmup(
    selected: list[dict[str, Any]],
    stats: dict[str, Any],
    current_date: date,
    count: int,
    delivery_cutoff: date,
    queue_id: str = "dry-run",
) -> str:
    lines = [
        f"# {current_date.isoformat()} 学习前 {count} 题",
        "",
        "用途：正式学习前的独立闭卷复做。最近七天的到期错点负责触发选题，实际题面只来自已入库且从未无提示独立做对的旧题。",
        "",
        f"队列 ID：{queue_id}",
        "",
        "## 一、选题边界",
        "- 错因检查起始日只表示该错点开始具备复盘资格，不表示次日直接投递原题。",
        f"- 实际投递卡最近活动距今天超过 7 天；日期边界为 {delivery_cutoff.isoformat()} 或更早。",
        "- 曾经无提示独立做对的卡永久不再实际投递；4～5 分触发该门禁，3 分不触发。",
        "- 先匹配同一具体错点或方法断点；没有精确旧题时，才用同知识点的已入库卡补位并明确降级标记。",
        "- warmup 不生成新题，也不会把任何生成题写入数学错题库。",
        "- 本页不显示具体错因、目标方法或解析；这些信息只保存在内部队列包中。",
        f"- 已启用模块：{'、'.join(stats.get('enabled_modules', []))}",
        f"- 最近七天活跃错点 {stats.get('active_gap_total', 0)} 个；已被后续正确覆盖 {stats.get('resolved_recent_gap_total', 0)} 个。",
        f"- 已根据历史无提示独立做对证据永久排除 {stats.get('permanent_independent_correct_total', 0)} 张实际交付卡。",
        f"- 最近错点精确题 {stats.get('selected_recent_gap_exact_count', 0)} 道；正式到期代理题 {stats.get('selected_formal_due_proxy_count', 0)} 道；知识点补位 {stats.get('selected_knowledge_fallback_count', 0)} 道；七天外原题正式到期 {stats.get('selected_due_count', 0)} 道。",
        "",
        f"## 二、今日 {count} 题",
    ]

    if not selected:
        lines.extend(["暂无符合条件的错题候选。", ""])
    for index, candidate in enumerate(selected, start=1):
        source = candidate.get("source") or "未记录"
        mode = candidate.get("selection_mode")
        mode_label = {
            "recent_gap_exact": "近期错点的精确旧题检查",
            "recent_gap_knowledge_fallback": "近期错点的知识点补位",
            "formal_due_proxy_exact": "正式到期的精确代理检查",
            "formal_due_proxy_knowledge_fallback": "正式到期的知识点代理补位",
            "formal_due": "七天外原题正式到期",
            "supplemental_training": "非到期补位训练",
        }.get(str(mode), "旧题训练")
        lines.extend(
            [
                f"### {index}. {candidate.get('id')}",
                f"- 队列身份：{mode_label}",
                f"- 来源：{source}",
                f"- 源版本：{str(candidate.get('card_source_version') or '')[:16]}",
                "",
            ]
        )
        if mode in {
            "recent_gap_exact",
            "recent_gap_knowledge_fallback",
            "formal_due_proxy_exact",
            "formal_due_proxy_knowledge_fallback",
            "formal_due",
        }:
            lines.extend(
                [
                    "本题结束后复用单题讲解与快速入库，只保存完整 Capture，随后继续下一题。",
                    f"- Capture 附加身份：`--queue-id {queue_id} --item-id {candidate.get('queue_item_id')}`；不需要评分事件。",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "本题仅作补位训练；结束后同样只保存完整 Capture，不推进长期阶段。",
                    f"- Capture 附加身份：`--queue-id {queue_id} --item-id {candidate.get('queue_item_id')}`；不需要评分事件。",
                    "",
                ]
            )

    lines.extend(
        [
            "## 三、作答后边界",
            "- 晨间逐题只讲解并保存 Capture；正式判分、长期调度、知识点更新与发布留到后续正式入库。",
            "- 对错、首答、提示依赖、纠正过程和卷面写法原样保留，不把提示后完成写成独立掌握。",
            "- Capture 成功或幂等返回后立即继续预处理的下一题，不在学习中修复旧评分引用。",
        ]
    )
    if len(selected) < count:
        lines.append(f"- 已入库旧题不足 {count} 道，本次只输出 {len(selected)} 道；不生成新题凑数。")
    lines.append("")
    return "\n".join(lines)


def warmup_bundle(
    current_date: date,
    count: int,
    config: dict[str, Any],
    units: list[dict[str, Any]],
    exam_date: date,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    selected, stats, delivery_cutoff = prepare_warmup_selection(
        current_date,
        count,
        config,
        units,
        exam_date=exam_date,
    )
    queue_id = warmup_queue_id(selected, stats, current_date, count, config, exam_date)
    manifest = {
        "schema_version": WARMUP_SCHEMA_VERSION,
        "queue_id": queue_id,
        "date": current_date.isoformat(),
        "mode": "prestudy",
        "requested_count": count,
        "actual_count": len(selected),
        "exam_date": exam_date.isoformat(),
        "stats": stats,
        "selected": [warmup_internal_item(candidate) for candidate in selected],
    }
    content = render_warmup(
        selected,
        stats,
        current_date,
        count,
        delivery_cutoff,
        queue_id=queue_id,
    )
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    log_entry = {
        "schema_version": WARMUP_SCHEMA_VERSION,
        "queue_id": queue_id,
        "date": current_date.isoformat(),
        "mode": "prestudy",
        "requested_count": count,
        "selected": [
            {
                "queue_item_id": candidate.get("queue_item_id"),
                "id": candidate.get("id"),
                "delivered_card_id": candidate.get("id"),
                "delivered_unit_id": candidate.get("delivered_unit_id"),
                "unit_id": candidate.get("unit_id"),
                "anchor_id": candidate.get("anchor_id"),
                "anchor_unit_id": candidate.get("anchor_unit_id"),
                "anchor_gap_occurrence_id": candidate.get("anchor_gap_occurrence_id"),
                "selection_mode": candidate.get("selection_mode"),
                "match_mode": candidate.get("match_mode"),
                "due_date": format_date(candidate.get("due_date")),
                "card_source_version": candidate.get("card_source_version"),
                "evidence_source_version": candidate.get("evidence_source_version"),
                "unit_source_version": candidate.get("unit_source_version"),
                "anchor_card_source_version": candidate.get("anchor_card_source_version"),
                "anchor_unit_source_version": candidate.get("anchor_unit_source_version"),
                "anchor_evidence_source_version": candidate.get(
                    "anchor_evidence_source_version"
                ),
            }
            for candidate in selected
        ],
    }
    return content, manifest_text, manifest, log_entry


def cmd_warmup(args: argparse.Namespace) -> None:
    current_date = today_from_arg(args.date)
    config = load_progress_config()
    count = args.count or to_int(config.get("default_count"), 5)
    if count <= 0:
        raise SystemExit("题目数量必须大于 0。")

    try:
        exam_date = load_exam_date(required=True)
    except RollbackSyncError as exc:
        raise SystemExit(str(exc)) from exc
    assert exam_date is not None
    if current_date > exam_date:
        raise SystemExit("学习前队列日期不得晚于考试日期。")

    def prepare() -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        units = load_units()
        return warmup_bundle(current_date, count, config, units, exam_date)

    if args.dry_run:
        try:
            existing_request = existing_warmup_request(current_date, count)
            if existing_request is not None:
                output_path, _ = validate_existing_warmup_request(
                    existing_request,
                    current_date,
                    count,
                )
                print(output_path.read_text(encoding="utf-8"), end="")
                return
        except RollbackSyncError as exc:
            raise SystemExit(str(exc)) from exc
        content, _, _, _ = prepare()
        print(content)
        return

    lock_path = WARMUP_LOG_PATH.with_name(f".{WARMUP_LOG_PATH.name}.lock")
    with exclusive_file_lock(lock_path):
        try:
            existing_request = existing_warmup_request(current_date, count)
            if existing_request is not None:
                output_path, queue_id = validate_existing_warmup_request(
                    existing_request,
                    current_date,
                    count,
                )
                print(f"已存在，本次 noop：{output_path}（{queue_id}）")
                return
        except RollbackSyncError as exc:
            raise SystemExit(str(exc)) from exc
        content, manifest_text, manifest, log_entry = prepare()
        queue_id = str(manifest["queue_id"])
        output_path = warmup_public_output_path(current_date, count)
        internal_path = warmup_internal_output_path(current_date, count)
        existing = [item for item in load_warmup_logs() if item.get("queue_id") == queue_id]
        if existing:
            if len(existing) != 1:
                raise SystemExit(f"学习前队列日志存在重复 queue_id：{queue_id}")
            if not output_path.exists() or not internal_path.exists():
                raise SystemExit("已记录队列缺少输出文件，拒绝伪装为完成。")
            if output_path.read_text(encoding="utf-8") != content:
                raise SystemExit("已记录队列的公开题面与当前内容不一致，拒绝覆盖。")
            if internal_path.read_text(encoding="utf-8") != manifest_text:
                raise SystemExit("已记录队列的内部溯源包与当前内容不一致，拒绝覆盖。")
            print(f"已存在，本次 noop：{output_path}（{queue_id}）")
            return

        atomic_write_text(output_path, content)
        atomic_write_text(internal_path, manifest_text)
        append_jsonl_entry(WARMUP_LOG_PATH, log_entry)
    print(f"已生成：{output_path}（{queue_id}）")


def warmup_v5_runtime() -> dict[str, Any]:
    """Expose the live, possibly test-patched scheduler runtime to warmup_v5.

    The semantic module owns the new two-phase protocol, while this mapping
    keeps every ledger/path/function binding identical to the canonical
    scheduler instance.  It contains no model shim and performs no delegation.
    """

    return globals()


def cmd_warmup_candidates(args: argparse.Namespace) -> None:
    import warmup_v5

    warmup_v5.cmd_candidates(args, warmup_v5_runtime())


def cmd_same_item_repair(args: argparse.Namespace) -> None:
    import warmup_v5

    warmup_v5.cmd_same_item_repair(args, warmup_v5_runtime())


def cmd_warmup_successor(args: argparse.Namespace) -> None:
    import warmup_v5

    warmup_v5.cmd_successor(args, warmup_v5_runtime())


def find_warmup_queue_item(
    queue_id: str,
    queue_item_id: str,
    current_date: date,
) -> dict[str, Any]:
    import training_evidence

    queues = [item for item in load_warmup_logs() if item.get("queue_id") == queue_id]
    if len(queues) != 1:
        raise RollbackSyncError(
            f"学习前队列身份必须唯一：{queue_id}（实际 {len(queues)} 条）"
        )
    queue = queues[0]
    queue_schema_version = str(queue.get("schema_version") or "")
    if queue_schema_version not in SUPPORTED_WARMUP_SCHEMA_VERSIONS:
        raise RollbackSyncError("只有 v3/v4/v5 学习前队列可以使用 score-warmup")
    if queue.get("date") != current_date.isoformat():
        raise RollbackSyncError("队列日期与评分日期不一致")
    requested_count = to_int(queue.get("requested_count"), 0)
    if requested_count <= 0:
        raise RollbackSyncError("学习前队列缺少有效 requested_count")
    logged_selected = queue.get("selected")
    if not isinstance(logged_selected, list):
        raise RollbackSyncError("学习前队列 selected 必须是数组")
    logged_matches = [
        item
        for item in logged_selected
        if isinstance(item, dict) and item.get("queue_item_id") == queue_item_id
    ]
    if len(logged_matches) != 1:
        raise RollbackSyncError(
            f"队列项身份必须唯一：{queue_item_id}（实际 {len(logged_matches)} 条）"
        )

    internal_relative = str(queue.get("internal_path") or "").strip()
    if internal_relative:
        internal_path = (REPO_ROOT / internal_relative).resolve()
        try:
            internal_path.relative_to(REPO_ROOT.resolve())
        except ValueError as exc:
            raise RollbackSyncError("学习前队列 internal_path 越出仓库") from exc
    else:
        internal_path = warmup_internal_output_path(current_date, requested_count)
    if not internal_path.exists():
        raise RollbackSyncError("学习前队列缺少内部溯源包，拒绝评分")
    expected_internal_sha256 = str(queue.get("internal_sha256") or "").strip()
    if expected_internal_sha256 and hashlib.sha256(internal_path.read_bytes()).hexdigest() != expected_internal_sha256:
        raise RollbackSyncError("学习前队列内部溯源包哈希与日志不一致")
    try:
        manifest = json.loads(internal_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RollbackSyncError("学习前队列内部溯源包不是有效 JSON") from exc
    if not isinstance(manifest, dict):
        raise RollbackSyncError("学习前队列内部溯源包顶层必须是对象")
    if (
        manifest.get("schema_version") != queue_schema_version
        or manifest.get("queue_id") != queue_id
        or manifest.get("date") != current_date.isoformat()
        or to_int(manifest.get("requested_count"), 0) != requested_count
    ):
        raise RollbackSyncError("学习前队列日志与内部溯源包身份不一致")
    internal_selected = manifest.get("selected")
    if not isinstance(internal_selected, list):
        raise RollbackSyncError("内部溯源包 selected 必须是数组")
    internal_matches = [
        item
        for item in internal_selected
        if isinstance(item, dict) and item.get("queue_item_id") == queue_item_id
    ]
    if len(internal_matches) != 1:
        raise RollbackSyncError(
            f"内部溯源队列项必须唯一：{queue_item_id}（实际 {len(internal_matches)} 条）"
        )

    logged_item = logged_matches[0]
    item = deepcopy(internal_matches[0])
    identity_fields = (
        "queue_item_id",
        "id",
        "delivered_card_id",
        "delivered_unit_id",
        "unit_id",
        "anchor_id",
        "anchor_unit_id",
        "anchor_gap_occurrence_id",
        "selection_mode",
        "match_mode",
        "card_source_version",
        "evidence_source_version",
        "unit_source_version",
        "anchor_card_source_version",
        "anchor_unit_source_version",
        "anchor_evidence_source_version",
    )
    if queue_schema_version == SEMANTIC_WARMUP_SCHEMA_VERSION:
        identity_fields = (
            *identity_fields,
            *(("selection_anchor",) if item.get("selection_anchor") else ()),
            "semantic_selection_v5",
            "semantic_match_level",
            "reader_query_id" if manifest.get("request_version") == "native-reader-semantic-v2" else "luna_query_id",
        )
    for field in identity_fields:
        if field not in logged_item or logged_item.get(field) != item.get(field):
            raise RollbackSyncError(f"学习前队列日志字段与内部溯源不一致：{field}")

    if item.get("match_mode") not in {"exact_gap", "knowledge_fallback", "direct_due"}:
        raise RollbackSyncError("学习前队列 match_mode 无效")
    for field in (
        "card_source_version",
        "evidence_source_version",
        "anchor_card_source_version",
        "anchor_unit_source_version",
        "anchor_evidence_source_version",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(item.get(field) or "")):
            raise RollbackSyncError(f"学习前队列缺少有效来源版本：{field}")
    if not CARD_ID_PATTERN.fullmatch(str(item.get("anchor_id") or "")):
        raise RollbackSyncError("学习前队列 anchor_id 无效")
    if not CARD_ID_PATTERN.fullmatch(str(item.get("delivered_card_id") or "")):
        raise RollbackSyncError("学习前队列 delivered_card_id 无效")
    if not re.fullmatch(r"GAPO-[0-9a-f]{24}", str(item.get("anchor_gap_occurrence_id") or "")):
        raise RollbackSyncError("学习前队列 active occurrence 身份无效")
    evidence = training_evidence.normalized_evidence_snapshot(
        item.get("evidence"),
        str(item.get("delivered_card_id") or item.get("id") or "").strip(),
    )
    anchor_evidence = training_evidence.normalized_evidence_snapshot(
        item.get("anchor_evidence"),
        str(item.get("anchor_id") or "").strip(),
    )
    if evidence is None or evidence.get("source_version") != item.get(
        "evidence_source_version"
    ):
        raise RollbackSyncError("实际交付题证据快照与来源版本不一致")
    if anchor_evidence is None or anchor_evidence.get("source_version") != item.get(
        "anchor_evidence_source_version"
    ):
        raise RollbackSyncError("anchor 证据快照与来源版本不一致")
    item["evidence"] = evidence
    item["anchor_evidence"] = anchor_evidence
    if item.get("selection_mode") == "supplemental_training":
        raise RollbackSyncError("非到期补位训练不得提交长期评分")
    anchor_unit_id = str(item.get("anchor_unit_id") or item.get("unit_id") or "").strip()
    delivered_card_id = str(item.get("delivered_card_id") or item.get("id") or "").strip()
    if not anchor_unit_id or not delivered_card_id:
        raise RollbackSyncError("学习前队列缺少 anchor 或 delivered 身份")
    item["queue_id"] = queue_id
    item["queue_date"] = current_date.isoformat()
    item["queue_item_id"] = queue_item_id
    item["anchor_unit_id"] = anchor_unit_id
    item["delivered_card_id"] = delivered_card_id
    return item


def cmd_score_warmup(args: argparse.Namespace) -> None:
    if not getattr(args, "formal_intake", False) and not getattr(args, "dry_run", False):
        import math_review
        print(json.dumps(math_review.capture_required(
            queue_id=args.queue_id,
            queue_item_id=getattr(args, "queue_item_id", None) or getattr(args, "item_id", None),
        ), ensure_ascii=False, sort_keys=True))
        return
    current_date = today_from_arg(args.date)
    queue_item_id = str(
        getattr(args, "queue_item_id", None) or getattr(args, "item_id", None) or ""
    ).strip()
    if not queue_item_id:
        raise SystemExit("缺少 queue_item_id")
    try:
        context = find_warmup_queue_item(args.queue_id, queue_item_id, current_date)
    except RollbackSyncError as exc:
        raise SystemExit(str(exc)) from exc
    delegated = argparse.Namespace(
        unit_id=context["anchor_unit_id"],
        score=args.score,
        date=current_date.isoformat(),
        attempt_id=f"warmup:{args.queue_id}:{queue_item_id}",
        dry_run=args.dry_run,
        warmup_context=context,
    )
    cmd_score(delegated)


def cmd_sync_wrongnet(args: argparse.Namespace) -> None:
    units, expected_version = load_units_with_version()
    existing_ids = {unit.get("复习单元ID") for unit in units}
    candidates = sorted(WRONGNET_CARDS_DIR.glob("*.md"))
    added = 0
    skipped = 0
    for path in candidates:
        unit = unit_from_card(path)
        if not unit:
            skipped += 1
            continue
        if unit["复习单元ID"] in existing_ids:
            skipped += 1
            continue
        units.append(unit)
        existing_ids.add(unit["复习单元ID"])
        added += 1
        if args.limit and added >= args.limit:
            break

    if added:
        try:
            atomic_save_units(units, expected_version=expected_version)
        except (RollbackSyncError, OSError) as exc:
            raise SystemExit(f"历史批量同步未完成：{exc}") from exc
    print(f"同步完成：新增 {added} 个复习单元，跳过 {skipped} 个。")


def cmd_upsert_wrongnet(args: argparse.Namespace) -> None:
    try:
        current_date = today_from_arg(args.date)
        path = find_wrongnet_card(args.id)
        data = parse_card_frontmatter(path)
        if not data:
            raise RollbackSyncError(f"错题卡缺少可解析 frontmatter：{path.name}")
        units, expected_version = load_units_with_version()
        validate_units_document(units)
        action, before, after, index, exam_date = plan_wrongnet_upsert(
            card_id=args.id,
            data=data,
            units=units,
            current_date=current_date,
            expect_recurrence=args.expect_recurrence,
        )
        changes = top_level_diff(before, after)
        report = {
            "card_id": args.id,
            "unit_id": after.get("复习单元ID"),
            "action": action,
            "source_version": after.get("定点同步状态", {}).get("源版本"),
            "anchor_eligibility_date": after.get("下次复习日期"),
            "date_semantics": "错因检查起始日，不代表在该日直接投递原题",
            "changes": changes,
        }

        updated_units = deepcopy(units)
        if index is None:
            updated_units.append(after)
        else:
            updated_units[index] = after
            for candidate_index, candidate in enumerate(units):
                if candidate_index != index and updated_units[candidate_index] != candidate:
                    raise RollbackSyncError("计划越界修改了非目标复习单元")
        validate_units_document(
            updated_units,
            target_unit_id=str(after.get("复习单元ID")),
            exam_date=exam_date,
        )

        if args.dry_run:
            report["status"] = "dry-run，未写文件"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        if action == "noop":
            report["status"] = "回滚同步完成，同一源版本已处理，无需写入"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return

        atomic_save_units(
            updated_units,
            target_unit_id=str(after.get("复习单元ID")),
            exam_date=exam_date,
            expected_version=expected_version,
        )
        report["status"] = "回滚同步完成"
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except SystemExit:
        raise
    except Exception as exc:
        raise SystemExit(f"回滚同步未完成：{exc}") from exc


def score_event_context_matches(
    event: dict[str, Any],
    warmup_context: dict[str, Any] | None,
) -> bool:
    if warmup_context is None:
        return True
    expected = {
        "queue_id": warmup_context.get("queue_id"),
        "queue_item_id": warmup_context.get("queue_item_id"),
        "delivered_card_id": warmup_context.get("delivered_card_id"),
        "anchor_gap_occurrence_id": warmup_context.get("anchor_gap_occurrence_id"),
        "match_mode": warmup_context.get("match_mode"),
        "delivered_card_source_version": warmup_context.get("card_source_version"),
        "delivered_evidence_source_version": warmup_context.get(
            "evidence_source_version"
        ),
        "anchor_card_source_version": warmup_context.get(
            "anchor_card_source_version"
        ),
        "anchor_evidence_source_version": warmup_context.get(
            "anchor_evidence_source_version"
        ),
    }
    return all(event.get(key) == value for key, value in expected.items())


def validate_warmup_score_context(
    warmup_context: dict[str, Any],
    unit: dict[str, Any],
) -> None:
    import training_evidence

    selection_anchor = warmup_context.get("selection_anchor")
    if selection_anchor:
        if selection_anchor.get("anchor_kind") != "concept_review" or not re.fullmatch(r"MATH-CONCEPT-[0-9a-f]{24}", str(selection_anchor.get("anchor_id", ""))):
            raise RollbackSyncError("知识点选题来源身份无效")
        for ref in selection_anchor.get("source_refs", []):
            path = (REPO_ROOT / ref["path"]).resolve()
            if not path.is_relative_to(REPO_ROOT.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
                raise RollbackSyncError("知识点选题来源已变化")
        if not selection_anchor.get("source_refs"):
            raise RollbackSyncError("知识点选题缺少正式来源")

    if warmup_context.get("anchor_unit_id") != unit.get("复习单元ID"):
        raise RollbackSyncError("队列 anchor 与评分目标单元不一致")
    anchor_id = str(warmup_context.get("anchor_id") or "").strip()
    if unit.get("关联错题ID") != anchor_id:
        raise RollbackSyncError("队列 anchor ID 与评分单元关联错题不一致")
    expected_unit_version = str(warmup_context.get("anchor_unit_source_version") or "")
    if expected_unit_version and unit_schedule_source_version(unit) != expected_unit_version:
        raise RollbackSyncError("队列生成后 anchor 单元已变更，请重新生成学习前队列")

    delivered_card_id = str(warmup_context.get("delivered_card_id") or "").strip()
    if not CARD_ID_PATTERN.fullmatch(delivered_card_id):
        raise RollbackSyncError("队列 delivered_card_id 无效")
    delivered_path = find_wrongnet_card(delivered_card_id)
    expected_card_version = str(warmup_context.get("card_source_version") or "")
    if expected_card_version and hashlib.sha256(delivered_path.read_bytes()).hexdigest() != expected_card_version:
        raise RollbackSyncError("队列生成后实际投递卡已变更，拒绝写入旧队列结果")
    delivered_data = parse_card_frontmatter(delivered_path)
    delivered_evidence = training_evidence.extract_error_evidence(
        delivered_data,
        delivered_card_id,
    )
    if delivered_evidence.get("source_version") != warmup_context.get(
        "evidence_source_version"
    ):
        raise RollbackSyncError("队列生成后实际投递卡证据已变更")
    delivered_normalized = training_evidence.normalized_evidence_snapshot(
        delivered_evidence,
        delivered_card_id,
    )
    if delivered_normalized != warmup_context.get("evidence"):
        raise RollbackSyncError("实际投递题证据快照与正式卡不一致")

    expected_anchor_card_version = str(
        warmup_context.get("anchor_card_source_version") or ""
    )
    anchor_path = find_wrongnet_card(anchor_id)
    if hashlib.sha256(anchor_path.read_bytes()).hexdigest() != expected_anchor_card_version:
        raise RollbackSyncError("队列生成后 anchor 错题卡已变更，拒绝写入旧队列结果")
    anchor_data = parse_card_frontmatter(anchor_path)
    anchor_evidence = training_evidence.extract_error_evidence(anchor_data, anchor_id)
    if anchor_evidence.get("source_version") != warmup_context.get(
        "anchor_evidence_source_version"
    ):
        raise RollbackSyncError("队列生成后 anchor 证据已变更")
    anchor_normalized = training_evidence.normalized_evidence_snapshot(
        anchor_evidence,
        anchor_id,
    )
    if anchor_normalized != warmup_context.get("anchor_evidence"):
        raise RollbackSyncError("anchor 证据快照与正式卡不一致")

    match_mode = warmup_context.get("match_mode")
    semantic_selection_v5 = warmup_context.get("semantic_selection_v5") is True
    if not semantic_selection_v5:
        exact_score, _ = training_evidence.exact_evidence_match(
            anchor_evidence,
            delivered_evidence,
        )
        shared_knowledge = training_evidence.shared_knowledge(
            anchor_evidence,
            delivered_evidence,
        )
        if match_mode == "exact_gap" and exact_score <= 0:
            raise RollbackSyncError("队列 exact_gap 关系已无法验证")
        if match_mode == "knowledge_fallback":
            if exact_score > 0 or not shared_knowledge:
                raise RollbackSyncError("队列 knowledge_fallback 关系已无法验证")
    if match_mode == "direct_due" and (
        anchor_id != delivered_card_id
        or warmup_context.get("delivered_unit_id") != unit.get("复习单元ID")
    ):
        raise RollbackSyncError("队列 direct_due 身份不一致")

    if match_mode in {"exact_gap", "knowledge_fallback"}:
        anchor_failure_date = safe_parse_date(warmup_context.get("anchor_failure_date"))
        current_occurrence = {
            "id": anchor_id,
            "unit_id": unit.get("复习单元ID"),
            "due_date": safe_parse_date(unit.get("下次复习日期")),
            "recent_failure_date": anchor_failure_date,
            "latest_wrong_event_id": warmup_context.get("anchor_wrong_event_id"),
            "evidence": anchor_evidence,
            "evidence_source_version": anchor_evidence.get("source_version"),
        }
        if gap_occurrence_id(current_occurrence) != warmup_context.get(
            "anchor_gap_occurrence_id"
        ):
            raise RollbackSyncError("队列 active occurrence 已变化，请重新生成")
        if not semantic_selection_v5:
            selection_mode = str(warmup_context.get("selection_mode") or "")
            resolution = active_gap_resolution_event(
                current_occurrence,
                {},
                {},
                today_from_arg(warmup_context.get("queue_date")),
                score_marker_events(load_units()),
                respect_schedule_origin=not selection_mode.startswith("recent_gap_"),
            )
            if resolution:
                raise RollbackSyncError("队列 anchor 已被较新的正确证据覆盖，请重新生成")


def score_evidence_context_from_unit(unit: dict[str, Any]) -> dict[str, Any]:
    import training_evidence

    card_id = str(unit.get("关联错题ID") or "").strip()
    if not CARD_ID_PATTERN.fullmatch(card_id):
        return {}
    try:
        path = find_wrongnet_card(card_id)
    except RollbackSyncError as exc:
        raise RollbackSyncError(
            f"正式评分无法唯一定位关联错题卡 {card_id}，证据快照未形成"
        ) from exc
    data = parse_card_frontmatter(path)
    if not data:
        raise RollbackSyncError(
            f"正式评分关联错题卡 {card_id} 缺少可解析 frontmatter，证据快照未形成"
        )
    evidence = training_evidence.extract_error_evidence(data, card_id)
    return {
        "delivered_card_id": card_id,
        "delivered_card_source_version": hashlib.sha256(path.read_bytes()).hexdigest(),
        "delivered_evidence_source_version": evidence.get("source_version"),
        "delivered_evidence_snapshot": deepcopy(evidence),
    }


def _cmd_score(args: argparse.Namespace) -> None:
    current_date = today_from_arg(args.date)
    score = int(args.score)
    if score < 0 or score > 5:
        raise SystemExit("分数必须是 0-5。")
    warmup_context = getattr(args, "warmup_context", None)
    if warmup_context is not None and not isinstance(warmup_context, dict):
        raise SystemExit("warmup_context 结构无效。")
    attempt_type = (
        "knowledge_fallback_check"
        if warmup_context and warmup_context.get("match_mode") == "knowledge_fallback"
        else "delayed"
    )

    try:
        exam_date = load_exam_date(required=True)
    except RollbackSyncError as exc:
        raise SystemExit(str(exc)) from exc
    assert exam_date is not None
    try:
        attempt_id, event_id = score_attempt_identity(
            args.unit_id,
            current_date,
            getattr(args, "attempt_id", None),
        )
    except RollbackSyncError as exc:
        raise SystemExit(str(exc)) from exc

    lock_path = LOG_PATH.with_name(".延迟复习评分.lock")
    score_guard = nullcontext() if getattr(args, "dry_run", False) else exclusive_file_lock(lock_path)
    with score_guard:
        try:
            logs = load_review_logs()
        except RollbackSyncError as exc:
            raise SystemExit(str(exc)) from exc
        logged_events = [item for item in logs if item.get("event_id") == event_id]
        if logged_events:
            if len(logged_events) != 1 or not score_event_matches(
                logged_events[0],
                event_id=event_id,
                unit_id=args.unit_id,
                current_date=current_date,
                score=score,
                attempt_type=attempt_type,
            ):
                raise SystemExit(f"评分事件冲突：{event_id}")
            if not score_event_context_matches(logged_events[0], warmup_context):
                raise SystemExit(f"评分事件队列上下文冲突：{event_id}")
            units = load_units()
            target = next((item for item in units if item.get("复习单元ID") == args.unit_id), None)
            markers = target.get("评分事件历史", []) if isinstance(target, dict) else []
            if not any(isinstance(item, dict) and item.get("event_id") == event_id for item in markers):
                raise SystemExit("评分日志与复习单元的幂等标记不一致，拒绝继续。")
            print(f"评分事件已存在，本次 noop：{event_id}")
            return

        units, expected_version = load_units_with_version()
        unit = next((item for item in units if item.get("复习单元ID") == args.unit_id), None)
        if unit is None:
            raise SystemExit(f"未找到复习单元：{args.unit_id}")

        markers = unit.get("评分事件历史", [])
        if not isinstance(markers, list):
            raise SystemExit("评分事件历史结构无效，本次未写入。")
        stored_markers = [item for item in markers if isinstance(item, dict) and item.get("event_id") == event_id]
        if stored_markers:
            marker = stored_markers[0]
            if len(stored_markers) != 1 or not score_event_matches(
                marker,
                event_id=event_id,
                unit_id=args.unit_id,
                current_date=current_date,
                score=score,
                attempt_type=attempt_type,
            ):
                raise SystemExit(f"评分事件冲突：{event_id}")
            if not score_event_context_matches(marker, warmup_context):
                raise SystemExit(f"评分事件队列上下文冲突：{event_id}")
            # 上一次可能在单元原子替换后、日志追加前中断。
            if getattr(args, "dry_run", False):
                print(
                    json.dumps(
                        {"status": "dry-run，评分日志恢复预览，未写入", **marker},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return
            append_log(marker)
            print(f"已恢复缺失的评分日志，未重复推进单元：{event_id}")
            return

        review_basis = getattr(args, "review_source_context", None)
        if review_basis is not None:
            import math_review
            math_review.validate_current_basis(LOG_PATH.parent.parent, review_basis)
        if warmup_context is not None:
            try:
                validate_warmup_score_context(warmup_context, unit)
            except RollbackSyncError as exc:
                raise SystemExit(str(exc)) from exc

        recurrence_date = safe_parse_date(unit.get("最近复发日期"))
        if recurrence_date and current_date <= recurrence_date:
            raise SystemExit(
                "当天即时纠错不属于长期延迟复习；本次未写入评分、阶段或复习记录。"
            )
        scheduled_date = safe_parse_date(unit.get("下次复习日期"))
        if scheduled_date is None:
            raise SystemExit("当前单元没有到期的长期复习任务；本次未写入评分或日志。")
        if current_date < scheduled_date:
            raise SystemExit(f"正式延迟复习尚未到期：{scheduled_date.isoformat()}；本次未写入。")

        old = {
            "掌握度": unit.get("掌握度"),
            "当前间隔天数": unit.get("当前间隔天数"),
            "下次复习日期": unit.get("下次复习日期"),
            "错误次数": unit.get("错误次数"),
            "延迟复习阶段": unit.get("延迟复习阶段"),
            "连续延迟成功次数": unit.get("连续延迟成功次数"),
            "调度优先级": unit.get("调度优先级"),
            "复习状态": unit.get("复习状态"),
        }
        event_context: dict[str, Any] = {}
        if warmup_context is not None:
            event_context = {
                "queue_id": warmup_context.get("queue_id"),
                "queue_item_id": warmup_context.get("queue_item_id"),
                "anchor_card_id": warmup_context.get("anchor_id"),
                "anchor_gap_occurrence_id": warmup_context.get(
                    "anchor_gap_occurrence_id"
                ),
                "anchor_evidence_source_version": warmup_context.get(
                    "anchor_evidence_source_version"
                ),
                "anchor_card_source_version": warmup_context.get(
                    "anchor_card_source_version"
                ),
                "delivered_card_id": warmup_context.get("delivered_card_id"),
                "delivered_card_source_version": warmup_context.get(
                    "card_source_version"
                ),
                "delivered_evidence_source_version": warmup_context.get(
                    "evidence_source_version"
                ),
                "delivered_evidence_snapshot": deepcopy(
                    warmup_context.get("evidence") or {}
                ),
                "match_mode": warmup_context.get("match_mode"),
            }
        else:
            try:
                event_context = score_evidence_context_from_unit(unit)
            except RollbackSyncError as exc:
                raise SystemExit(str(exc)) from exc
        review_outcome = getattr(args, "review_outcome", None)
        if review_outcome is not None:
            event_context["review_outcome"] = deepcopy(review_outcome)
            event_context["review_outcome_sha256"] = args.review_outcome_sha256
            event_context["delivered_card_id"] = review_outcome["formal_id"]

        if attempt_type == "knowledge_fallback_check":
            # A broad knowledge fallback can prove that this rolling seven-day
            # occurrence no longer needs mechanical re-selection, but it does
            # not prove the same personal method gap.  Keep the long-term stage
            # and schedule untouched.
            event = {
                "event_id": event_id,
                "attempt_id": attempt_id,
                "date": current_date.isoformat(),
                "unit_id": args.unit_id,
                "score": score,
                "attempt_type": attempt_type,
                "coverage_resolves_active_gap": score >= 4,
                "advances_long_term": False,
                "long_term_success_increment": 0,
                "old": old,
                "new": deepcopy(old),
                **event_context,
            }
            if getattr(args, "dry_run", False):
                print(
                    json.dumps(
                        {"status": "dry-run，知识点补位结果未写入", **event},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return
            unit["评分事件历史"] = [*markers, event]
            try:
                atomic_save_units(
                    units,
                    target_unit_id=args.unit_id,
                    exam_date=exam_date,
                    expected_version=expected_version,
                )
            except RollbackSyncError as exc:
                raise SystemExit(str(exc)) from exc
            append_log(event)
            if score >= 4:
                print(
                    f"已记录知识点补位通过：{event_id}；"
                    "仅从最近七天活跃错点池去重，不推进长期阶段。"
                )
            else:
                print(
                    f"已记录知识点补位未通过：{event_id}；"
                    "活跃错点保留，长期阶段未变。"
                )
            return

        current_interval = to_int(unit.get("当前间隔天数"), 1)
        targeted = unit.get("调度策略版本") == "wrongnet-targeted-v1"
        stable = score >= 4
        unstable = score <= 3

        if targeted:
            import warmup_v5

            schedule = warmup_v5.stage_schedule_after_score(
                score=score,
                unit=unit,
                config=load_progress_config(),
                current_date=current_date,
                exam_date=exam_date,
            )
            proposed_interval = schedule["interval_days"]
            unit["延迟复习阶段"] = schedule["stage_index"]
            unit["连续延迟成功次数"] = schedule["independent_successes"]
            unit["证据阶段"] = schedule["stage_name"]
            unit["阶段窗口"] = schedule["window_days"]
            unit["调度优先级"] = schedule["scheduling_priority"]
        else:
            proposed_interval = next_interval_days(score, current_interval)

        try:
            interval, next_review, review_state = apply_exam_constraints(
                unit=unit,
                current_date=current_date,
                exam_date=exam_date,
                proposed_interval=proposed_interval,
                stable=stable,
                unstable=unstable,
            )
        except RollbackSyncError as exc:
            raise SystemExit(str(exc)) from exc

        unit["掌握度"] = score
        unit["上次复习日期"] = current_date.isoformat()
        unit["当前间隔天数"] = interval
        unit["下次复习日期"] = next_review
        if targeted:
            unit["复习状态"] = review_state

        if score <= 2:
            unit["错误次数"] = to_int(unit.get("错误次数")) + 1
            note = "评分 0-2，继续加密复习；需要重做原题或同类题。"
            unit["备注"] = f"{unit.get('备注', '')} {note}".strip()
        elif score >= 4:
            unit["备注"] = f"{unit.get('备注', '')} 本次评分较高，下轮可降低优先级。".strip()
        else:
            unit["备注"] = f"{unit.get('备注', '')} 评分 3，未推进长期阶段，下次只小幅增加间隔。".strip()

        new = {
            "掌握度": unit.get("掌握度"),
            "当前间隔天数": unit.get("当前间隔天数"),
            "下次复习日期": unit.get("下次复习日期"),
            "错误次数": unit.get("错误次数"),
            "延迟复习阶段": unit.get("延迟复习阶段"),
            "连续延迟成功次数": unit.get("连续延迟成功次数"),
            "调度优先级": unit.get("调度优先级"),
            "复习状态": unit.get("复习状态"),
        }
        event = {
            "event_id": event_id,
            "attempt_id": attempt_id,
            "date": current_date.isoformat(),
            "unit_id": args.unit_id,
            "score": score,
            "attempt_type": attempt_type,
            "coverage_resolves_active_gap": score >= 4,
            "advances_long_term": score >= 4,
            "long_term_success_increment": max(
                0,
                to_int(new.get("连续延迟成功次数"))
                - to_int(old.get("连续延迟成功次数")),
            ),
            "old": old,
            "new": new,
            **event_context,
        }

        if getattr(args, "dry_run", False):
            print(json.dumps({"status": "dry-run，未写入", **event}, ensure_ascii=False, indent=2))
            return

        unit["评分事件历史"] = [*markers, event]
        try:
            atomic_save_units(
                units,
                target_unit_id=args.unit_id,
                exam_date=exam_date,
                expected_version=expected_version,
            )
        except RollbackSyncError as exc:
            raise SystemExit(str(exc)) from exc
        append_log(event)
        print(
            f"已更新 {args.unit_id}：正式延迟复习 {score} 分，"
            f"下次复习 {unit.get('下次复习日期')}，间隔 {interval} 天（{event_id}）。"
        )


def cmd_score(args: argparse.Namespace) -> None:
    _cmd_score(args)
    if getattr(args, "dry_run", False):
        return
    # _cmd_score has released its score lock. A successful noop or recovered
    # log is also a recovery opportunity for the missing postcommit work.
    _attempt, event_id = score_attempt_identity(args.unit_id, today_from_arg(args.date), getattr(args, "attempt_id", None))
    import math_postcommit
    try:
        result = math_postcommit.run_after_commit(LOG_PATH.parent.parent, event_id)
    except (OSError, ValueError) as exc:
        print(f"正式评分已保存，后续刷新待恢复：{exc}", file=sys.stderr)
        return
    if result["publication"]["status"] in {"PENDING", "FAILED"}:
        print("本地评分已保存，云端待同步。", file=sys.stderr)


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def cmd_add(args: argparse.Namespace) -> None:
    current_date = today_from_arg(args.date)
    units, expected_version = load_units_with_version()
    if any(unit.get("复习单元ID") == args.id for unit in units):
        raise SystemExit(f"复习单元已存在：{args.id}")

    unit = {
        "复习单元ID": args.id,
        "科目": "数学一",
        "模块": args.module,
        "内容名称": args.name,
        "类型": args.type,
        "首次学习日期": current_date.isoformat(),
        "上次复习日期": None,
        "下次复习日期": current_date.isoformat(),
        "当前间隔天数": 0,
        "掌握度": args.mastery,
        "错误次数": args.mistakes,
        "重要程度": args.importance,
        "难度等级": args.difficulty,
        "复习方式": args.method,
        "备注": args.remark or "新学内容 D0 入库。",
        "关联错题ID": args.source_id,
        "知识点": split_csv(args.knowledge),
        "错因类型": split_csv(args.wrong_cause),
    }
    units.append(unit)
    try:
        atomic_save_units(units, expected_version=expected_version)
    except (RollbackSyncError, OSError) as exc:
        raise SystemExit(f"新增复习单元未完成：{exc}") from exc
    print(f"已新增复习单元：{args.id}，今天进入 D0 回滚。")


def load_logs() -> list[dict[str, Any]]:
    if not LOG_PATH.exists():
        return []
    logs = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            logs.append(json.loads(line))
    return logs


def unit_touched_in_week(unit: dict[str, Any], week_start: date, week_end: date) -> bool:
    for field in ["首次学习日期", "最近复发日期", "上次复习日期"]:
        value = parse_date(unit.get(field))
        if value and week_start <= value <= week_end:
            return True
    return False


def cmd_week(args: argparse.Namespace) -> None:
    current_date = today_from_arg(args.date)
    week_start = current_date - timedelta(days=current_date.weekday())
    week_end = week_start + timedelta(days=6)
    units = load_units()
    logs = [
        log
        for log in load_logs()
        if week_start <= parse_date(log.get("date")) <= week_end
    ]

    unit_by_id = {unit.get("复习单元ID"): unit for unit in units}
    reviewed_ids = [log.get("unit_id") for log in logs]
    low_score_ids = [log.get("unit_id") for log in logs if to_int(log.get("score")) < 3]
    repeated_types = Counter()
    for unit_id in low_score_ids:
        unit = unit_by_id.get(unit_id)
        if unit:
            repeated_types.update(unit.get("知识点", []))
    for unit in units:
        if unit_touched_in_week(unit, week_start, week_end) and to_int(unit.get("错误次数")) >= 2:
            repeated_types.update(unit.get("知识点", []))

    lines = [
        f"# 【数学一本周复习报告】{week_start.isoformat()} 至 {week_end.isoformat()}",
        "",
        "## 一、本周新学内容",
    ]
    new_units = [
        unit for unit in units if week_start <= parse_date(unit.get("首次学习日期")) <= week_end
    ]
    lines.extend(
        [f"- {unit.get('复习单元ID')}：{unit.get('内容名称')}" for unit in new_units]
        or ["- 本周暂无新学内容入库。"]
    )

    lines.extend(["", "## 二、本周错题总表"])
    wrong_units_by_id = {}
    for unit in units:
        if unit.get("类型") == "错题" and unit_touched_in_week(unit, week_start, week_end):
            wrong_units_by_id[unit.get("复习单元ID")] = unit
    for unit_id in reviewed_ids:
        if unit_by_id.get(unit_id, {}).get("类型") == "错题":
            wrong_units_by_id[unit_id] = unit_by_id[unit_id]
    wrong_units = list(wrong_units_by_id.values())
    lines.extend(
        [f"- {unit.get('复习单元ID')}：{unit.get('内容名称')}" for unit in wrong_units]
        or ["- 本周暂无已评分错题记录。"]
    )

    lines.extend(["", "## 三、本周掌握度低于3分的内容"])
    low_units_by_id = {
        unit.get("复习单元ID"): unit
        for unit in units
        if to_int(unit.get("掌握度")) < 3
        and unit_touched_in_week(unit, week_start, week_end)
    }
    for unit_id in low_score_ids:
        if unit_id in unit_by_id:
            low_units_by_id[unit_id] = unit_by_id[unit_id]
    lines.extend(
        [
            f"- {unit.get('复习单元ID')}：{unit.get('内容名称')}（当前掌握度 {unit.get('掌握度')} 分）"
            for unit in low_units_by_id.values()
        ]
        or ["- 本周暂无低于 3 分的内容。"]
    )

    lines.extend(["", "## 四、本周反复出错的题型"])
    lines.extend(
        [f"- {name}：{count} 次" for name, count in repeated_types.most_common(8)]
        or ["- 暂无足够评分记录判断反复出错题型。"]
    )

    lines.extend(["", "## 五、下周需要重点回滚的内容"])
    focus_units = sorted(
        [unit for unit in units if to_int(unit.get("掌握度")) <= 2 or to_int(unit.get("错误次数")) >= 3],
        key=lambda unit: priority_score(unit, current_date),
        reverse=True,
    )
    lines.extend(
        [f"- {unit.get('复习单元ID')}：{unit.get('内容名称')}" for unit in focus_units[:10]]
        or ["- 暂无高危单元。"]
    )

    lines.extend(["", "## 六、哪些内容可以降低频率"])
    stable_units = [
        unit for unit in units if to_int(unit.get("掌握度")) >= 4 and to_int(unit.get("错误次数")) <= 1
    ]
    lines.extend(
        [f"- {unit.get('复习单元ID')}：{unit.get('内容名称')}" for unit in stable_units[:10]]
        or ["- 暂无可以明显降低频率的内容。"]
    )

    lines.extend(["", "## 七、哪些内容必须重新学"])
    relearn_units = [unit for unit in units if to_int(unit.get("掌握度")) <= 1]
    lines.extend(
        [f"- {unit.get('复习单元ID')}：{unit.get('内容名称')}" for unit in relearn_units]
        or ["- 暂无必须重新学的内容。"]
    )
    lines.append("")

    OUT_DIR.mkdir(exist_ok=True)
    output_path = OUT_DIR / f"{current_date.isoformat()}_周回滚报告.md"
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成：{output_path}")


def cmd_import_review_source(args: argparse.Namespace) -> None:
    import math_review
    try:
        document = json.loads(Path(args.manifest_file).read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("manifest_must_be_object")
        result = math_review.import_source(REPO_ROOT, document, sys.modules[__name__])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "invalid", "reason": str(exc), "learning_events_written": 0}, ensure_ascii=False))
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def cmd_record_review_outcome(args: argparse.Namespace) -> None:
    import contextlib
    import io
    import math_review
    try:
        document = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("outcome_must_be_object")
        with contextlib.redirect_stdout(io.StringIO()):
            result = math_review.record_outcome(REPO_ROOT, document, sys.modules[__name__],
                                                formal_intake=getattr(args, "formal_intake", False))
    except (OSError, ValueError, KeyError, TypeError, SystemExit) as exc:
        print(json.dumps({"status": "invalid", "reason": str(exc)}, ensure_ascii=False))
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def cmd_show_review_source(args: argparse.Namespace) -> None:
    import math_review
    try:
        result = math_review.show_source(REPO_ROOT, args.run_id, sys.modules[__name__], today_from_arg(args.date))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "invalid", "reason": str(exc), "learning_events_written": 0}, ensure_ascii=False))
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="数学一回滚复习调度系统")
    subparsers = parser.add_subparsers(dest="command", required=True)

    imported = subparsers.add_parser("import-review-source", help="注册已发布版本对应的B/C原始文档；不记录作答")
    imported.add_argument("--manifest-file", required=True, help="math-review-source-v1/v2 JSON；C 知识点选题使用 v2")
    imported.set_defaults(func=cmd_import_review_source)
    shown = subparsers.add_parser("show-review-source", help="生成C已验证原题展示并记录一次交付；不展示答案或评分")
    shown.add_argument("--run-id", required=True)
    shown.add_argument("--date")
    shown.set_defaults(func=cmd_show_review_source)
    outcome = subparsers.add_parser("record-review-outcome", help="正式入库时记录B/C结果；C晨间学习默认返回Capture入口")
    outcome.add_argument("--payload-file", required=True, help="math-review-outcome-v1 JSON")
    outcome.add_argument("--formal-intake", action="store_true", help="仅在用户已要求正式入库时使用；晨间快速保存不得添加")
    outcome.set_defaults(func=cmd_record_review_outcome)

    today_parser = subparsers.add_parser("today", help="生成今日到期复习队列")
    today_parser.add_argument("--date", help="指定日期 YYYY-MM-DD")
    today_parser.set_defaults(func=cmd_today)

    score_parser = subparsers.add_parser(
        "score",
        help="仅在正式延迟闭卷复习后按 0-5 分更新单元；当天即时纠错不用此命令",
    )
    score_parser.add_argument("unit_id")
    score_parser.add_argument("score", type=int)
    score_parser.add_argument("--date", help="指定日期 YYYY-MM-DD")
    score_parser.add_argument(
        "--attempt-id",
        help="本次延迟复习的稳定作答 ID；默认按单元与日期生成",
    )
    score_parser.add_argument("--dry-run", action="store_true", help="预览调度差异，不写复习单元或日志")
    score_parser.set_defaults(func=cmd_score)

    add_parser = subparsers.add_parser("add", help="新增一个 D0 复习单元")
    add_parser.add_argument("--id", required=True)
    add_parser.add_argument("--module", required=True, choices=MODULES)
    add_parser.add_argument("--name", required=True)
    add_parser.add_argument("--type", required=True, choices=["公式", "定理", "题型", "错题", "方法模板"])
    add_parser.add_argument("--date", help="指定首次学习日期 YYYY-MM-DD")
    add_parser.add_argument("--mastery", type=int, default=0)
    add_parser.add_argument("--mistakes", type=int, default=0)
    add_parser.add_argument("--importance", type=int, default=3)
    add_parser.add_argument("--difficulty", default="B中等", choices=["A简单", "B中等", "C困难"])
    add_parser.add_argument("--method", required=True)
    add_parser.add_argument("--remark")
    add_parser.add_argument("--knowledge", help="逗号分隔知识点")
    add_parser.add_argument("--wrong-cause", help="逗号分隔错因类型")
    add_parser.add_argument("--source-id", help="关联错题编号")
    add_parser.set_defaults(func=cmd_add)

    week_parser = subparsers.add_parser("week", help="生成本周回滚报告")
    week_parser.add_argument("--date", help="指定日期 YYYY-MM-DD")
    week_parser.set_defaults(func=cmd_week)

    warmup_parser = subparsers.add_parser(
        "warmup",
        help="只从已正式入库旧题生成学习前队列；精确错因优先，其次知识点补位，不生成新题",
    )
    warmup_parser.add_argument("--date", help="指定日期 YYYY-MM-DD")
    warmup_parser.add_argument("--count", type=int, help="指定题目数量，默认读取学习进度配置")
    warmup_parser.add_argument("--dry-run", action="store_true", help="只预览，不写入生成文件和推荐记录")
    warmup_parser.set_defaults(func=cmd_warmup)

    warmup_candidates_parser = subparsers.add_parser(
        "warmup-candidates",
        help="只读冻结阶段到期 anchor、Day 0-7 排除和正式旧卡候选；语义排序必须由原生 Luna 完成",
    )
    warmup_candidates_parser.add_argument("--date", help="指定日期 YYYY-MM-DD")
    warmup_candidates_parser.add_argument("--count", type=int, help="目标题数，默认读取学习进度配置")
    warmup_candidates_parser.add_argument("--output", help="可选 JSON 输出路径；省略时写标准输出")
    warmup_candidates_parser.set_defaults(func=cmd_warmup_candidates)

    same_item_parser = subparsers.add_parser(
        "same-item-repair",
        help="只读列出做错后 1-2 天的同题修复通道；不占每日五题",
    )
    same_item_parser.add_argument("--date", help="指定日期 YYYY-MM-DD")
    same_item_parser.add_argument("--output", help="可选 JSON 输出路径；省略时写标准输出")
    same_item_parser.set_defaults(func=cmd_same_item_repair)

    warmup_successor_parser = subparsers.add_parser(
        "warmup-successor",
        help="验证原生 Luna 语义计划并 append-only 生成 v5 successor 队列",
    )
    warmup_successor_parser.add_argument("--date", required=True, help="队列日期 YYYY-MM-DD")
    warmup_successor_parser.add_argument("--count", required=True, type=int, help="请求题数")
    warmup_successor_parser.add_argument("--candidate-bundle", required=True, help="warmup-candidates 生成的冻结 JSON")
    warmup_successor_parser.add_argument("--semantic-plan", required=True, help="原生读取计划（v1/v2）与父代理同字节复核 JSON")
    warmup_successor_parser.add_argument("--supersedes-queue-id", default="", help="替换已有队列时必填；当天首次队列省略，不创建占位交付")
    warmup_successor_parser.set_defaults(func=cmd_warmup_successor)

    warmup_score_parser = subparsers.add_parser(
        "score-warmup",
        help="正式入库时处理 v3/v4/v5 队列评分；晨间学习默认返回Capture入口",
    )
    warmup_score_parser.add_argument("queue_id")
    warmup_score_parser.add_argument("queue_item_id")
    warmup_score_parser.add_argument("score", type=int)
    warmup_score_parser.add_argument("--date", help="指定作答日期 YYYY-MM-DD")
    warmup_score_parser.add_argument("--formal-intake", action="store_true", help="仅在用户已要求正式入库时使用；晨间快速保存不得添加")
    warmup_score_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览作答事件，不写复习单元或日志",
    )
    warmup_score_parser.set_defaults(func=cmd_score_warmup)

    sync_parser = subparsers.add_parser("sync-wrongnet", help="从错题知识网络同步错题卡为复习单元")
    sync_parser.add_argument("--limit", type=int, help="限制本次最多新增多少个单元")
    sync_parser.set_defaults(func=cmd_sync_wrongnet)

    upsert_parser = subparsers.add_parser(
        "upsert-wrongnet",
        help="定点维护当前正式 ID；返回错因检查起始日，不表示该日直接重推原题",
    )
    upsert_parser.add_argument("--id", required=True, help="正式错题 ID，例如 GS-653")
    upsert_parser.add_argument("--date", help="固定运行日期 YYYY-MM-DD")
    upsert_parser.add_argument("--dry-run", action="store_true", help="显示准确字段差异但不写文件")
    upsert_parser.add_argument(
        "--expect-recurrence",
        action="store_true",
        help="本轮正式卡声称新增复发；找不到唯一新证据时失败关闭",
    )
    upsert_parser.set_defaults(func=cmd_upsert_wrongnet)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
