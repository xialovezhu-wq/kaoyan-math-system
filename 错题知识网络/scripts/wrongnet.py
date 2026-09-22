#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(os.environ.get("KAOYAN_MATH_PROJECT_ROOT", Path(__file__).resolve().parents[2])).expanduser().resolve()
BASE_DIR = PROJECT_ROOT / "错题知识网络"
CARDS_DIR = BASE_DIR / "错题卡"
OUT_DIR = BASE_DIR / "生成"

PLACEHOLDERS = {"", "待补充", "待确认", "未记录", "无", "未知", "暂无明确错因", "暂无明确个人错因", "none", "null", "-"}
NON_SIGNAL_SUFFIXES = ("待精分",)
MASTERED_STATUSES = {"已掌握", "复做正确", "已做对"}
RELATION_LEVELS = ("强关联", "中关联", "弱关联")
RECOMMENDATION_LEVELS = {"强关联", "中关联"}
MAX_RECOMMENDATIONS_PER_CARD = 8
MAX_WEAK_AUDIT_ROWS = 500

# 这些标签只能作为背景信息，不能单独把两道题连成强边。
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
    "递推数列",
    "单调有界准则",
    "无穷级数",
    "数项级数敛散性判别",
    "正项级数敛散性判别",
}
BROAD_QUESTION_TYPES = {
    "积分型问题",
    "线性代数综合题",
    "矩阵综合题",
    "含参数问题",
    "递推数列极限",
    "错题复做",
    "待补充",
}
GENERIC_ERROR_CAUSES = {
    "知识缺口",
    "定理条件未知",
    "审题遗漏",
    "目标识别断点",
    "题型识别失败",
    "题型识别断点",
    "触发信息遗漏",
    "方法选择错误",
    "方法调取失败",
    "方法论调取失败",
    "方法论调取不稳",
    "方法入口未沉淀",
    "动作链断裂",
    "结构整理断点",
    "条件忽略",
    "条件检查遗漏",
    "分类讨论遗漏",
    "分类讨论不全",
    "收尾验证遗漏",
    "过程跳步",
    "证明结构不完整",
    "概念混淆",
    "概念边界混淆",
    "变量混淆",
    "运算路径不稳",
    "计算失误",
    "计算细节错误",
    "符号错误",
    "定义域错误",
    "参数范围错误",
    "公式记错",
    "公式遗忘",
    "复习记忆不牢",
}
GENERIC_METHODS = {
    "先判型",
    "条件转化",
    "分类讨论",
    "等价变形",
    "换元",
    "作差法",
    "数学归纳法",
    "单调有界",
    "单调有界准则",
    "夹逼",
    "夹逼准则",
    "标准化计算流程",
    "代入验证",
    "特殊值检验",
}
GENERIC_TRAPS = {
    "适用条件",
    "正负号",
    "定义域",
    "参数边界",
    "极限过程",
    "量纲/阶数",
}
TOPIC_CHAIN_NAMES = (
    "递推数列单调有界链",
    "中值定理证明入口链",
    "罗尔辅助函数链",
    "零点定理构造链",
    "相关变化率链",
    "无穷级数判敛链",
)
BROAD_TOPIC_CHAINS = {"递推数列单调有界链", "无穷级数判敛链"}

# 这些文字用于说明证据边界，而不是一道题的数学错因/方法/陷阱。
# 保留在正式卡中用于追溯，但关系评分必须忽略，避免旧批量卡因同一段
# “未记录/待确认”说明被误连成强边。
NON_EVIDENCE_SIGNAL_MARKERS = (
    "未记录",
    "待确认",
    "待补充",
    "暂无明确",
    "个人错因",
    "原始错因",
    "旧批量",
    "旧卡",
    "题图缺",
    "缺题图",
    "解析缺",
    "缺解析",
    "ocr缺",
    "ocr待",
    "视觉证据",
    "不能反推",
    "不可反推",
    "证据不足",
    "仅可确认",
    "仅确认",
)

METHOD_CARD_RE = re.compile(r"^[A-Z]\d{2}-\d{3}$")

# 读卡片时按可确认的关键词补足知识点挂载；只做保守推断，避免替代人工标签。
KNOWLEDGE_INFERENCE_RULES = (
    (
        "等价无穷小",
        (
            "等价无穷小",
            "等价代换",
            "等价替换",
            "等价代入",
            "等价使用",
            "无穷小阶",
            "无穷小的阶",
            "同阶无穷小",
        ),
    ),
    ("洛必达法则", ("洛必达", "l'hospital", "lhospital")),
    ("泰勒公式", ("泰勒", "麦克劳林")),
    ("导数定义", ("导数定义", "差商")),
    ("隐函数求导", ("隐函数求导",)),
    ("参数方程求导", ("参数方程求导",)),
    ("变上限积分", ("变上限积分", "变限积分")),
    ("中值定理", ("中值定理", "拉格朗日中值定理", "柯西中值定理")),
    ("零点定理", ("零点定理", "介值定理")),
    ("幂级数收敛域", ("幂级数收敛域", "收敛域")),
    ("幂级数和函数", ("幂级数和函数", "和函数")),
    ("函数展开成幂级数", ("展开成幂级数",)),
    ("数项级数敛散性判别", ("数项级数", "级数敛散")),
)


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break

    if end is None:
        return {}, text

    front = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :])
    return parse_yaml_like(front), body


def parse_yaml_like(front: str) -> dict[str, Any]:
    """Parse the small YAML subset used by the wrong-question cards."""
    meta: dict[str, Any] = {}
    current_key: str | None = None
    current_nested: str | None = None
    lines = front.splitlines()

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
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        if (
            raw_line.startswith("  - ")
            and current_key is not None
            and current_nested is not None
            and isinstance(meta.get(current_key), dict)
            and isinstance(meta[current_key].get(current_nested), list)
        ):
            meta[current_key][current_nested].append(
                parse_scalar(raw_line[4:].strip())
            )
            continue

        if raw_line.startswith("- ") or raw_line.startswith("  - "):
            if current_key is None:
                continue
            if not isinstance(meta.get(current_key), list):
                meta[current_key] = []
            item_offset = 2 if raw_line.startswith("- ") else 4
            meta[current_key].append(parse_scalar(raw_line[item_offset:].strip()))
            continue

        if raw_line.startswith("    - ") and current_key is not None and current_nested is not None:
            if not isinstance(meta.get(current_key), dict):
                meta[current_key] = {}
            nested = meta[current_key].setdefault(current_nested, [])
            if isinstance(nested, list):
                nested.append(parse_scalar(raw_line[6:].strip()))
            continue

        if raw_line.startswith("  ") and ":" in raw_line:
            if current_key is None:
                continue
            if not isinstance(meta.get(current_key), dict):
                meta[current_key] = {}
            key, value = raw_line.strip().split(":", 1)
            key = key.strip()
            value = value.strip()
            current_nested = key
            if is_block_scalar(value):
                block_value, index = collect_block(index, line_indent(raw_line) + 2, value.startswith(">"))
                meta[current_key][key] = block_value
            else:
                meta[current_key][key] = parse_scalar(value) if value else []
            continue

        if ":" in raw_line:
            key, value = raw_line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if is_block_scalar(value):
                block_value, index = collect_block(index, line_indent(raw_line) + 2, value.startswith(">"))
                meta[key] = block_value
            else:
                meta[key] = parse_scalar(value) if value else []
            current_key = key
            current_nested = None

    return meta


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"[]", "[ ]"}:
        return []
    if (
        len(value) >= 2
        and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'"))
    ):
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError:
            return value
    if re.fullmatch(r"-?\d+\.\d+", value):
        try:
            return float(value)
        except ValueError:
            return value
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(value).strip()]


def clean_items(value: Any) -> list[str]:
    return [item for item in as_list(value) if item.lower() not in PLACEHOLDERS]


def signal_items(value: Any) -> list[str]:
    return [item for item in clean_items(value) if not item.endswith(NON_SIGNAL_SUFFIXES)]


@lru_cache(maxsize=1)
def _normalized_non_evidence_markers() -> tuple[str, ...]:
    return tuple(normalize_text(marker) for marker in NON_EVIDENCE_SIGNAL_MARKERS)


@lru_cache(maxsize=8192)
def _evidence_items_cached(items: tuple[str, ...]) -> tuple[str, ...]:
    kept: list[str] = []
    normalized_markers = _normalized_non_evidence_markers()
    for item in items:
        normalized = normalize_text(item)
        if any(marker in normalized for marker in normalized_markers):
            continue
        kept.append(item)
    return tuple(kept)


def evidence_items(value: Any) -> list[str]:
    """返回可参与关系评分的结构化信号，排除证据边界说明。"""

    return list(_evidence_items_cached(tuple(signal_items(value))))


def signal_set(value: Any) -> set[str]:
    return set(signal_items(value))


def specific_items(value: Any, broad: set[str]) -> list[str]:
    return [item for item in signal_items(value) if item not in broad]


def broad_items(value: Any, broad: set[str]) -> list[str]:
    return [item for item in signal_items(value) if item in broad]


def specific_evidence_items(value: Any, broad: set[str]) -> list[str]:
    return [item for item in evidence_items(value) if item not in broad]


def broad_evidence_items(value: Any, broad: set[str]) -> list[str]:
    return [item for item in evidence_items(value) if item in broad]


def common_items(left: Any, right: Any, *, exclude: set[str] | None = None) -> list[str]:
    exclude = exclude or set()
    common = set(signal_items(left)) & set(signal_items(right))
    return sorted(item for item in common if item not in exclude)


def common_specific(left: Any, right: Any, broad: set[str]) -> list[str]:
    return common_items(left, right, exclude=broad)


def common_evidence(left: Any, right: Any, *, exclude: set[str] | None = None) -> list[str]:
    exclude = exclude or set()
    common = set(evidence_items(left)) & set(evidence_items(right))
    return sorted(item for item in common if item not in exclude)


def append_unique_items(value: Any, additions: list[str]) -> list[str]:
    items = clean_items(value)
    seen = set(items)
    for item in additions:
        if item and item not in seen:
            items.append(item)
            seen.add(item)
    return items


def knowledge_inference_text(meta: dict[str, Any], body: str) -> str:
    parts: list[str] = []
    for key in (
        "title",
        "chapter",
        "question_type",
        "wrong_point",
        "answer",
    ):
        parts.append(str(meta.get(key, "")))
    for key in ("knowledge", "methods", "traps", "keywords"):
        parts.extend(clean_items(meta.get(key)))
    parts.append(body)
    return "\n".join(parts)


def infer_knowledge(meta: dict[str, Any], body: str) -> list[str]:
    text = knowledge_inference_text(meta, body)
    normalized = normalize_text(text)
    inferred: list[str] = []
    existing = set(clean_items(meta.get("knowledge")))
    for knowledge, patterns in KNOWLEDGE_INFERENCE_RULES:
        if knowledge in existing:
            continue
        for pattern in patterns:
            if pattern.lower() in normalized or pattern in text:
                inferred.append(knowledge)
                break
    return inferred


def enrich_meta(meta: dict[str, Any], body: str) -> dict[str, Any]:
    inferred = infer_knowledge(meta, body)
    if inferred:
        # 推断结果只能作为逐题审计候选，不能静默混入正式 knowledge 后参与
        # 强/中关系评分。正式知识点必须由错题卡本身或正式审核写入。
        meta["inferred_knowledge_candidates"] = inferred
    return meta


def related_ids(meta: dict[str, Any]) -> set[str]:
    return set(clean_items(meta.get("related")))


def is_declared_related(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return b["id"] in related_ids(a["meta"]) or a["id"] in related_ids(b["meta"])


def is_manual_related(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """兼容旧调用名；当前 related 仅表示已声明关系，不再自动等同人工确认。"""

    return is_declared_related(a, b)


def method_gap_signals(meta: dict[str, Any]) -> tuple[list[str], list[str]]:
    method_gap = meta.get("method_gap")
    if not isinstance(method_gap, dict) or method_gap.get("enabled") is not True:
        return [], []
    method_id = str(method_gap.get("related_method_card_id") or "").strip()
    method_cards = [method_id] if METHOD_CARD_RE.fullmatch(method_id) else []
    action_gap = str(method_gap.get("action_gap_type") or "").strip()
    action_gaps = [action_gap] if re.fullmatch(r"(?:A-[A-Z]+|B\d-[A-Z]+)", action_gap) else []
    return method_cards, action_gaps


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"\s+", "", text)
    return text


def compact_text(text: str, limit: int = 140) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def char_ngrams(text: str) -> Counter[str]:
    text = normalize_text(text)
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text)
    grams: Counter[str] = Counter()
    if not text:
        return grams
    for n in (2, 3):
        if len(text) < n:
            continue
        for idx in range(0, len(text) - n + 1):
            grams[text[idx : idx + n]] += 1
    for token in re.findall(r"[a-zA-Z0-9_]+", text):
        if len(token) >= 2:
            grams[f"tok:{token}"] += 2
    return grams


def cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(count * b.get(key, 0) for key, count in a.items())
    norm_a = math.sqrt(sum(count * count for count in a.values()))
    norm_b = math.sqrt(sum(count * count for count in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def jaccard(a: list[str], b: list[str]) -> float:
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def card_text(card: dict[str, Any]) -> str:
    meta = card["meta"]
    parts: list[str] = []
    for key in (
        "title",
        "subject",
        "chapter",
        "question_type",
        "knowledge",
        "methods",
        "traps",
        "answer",
    ):
        parts.extend(signal_items(meta.get(key)))
    parts.extend(signal_items(meta.get("wrong_point")))
    parts.extend(signal_items(meta.get("error_causes")))
    return "\n".join(parts)


def topic_chain_text(card: dict[str, Any]) -> str:
    meta = card["meta"]
    parts: list[str] = [
        str(meta.get("title", "")),
        str(meta.get("chapter", "")),
        str(meta.get("answer", "")),
        str(card.get("body", ""))[:1200],
    ]
    for key in ("question_type", "knowledge", "methods", "traps", "wrong_point", "error_causes"):
        parts.extend(signal_items(meta.get(key)))
    return normalize_text(" ".join(parts))


def topic_chains(card: dict[str, Any]) -> list[str]:
    meta = card["meta"]
    text = topic_chain_text(card)
    body_excerpt = str(card.get("body", "")).split("\n## 标签", 1)[0]
    body_excerpt = body_excerpt.split("\n## 必要提示", 1)[0]
    literal_parts: list[str] = [
        str(meta.get("title", "")),
        str(meta.get("chapter", "")),
        str(meta.get("answer", "")),
        body_excerpt[:1200],
    ]
    for key in ("wrong_point", "traps"):
        literal_parts.extend(signal_items(meta.get(key)))
    literal_text = normalize_text(" ".join(literal_parts))
    chains: list[str] = []
    qtypes = signal_set(meta.get("question_type"))
    knowledge = signal_set(meta.get("knowledge"))
    methods = signal_set(meta.get("methods"))
    traps = signal_set(meta.get("traps"))
    chapter = normalize_text(str(meta.get("chapter", "")))

    recurrence_context = (
        "递推数列极限" in qtypes
        or "递推数列" in knowledge
        or "数列极限" in chapter
        or "递推数列" in text
        or "递推式" in text
        or "递推关系" in text
    )
    recurrence_shape = (
        "递推" in literal_text
        or "x_n" in literal_text
        or "x_{n" in literal_text
        or "x{n" in literal_text
        or "xn" in literal_text
        or "a_n" in literal_text
        or "a_{n" in literal_text
        or "a{n" in literal_text
    )
    recurrence_method = bool(
        {"单调有界", "单调有界准则", "数学归纳法", "构造上界", "构造下界"}
        & (methods | traps | knowledge)
    ) or "区间不变" in text
    if recurrence_context and recurrence_shape and recurrence_method:
        chains.append("递推数列单调有界链")

    mvt_context = (
        "中值定理证明/估计" in qtypes
        or "中值定理" in knowledge
        or "拉格朗日中值定理" in knowledge
        or "柯西中值定理" in knowledge
        or "中值定理证明" in text
    )
    mvt_entry = (
        "拉格朗日中值定理" in literal_text
        or "柯西中值定理" in literal_text
        or "中值定理证明" in literal_text
        or "割线斜率" in literal_text
        or "区间拆分" in literal_text
        or (
            "中值定理" in literal_text
            and (
                "证明结构不完整" in literal_text
                or "题型识别失败" in literal_text
                or "辅助函数" in literal_text
            )
        )
    )
    if mvt_context and mvt_entry:
        chains.append("中值定理证明入口链")

    rolle_context = (
        "罗尔定理辅助函数构造" in qtypes
        or "罗尔定理" in knowledge
        or "罗尔定理" in methods
        or "积分因子" in knowledge
        or "积分因子" in methods
        or "罗尔" in text
    )
    rolle_entry = (
        "辅助函数" in text
        or "端点条件" in text
        or "积分因子" in text
        or "反向构造" in text
    )
    if rolle_context and rolle_entry:
        chains.append("罗尔辅助函数链")

    zero_context = (
        "零点定理" in qtypes
        or "零点定理" in knowledge
        or "零点定理" in methods
        or "零点" in text
    )
    zero_entry = "构造" in text or "端点" in text or "证明结构" in text or "条件转化" in text
    if zero_context and zero_entry:
        chains.append("零点定理构造链")

    if (
        "相关变化率" in qtypes
        or "相关变化率" in knowledge
        or "相关变化率" in text
        or "对时间求导" in text
    ):
        chains.append("相关变化率链")

    series_context = bool(
        {
            "无穷级数",
            "数项级数敛散性判别",
            "正项级数敛散性判别",
            "任意项级数",
            "交错级数",
            "幂级数",
        }
        & knowledge
    ) or "无穷级数" in chapter or any("级数" in item for item in qtypes)
    series_entry = bool(
        {
            "级数收敛必要条件",
            "正项级数比较判别法",
            "极限比较判别法",
            "比值判别法",
            "根值判别法",
            "莱布尼茨判别法",
            "积分判别法",
            "通项趋零",
            "比较判别法",
        }
        & (knowledge | methods | traps)
    ) or any(
        marker in literal_text
        for marker in ("通项趋零", "莱布尼茨判别", "根值判别", "比值判别", "比较判别")
    )
    if series_context and series_entry:
        chains.append("无穷级数判敛链")

    return [name for name in TOPIC_CHAIN_NAMES if name in chains]


def read_cards() -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for path in sorted(CARDS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta, body = split_front_matter(text)
        if not meta:
            continue
        qid = str(meta.get("id") or path.stem).strip()
        if not qid:
            continue
        meta["id"] = qid
        if not meta.get("title"):
            meta["title"] = first_heading(body) or path.stem
        meta = enrich_meta(meta, body)
        cards.append(
            {
                "id": qid,
                "path": path,
                "relpath": path.relative_to(BASE_DIR).as_posix(),
                "meta": meta,
                "body": body,
                "grams": char_ngrams(card_text({"meta": meta, "body": body})),
                "topic_chains": [],
            }
        )
        cards[-1]["topic_chains"] = topic_chains(cards[-1])
    return cards


def first_heading(body: str) -> str:
    for line in body.splitlines():
        match = re.match(r"^#\s+(.+)$", line.strip())
        if match:
            return match.group(1).strip()
    return ""


def similarity(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, list[str]]:
    ma = a["meta"]
    mb = b["meta"]

    wrong_point = jaccard(evidence_items(ma.get("wrong_point")), evidence_items(mb.get("wrong_point")))
    fine_knowledge = jaccard(
        specific_items(ma.get("knowledge"), BROAD_KNOWLEDGE),
        specific_items(mb.get("knowledge"), BROAD_KNOWLEDGE),
    )
    broad_knowledge = jaccard(
        broad_items(ma.get("knowledge"), BROAD_KNOWLEDGE),
        broad_items(mb.get("knowledge"), BROAD_KNOWLEDGE),
    )
    specific_errors = jaccard(
        specific_evidence_items(ma.get("error_causes"), GENERIC_ERROR_CAUSES),
        specific_evidence_items(mb.get("error_causes"), GENERIC_ERROR_CAUSES),
    )
    generic_errors = jaccard(
        broad_evidence_items(ma.get("error_causes"), GENERIC_ERROR_CAUSES),
        broad_evidence_items(mb.get("error_causes"), GENERIC_ERROR_CAUSES),
    )
    specific_methods = jaccard(
        specific_evidence_items(ma.get("methods"), GENERIC_METHODS),
        specific_evidence_items(mb.get("methods"), GENERIC_METHODS),
    )
    generic_methods = jaccard(
        broad_evidence_items(ma.get("methods"), GENERIC_METHODS),
        broad_evidence_items(mb.get("methods"), GENERIC_METHODS),
    )
    traps = jaccard(
        specific_evidence_items(ma.get("traps"), GENERIC_TRAPS),
        specific_evidence_items(mb.get("traps"), GENERIC_TRAPS),
    )
    specific_question_type = jaccard(
        specific_evidence_items(ma.get("question_type"), BROAD_QUESTION_TYPES),
        specific_evidence_items(mb.get("question_type"), BROAD_QUESTION_TYPES),
    )
    broad_question_type = jaccard(
        broad_evidence_items(ma.get("question_type"), BROAD_QUESTION_TYPES),
        broad_evidence_items(mb.get("question_type"), BROAD_QUESTION_TYPES),
    )
    method_cards_a, action_gaps_a = method_gap_signals(ma)
    method_cards_b, action_gaps_b = method_gap_signals(mb)
    method_card = jaccard(method_cards_a, method_cards_b)
    action_gap = jaccard(action_gaps_a, action_gaps_b)
    text = cosine(a["grams"], b["grams"])
    same_subject = 1.0 if str(ma.get("subject", "")) == str(mb.get("subject", "")) and ma.get("subject") else 0.0
    same_chapter = 1.0 if str(ma.get("chapter", "")) == str(mb.get("chapter", "")) and ma.get("chapter") else 0.0

    # 当前网络优先按知识点召回；具体错点只作增强信号，不作为第一分类轴。
    score = (
        0.05 * wrong_point
        + 0.32 * fine_knowledge
        + 0.03 * broad_knowledge
        + 0.10 * specific_errors
        + 0.02 * generic_errors
        + 0.14 * specific_methods
        + 0.02 * generic_methods
        + 0.05 * traps
        + 0.11 * specific_question_type
        + 0.01 * broad_question_type
        + 0.06 * method_card
        + 0.02 * action_gap
        + 0.03 * text
        + 0.02 * same_subject
    )
    if same_chapter and fine_knowledge > 0:
        score += 0.02
    score = max(0.0, min(score, 1.0))

    reasons: list[str] = []
    common_topics = sorted(set(a.get("topic_chains", [])) & set(b.get("topic_chains", [])))
    if common_topics:
        reasons.append(f"共同专题链：{', '.join(common_topics)}")
    if is_declared_related(a, b):
        reasons.append("已声明关系：related 字段（仍需独立证据定级）")
    reasons.extend(common_reason("共同具体错点", evidence_items(ma.get("wrong_point")), evidence_items(mb.get("wrong_point"))))
    reasons.extend(common_reason("共同细知识点", specific_items(ma.get("knowledge"), BROAD_KNOWLEDGE), specific_items(mb.get("knowledge"), BROAD_KNOWLEDGE)))
    reasons.extend(common_reason("共同粗知识点", broad_items(ma.get("knowledge"), BROAD_KNOWLEDGE), broad_items(mb.get("knowledge"), BROAD_KNOWLEDGE)))
    reasons.extend(
        common_reason(
            "共同错因",
            specific_evidence_items(ma.get("error_causes"), GENERIC_ERROR_CAUSES),
            specific_evidence_items(mb.get("error_causes"), GENERIC_ERROR_CAUSES),
        )
    )
    reasons.extend(
        common_reason(
            "共同粗错因",
            broad_evidence_items(ma.get("error_causes"), GENERIC_ERROR_CAUSES),
            broad_evidence_items(mb.get("error_causes"), GENERIC_ERROR_CAUSES),
        )
    )
    reasons.extend(
        common_reason(
            "共同方法",
            specific_evidence_items(ma.get("methods"), GENERIC_METHODS),
            specific_evidence_items(mb.get("methods"), GENERIC_METHODS),
        )
    )
    reasons.extend(
        common_reason(
            "共同粗方法",
            broad_evidence_items(ma.get("methods"), GENERIC_METHODS),
            broad_evidence_items(mb.get("methods"), GENERIC_METHODS),
        )
    )
    reasons.extend(
        common_reason(
            "共同陷阱",
            specific_evidence_items(ma.get("traps"), GENERIC_TRAPS),
            specific_evidence_items(mb.get("traps"), GENERIC_TRAPS),
        )
    )
    reasons.extend(
        common_reason(
            "共同粗陷阱",
            broad_evidence_items(ma.get("traps"), GENERIC_TRAPS),
            broad_evidence_items(mb.get("traps"), GENERIC_TRAPS),
        )
    )
    reasons.extend(
        common_reason(
            "共同题型",
            specific_evidence_items(ma.get("question_type"), BROAD_QUESTION_TYPES),
            specific_evidence_items(mb.get("question_type"), BROAD_QUESTION_TYPES),
        )
    )
    reasons.extend(
        common_reason(
            "共同粗题型",
            broad_evidence_items(ma.get("question_type"), BROAD_QUESTION_TYPES),
            broad_evidence_items(mb.get("question_type"), BROAD_QUESTION_TYPES),
        )
    )
    reasons.extend(common_reason("共同方法卡", method_cards_a, method_cards_b))
    reasons.extend(common_reason("共同动作断点", action_gaps_a, action_gaps_b))
    if same_subject:
        reasons.append(f"同科目：{ma.get('subject')}")
    if same_chapter and (fine_knowledge > 0 or broad_knowledge > 0):
        reasons.append(f"同章节：{ma.get('chapter')}")
    if text >= 0.42:
        reasons.append("题干/解法文本相似")

    return round(score, 4), reasons


def relation_level(a: dict[str, Any], b: dict[str, Any], score: float, reasons: list[str]) -> tuple[str, str, float]:
    ma = a["meta"]
    mb = b["meta"]

    common_topic = sorted(set(a.get("topic_chains", [])) & set(b.get("topic_chains", [])))
    fine_knowledge = common_specific(ma.get("knowledge"), mb.get("knowledge"), BROAD_KNOWLEDGE)
    broad_knowledge = sorted(set(broad_items(ma.get("knowledge"), BROAD_KNOWLEDGE)) & set(broad_items(mb.get("knowledge"), BROAD_KNOWLEDGE)))
    common_errors = common_evidence(ma.get("error_causes"), mb.get("error_causes"))
    specific_errors = [item for item in common_errors if item not in GENERIC_ERROR_CAUSES]
    common_methods = common_evidence(ma.get("methods"), mb.get("methods"))
    specific_methods = [item for item in common_methods if item not in GENERIC_METHODS]
    common_types = common_evidence(ma.get("question_type"), mb.get("question_type"))
    specific_types = [item for item in common_types if item not in BROAD_QUESTION_TYPES]
    common_traps = common_evidence(ma.get("traps"), mb.get("traps"))
    specific_traps = [item for item in common_traps if item not in GENERIC_TRAPS]
    method_cards_a, action_gaps_a = method_gap_signals(ma)
    method_cards_b, action_gaps_b = method_gap_signals(mb)
    common_method_cards = sorted(set(method_cards_a) & set(method_cards_b))
    common_action_gaps = sorted(set(action_gaps_a) & set(action_gaps_b))
    has_text = any(reason.startswith("题干/解法文本相似") for reason in reasons)
    same_subject = bool(ma.get("subject") and ma.get("subject") == mb.get("subject"))
    declared = is_declared_related(a, b)
    specific_topics = [item for item in common_topic if item not in BROAD_TOPIC_CHAINS]

    level = "弱关联"
    source = "noisy"
    adjusted = score

    # 强边至少需要两个独立的结构轴；related 本身不再作为自证证据。
    if same_subject and specific_topics and fine_knowledge and (
        specific_methods or specific_errors or specific_types or specific_traps or common_method_cards
    ):
        level, source, adjusted = "强关联", "topic_chain", min(0.88, max(score + 0.20, 0.52))
    elif same_subject and specific_topics and (specific_methods or common_method_cards) and (
        fine_knowledge or specific_errors or specific_types
    ):
        level, source, adjusted = "强关联", "topic_chain", min(0.86, max(score + 0.18, 0.50))
    elif same_subject and specific_types and (specific_methods or common_method_cards or fine_knowledge):
        level, source, adjusted = "强关联", "type_template", min(0.84, max(score + 0.18, 0.48))
    elif same_subject and fine_knowledge and (
        specific_methods or specific_errors or specific_types or specific_traps or common_method_cards
    ):
        level, source, adjusted = "强关联", "knowledge_supported", min(0.82, max(score + 0.16, 0.46))
    elif fine_knowledge and (specific_methods or specific_errors or specific_types or common_method_cards):
        level, source, adjusted = "中关联", "fine_knowledge_combo", max(score, 0.36)
    elif fine_knowledge and has_text:
        level, source, adjusted = "中关联", "knowledge_text", max(score, 0.34)
    elif fine_knowledge:
        level, source, adjusted = "中关联", "knowledge_only", max(score, 0.30)
    elif common_method_cards:
        level, source, adjusted = "中关联", "method_card_only", max(score, 0.34)
    elif common_topic and (specific_methods or specific_types or specific_errors):
        level, source, adjusted = "中关联", "topic_chain_backup", max(score, 0.32)
    elif specific_types and specific_methods:
        level, source, adjusted = "中关联", "type_method", max(score, 0.34)
    elif specific_methods and (specific_errors or specific_traps):
        level, source, adjusted = "中关联", "method_error_or_trap", max(score, 0.32)
    elif score >= 0.40 and len(
        [x for x in (fine_knowledge, specific_errors, specific_methods, specific_types, specific_traps, common_method_cards) if x]
    ) >= 2:
        level, source, adjusted = "中关联", "multi_signal", score
    elif broad_knowledge or common_errors or common_methods or common_types or common_traps or common_action_gaps or has_text or common_topic:
        level, source, adjusted = "弱关联", "weak_audit", score

    if declared:
        if level == "强关联":
            source = f"declared_supported:{source}"
        elif level == "中关联":
            source = f"declared_medium:{source}"
        else:
            source = "declared_unverified"
            adjusted = max(adjusted, 0.10)
    return level, source, round(adjusted, 4)


def common_reason(label: str, left: Any, right: Any) -> list[str]:
    common = sorted(set(signal_items(left)) & set(signal_items(right)))
    if not common:
        return []
    return [f"{label}：{', '.join(common)}"]


def compute_pairs(cards: list[dict[str, Any]], threshold: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    recommendation_pairs: list[dict[str, Any]] = []
    weak_pairs: list[dict[str, Any]] = []
    for idx, left in enumerate(cards):
        for right in cards[idx + 1 :]:
            score, reasons = similarity(left, right)
            level, source, adjusted_score = relation_level(left, right, score, reasons)
            if adjusted_score < threshold and not source.startswith("declared_") and source != "topic_chain":
                continue
            if not has_substantive_relation(reasons):
                continue
            pair = {
                "a": left["id"],
                "b": right["id"],
                "score": round(adjusted_score, 4),
                "raw_score": score,
                "level": level,
                "source": source,
                "reasons": reasons,
            }
            if level in RECOMMENDATION_LEVELS:
                recommendation_pairs.append(pair)
            else:
                weak_pairs.append(pair)

    recommendation_pairs = cap_recommendations(recommendation_pairs, MAX_RECOMMENDATIONS_PER_CARD)
    return (
        sorted(recommendation_pairs, key=pair_sort_key),
        sorted(weak_pairs, key=pair_sort_key)[:MAX_WEAK_AUDIT_ROWS],
    )


def pair_sort_key(item: dict[str, Any]) -> tuple[int, float, str, str]:
    level_rank = {"强关联": 0, "中关联": 1, "弱关联": 2}.get(str(item.get("level")), 9)
    return (level_rank, -float(item.get("score", 0.0)), str(item.get("a")), str(item.get("b")))


def cap_recommendations(pairs: list[dict[str, Any]], max_per_card: int) -> list[dict[str, Any]]:
    if max_per_card <= 0:
        return []
    ranked = sorted(pairs, key=pair_sort_key)
    incident: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pair in ranked:
        incident[pair["a"]].append(pair)
        incident[pair["b"]].append(pair)

    degree: Counter[str] = Counter()
    selected: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str]] = set()

    def pair_key(pair: dict[str, Any]) -> tuple[str, str]:
        return tuple(sorted((str(pair["a"]), str(pair["b"]))))

    def try_select(pair: dict[str, Any]) -> bool:
        key = pair_key(pair)
        if key in selected_keys:
            return True
        if degree[pair["a"]] >= max_per_card or degree[pair["b"]] >= max_per_card:
            return False
        selected_keys.add(key)
        selected.append(pair)
        degree[pair["a"]] += 1
        degree[pair["b"]] += 1
        return True

    # 先照顾候选稀少的卡，避免高连接 hub 在全局贪心阶段先占满邻居槽位。
    for card_id in sorted(incident, key=lambda item: (len(incident[item]), item)):
        if degree[card_id] > 0:
            continue
        for pair in incident[card_id]:
            if try_select(pair):
                break

    for pair in ranked:
        if degree[pair["a"]] < max_per_card and degree[pair["b"]] < max_per_card:
            try_select(pair)
    return selected


def is_mastered(card: dict[str, Any]) -> bool:
    return str(card["meta"].get("status", "")).strip() in MASTERED_STATUSES


def review_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [card for card in cards if not is_mastered(card)]


def has_substantive_relation(reasons: list[str]) -> bool:
    prefixes = (
        "共同专题链",
        "已声明关系",
        "共同具体错点",
        "共同细知识点",
        "共同粗知识点",
        "共同错因",
        "共同方法",
        "共同陷阱",
        "共同题型",
        "共同方法卡",
        "共同动作断点",
        "题干/解法文本相似",
    )
    return any(reason.startswith(prefixes) for reason in reasons)


def review_next(meta: dict[str, Any]) -> str:
    review = meta.get("review")
    if isinstance(review, dict):
        return str(review.get("next", ""))
    return ""


def mistake_count(meta: dict[str, Any]) -> str:
    value = meta.get("mistake_count")
    if value not in (None, ""):
        return str(value)
    history = clean_items(meta.get("wrong_history"))
    return str(len(history)) if history else ""


def wrong_dates(meta: dict[str, Any]) -> list[str]:
    dates: list[str] = []
    for item in clean_items(meta.get("wrong_history")):
        for raw in re.findall(r"20\d{2}-\d{2}-\d{2}", item):
            if raw not in dates:
                dates.append(raw)
    return dates


def write_index(cards: list[dict[str, Any]]) -> None:
    lines = [
        "# 错题索引",
        "",
        f"更新时间：{date.today().isoformat()}",
        "",
        f"错题数量：{len(cards)}",
        "",
        "| 编号 | 标题 | 科目 | 章节 | 题型 | 具体错点 | 知识点 | 错因 | 优先级 | 错次 | 错题日期 | 批次 | 状态 | 错因检查起始日 | 文件 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for card in sorted(cards, key=lambda item: item["id"]):
        meta = card["meta"]
        rel = Path("..") / card["relpath"]
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(card["id"]),
                    md_cell(str(meta.get("title", ""))),
                    md_cell(str(meta.get("subject", ""))),
                    md_cell(str(meta.get("chapter", ""))),
                    md_cell(", ".join(clean_items(meta.get("question_type")))),
                    md_cell(", ".join(clean_items(meta.get("wrong_point")))),
                    md_cell(", ".join(clean_items(meta.get("knowledge")))),
                    md_cell(", ".join(clean_items(meta.get("error_causes")))),
                    md_cell(str(meta.get("priority", ""))),
                    md_cell(mistake_count(meta)),
                    md_cell(", ".join(wrong_dates(meta))),
                    md_cell(str(meta.get("import_batch", ""))),
                    md_cell(str(meta.get("status", ""))),
                    md_cell(review_next(meta)),
                    f"[打开]({rel.as_posix()})",
                ]
            )
            + " |"
        )
    (OUT_DIR / "错题索引.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_similarities(cards: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> None:
    by_id = {card["id"]: card for card in cards}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pair in pairs:
        grouped[pair["a"]].append(pair)
        grouped[pair["b"]].append(
            {
                "a": pair["b"],
                "b": pair["a"],
                "score": pair["score"],
                "raw_score": pair.get("raw_score", pair["score"]),
                "level": pair.get("level", ""),
                "source": pair.get("source", ""),
                "reasons": pair["reasons"],
            }
        )

    lines = [
        "# 相似题清单",
        "",
        f"更新时间：{date.today().isoformat()}",
        "",
    ]
    if not pairs:
        lines.append("当前没有达到阈值的相似题。")
    for card in sorted(cards, key=lambda item: item["id"]):
        related = sorted(grouped.get(card["id"], []), key=pair_sort_key)
        if not related:
            continue
        meta = card["meta"]
        lines.extend(["", f"## {card['id']} {meta.get('title', '')}", ""])
        for level in ("强关联", "中关联"):
            bucket = [item for item in related if item.get("level") == level]
            if not bucket:
                continue
            lines.append(f"### {level}")
            for item in bucket[:MAX_RECOMMENDATIONS_PER_CARD]:
                other = by_id[item["b"]]
                other_meta = other["meta"]
                rel = Path("..") / other["relpath"]
                reason = "；".join(item["reasons"]) if item["reasons"] else "文本或标签相似"
                lines.append(
                    f"- `{item['score']:.2f}` [{other['id']} {other_meta.get('title', '')}]({rel.as_posix()})：{reason}"
                )
            lines.append("")
    (OUT_DIR / "相似题清单.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_strong_relations(cards: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> None:
    by_id = {card["id"]: card for card in cards}
    lines = [
        "# 强关联清单",
        "",
        f"更新时间：{date.today().isoformat()}",
        "",
        "用途：只保留有独立知识/方法/题型证据、可直接用于复做推荐的强边；`related` 仅表示已声明关系，不能自行把关系抬成强边。",
        "",
    ]
    strong = [pair for pair in pairs if pair.get("level") == "强关联"]
    if not strong:
        lines.append("暂无强关联。")
    for pair in sorted(strong, key=pair_sort_key):
        left = by_id.get(pair["a"])
        right = by_id.get(pair["b"])
        if not left or not right:
            continue
        reason = "；".join(pair["reasons"]) if pair["reasons"] else "人工或规则确认"
        left_rel = Path("..") / left["relpath"]
        right_rel = Path("..") / right["relpath"]
        lines.append(
            f"- `{pair['score']:.2f}` [{pair['a']} {left['meta'].get('title', '')}]({left_rel.as_posix()}) ↔ "
            f"[{pair['b']} {right['meta'].get('title', '')}]({right_rel.as_posix()})：{reason}"
        )
    (OUT_DIR / "强关联清单.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_weak_audit(cards: list[dict[str, Any]], weak_pairs: list[dict[str, Any]]) -> None:
    by_id = {card["id"]: card for card in cards}
    lines = [
        "# 弱边审计清单",
        "",
        f"更新时间：{date.today().isoformat()}",
        "",
        "用途：这些关系只作为备用召回或后续标签清洗依据，不进入主推荐。",
        "",
    ]
    if not weak_pairs:
        lines.append("暂无弱边样本。")
    for pair in sorted(weak_pairs, key=pair_sort_key):
        left = by_id.get(pair["a"])
        right = by_id.get(pair["b"])
        if not left or not right:
            continue
        reason = "；".join(pair["reasons"]) if pair["reasons"] else "弱文本或标签相似"
        left_rel = Path("..") / left["relpath"]
        right_rel = Path("..") / right["relpath"]
        lines.append(
            f"- `{pair['score']:.2f}` [{pair['a']} {left['meta'].get('title', '')}]({left_rel.as_posix()}) ↔ "
            f"[{pair['b']} {right['meta'].get('title', '')}]({right_rel.as_posix()})：{reason}"
        )
    (OUT_DIR / "弱边审计清单.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_topic_chains(cards: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> None:
    by_chain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_id = {card["id"]: card for card in cards}
    for card in review_cards(cards):
        for chain in card.get("topic_chains", []):
            by_chain[chain].append(card)

    lines = [
        "# 专题链关联清单",
        "",
        f"更新时间：{date.today().isoformat()}",
        "",
        "用途：把同一方法模板或证明入口的错题先聚成链，再参与强关联推荐。",
        "",
    ]
    for chain in TOPIC_CHAIN_NAMES:
        items = sorted(by_chain.get(chain, []), key=lambda card: card["id"])
        lines.extend([f"## {chain}（{len(items)}）", ""])
        if not items:
            lines.append("- 暂无挂载错题。")
            lines.append("")
            continue
        for card in items[:80]:
            meta = card["meta"]
            rel = Path("..") / card["relpath"]
            wrong = compact_text(", ".join(clean_items(meta.get("wrong_point"))) or "待补充", 90)
            lines.append(f"- [{card['id']} {meta.get('title', '')}]({rel.as_posix()})：{wrong}")
        chain_pairs = [
            pair
            for pair in pairs
            if pair.get("level") == "强关联"
            and by_id.get(pair["a"])
            and by_id.get(pair["b"])
            and chain in by_id[pair["a"]].get("topic_chains", [])
            and chain in by_id[pair["b"]].get("topic_chains", [])
        ]
        if chain_pairs:
            lines.extend(["", "### 链内强边"])
            for pair in sorted(chain_pairs, key=pair_sort_key)[:30]:
                reason = "；".join(pair["reasons"]) if pair["reasons"] else "共同专题链"
                lines.append(f"- `{pair['score']:.2f}` {pair['a']} ↔ {pair['b']}：{reason}")
        lines.append("")
    (OUT_DIR / "专题链关联清单.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_overview(cards: list[dict[str, Any]], pairs: list[dict[str, Any]], weak_pairs: list[dict[str, Any]]) -> None:
    def count_field(field: str) -> Counter[str]:
        counter: Counter[str] = Counter()
        for card in cards:
            counter.update(clean_items(card["meta"].get(field)))
        return counter

    def count_scalar(field: str) -> Counter[str]:
        counter: Counter[str] = Counter()
        for card in cards:
            value = str(card["meta"].get(field, "")).strip()
            if value and value.lower() not in PLACEHOLDERS:
                counter[value] += 1
        return counter

    def top_lines(counter: Counter[str], empty: str) -> list[str]:
        if not counter:
            return [f"- {empty}"]
        return [f"- {name}：{count}" for name, count in counter.most_common(12)]

    level_counts = Counter(pair.get("level", "未分级") for pair in pairs + weak_pairs)
    source_counts = Counter(pair.get("source", "unknown") for pair in pairs + weak_pairs)
    active_cards = review_cards(cards)
    active_ids = {card["id"] for card in active_cards}
    connected_ids = {pair["a"] for pair in pairs} | {pair["b"] for pair in pairs}
    isolated_active = sorted(active_ids - connected_ids)

    lines = [
        "# 错题网络概览",
        "",
        f"更新时间：{date.today().isoformat()}",
        "",
        f"- 错题数量：{len(cards)}",
        f"- 待补充具体错点：{sum(1 for card in cards if not clean_items(card['meta'].get('wrong_point')))}",
        f"- 待补充知识点：{sum(1 for card in cards if not clean_items(card['meta'].get('knowledge')))}",
        f"- 粗分待精分知识点：{sum(1 for card in cards if any(item.endswith(NON_SIGNAL_SUFFIXES) for item in clean_items(card['meta'].get('knowledge'))))}",
        f"- 已归档做错日期：{sum(1 for card in cards if clean_items(card['meta'].get('wrong_history')))}",
        f"- 复发错题：{sum(1 for card in cards if str(card['meta'].get('mistake_count', '')).isdigit() and int(card['meta'].get('mistake_count')) >= 2)}",
        f"- 主推荐关系数量：{len(pairs)}",
        f"- 强关联数量：{level_counts.get('强关联', 0)}",
        f"- 中关联数量：{level_counts.get('中关联', 0)}",
        f"- 弱关联审计样本：{level_counts.get('弱关联', 0)}",
        f"- 主推荐孤岛题：{len(isolated_active)}",
        "",
        "## 科目分布",
        "",
        *top_lines(count_scalar("subject"), "暂无科目信息"),
        "",
        "## 高频具体错点",
        "",
        *top_lines(count_field("wrong_point"), "暂无具体错点"),
        "",
        "## 高频知识点",
        "",
        *top_lines(count_field("knowledge"), "暂无知识点标签"),
        "",
        "## 高频错因",
        "",
        *top_lines(count_field("error_causes"), "暂无错因标签"),
        "",
        "## 高频方法",
        "",
        *top_lines(count_field("methods"), "暂无方法标签"),
        "",
        "## 关系来源",
        "",
        *top_lines(source_counts, "暂无关系来源"),
        "",
        "## 优先复做连接",
        "",
    ]

    if not pairs:
        lines.append("- 暂无相似题连接")
    else:
        for pair in pairs[:20]:
            reason = "；".join(pair["reasons"]) if pair["reasons"] else "文本或标签相似"
            lines.append(f"- `{pair['score']:.2f}` {pair.get('level')} {pair['a']} ↔ {pair['b']}：{reason}")

    if isolated_active:
        lines.extend(["", "## 主推荐孤岛题样本", ""])
        for qid in isolated_active[:30]:
            lines.append(f"- {qid}")

    (OUT_DIR / "错题网络概览.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_knowledge_review(cards: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in cards:
        for item in clean_items(card["meta"].get("knowledge")):
            grouped[item].append(card)

    lines = [
        "# 按知识点复做清单",
        "",
        f"更新时间：{date.today().isoformat()}",
        "",
        "用途：新错题如果明确错在某个知识点，优先到对应知识点下找旧题复做；缺少具体错因的旧题只作为知识点节点参与连接。",
        "",
    ]
    if not grouped:
        lines.append("暂无知识点标签。")
    for knowledge, items in sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        lines.extend(["", f"## {knowledge}（{len(items)}）", ""])
        explicit = [card for card in items if clean_items(card["meta"].get("wrong_point"))]
        missing = [card for card in items if not clean_items(card["meta"].get("wrong_point"))]
        for label, bucket in (("已写具体错点", explicit), ("待补充具体错点", missing)):
            if not bucket:
                continue
            lines.append(f"### {label}")
            for card in sorted(bucket, key=lambda item: item["id"])[:60]:
                meta = card["meta"]
                rel = Path("..") / card["relpath"]
                wrong = compact_text(", ".join(clean_items(meta.get("wrong_point"))) or "待补充")
                lines.append(f"- [{card['id']} {meta.get('title', '')}]({rel.as_posix()})：{wrong}")
            lines.append("")

    (OUT_DIR / "按知识点复做清单.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_mermaid(cards: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> None:
    lines = [
        "graph LR",
        "  classDef question fill:#eaf4ff,stroke:#2f6fb0,color:#111;",
        "  classDef knowledge fill:#effaf0,stroke:#3f8f4c,color:#111;",
        "  classDef error fill:#fff1ea,stroke:#ba5a31,color:#111;",
    ]
    node_ids: dict[str, str] = {}

    def node(prefix: str, label: str) -> str:
        key = f"{prefix}:{label}"
        if key not in node_ids:
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
            node_ids[key] = f"{prefix}_{digest}"
            safe_label = label.replace('"', "'")
            lines.append(f'  {node_ids[key]}["{safe_label}"]')
        return node_ids[key]

    q_nodes: dict[str, str] = {}
    for card in cards:
        meta = card["meta"]
        label = f"{card['id']}<br/>{meta.get('title', '')}"
        qid = node("q", label)
        q_nodes[card["id"]] = qid
        lines.append(f"  class {qid} question;")
        for item in clean_items(meta.get("knowledge")):
            kid = node("k", f"知识点：{item}")
            lines.append(f"  class {kid} knowledge;")
            lines.append(f"  {qid} --> {kid}")
        for item in clean_items(meta.get("error_causes")):
            eid = node("e", f"错因：{item}")
            lines.append(f"  class {eid} error;")
            lines.append(f"  {qid} --> {eid}")

    for pair in pairs:
        if pair["a"] not in q_nodes or pair["b"] not in q_nodes:
            continue
        lines.append(f'  {q_nodes[pair["a"]]} -. "{pair["score"]:.2f}" .- {q_nodes[pair["b"]]}')

    (OUT_DIR / "知识网络图.mmd").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json(cards: list[dict[str, Any]], pairs: list[dict[str, Any]], weak_pairs: list[dict[str, Any]]) -> None:
    payload = {
        "updated_at": date.today().isoformat(),
        "cards": [
            {
                "id": card["id"],
                "path": card["relpath"],
                "meta": card["meta"],
                "topic_chains": card.get("topic_chains", []),
            }
            for card in cards
        ],
        "similarities": pairs,
        "weak_relations": weak_pairs,
        "relation_summary": {
            "strong": sum(1 for pair in pairs if pair.get("level") == "强关联"),
            "medium": sum(1 for pair in pairs if pair.get("level") == "中关联"),
            "weak_audit": len(weak_pairs),
        },
    }
    (OUT_DIR / "wrong_questions.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def md_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br/>")


def rebuild(args: argparse.Namespace) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    cards = read_cards()
    active_cards = review_cards(cards)
    pairs, weak_pairs = compute_pairs(active_cards, args.threshold)
    write_index(cards)
    write_similarities(cards, pairs)
    write_strong_relations(cards, pairs)
    write_weak_audit(cards, weak_pairs)
    write_topic_chains(cards, pairs)
    write_overview(cards, pairs, weak_pairs)
    write_knowledge_review(active_cards)
    write_mermaid(cards, pairs)
    write_json(cards, pairs, weak_pairs)
    strong = sum(1 for pair in pairs if pair.get("level") == "强关联")
    medium = sum(1 for pair in pairs if pair.get("level") == "中关联")
    print(
        f"cards={len(cards)} strong={strong} medium={medium} weak_audit={len(weak_pairs)} output={OUT_DIR}"
    )
    return 0


def find_card(cards: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    for card in cards:
        if card["id"] == target:
            return card
    path = Path(target)
    if path.exists():
        resolved = path.resolve()
        for card in cards:
            if card["path"].resolve() == resolved:
                return card
    return None


def without_declared_related(card: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(card)
    cloned_meta = dict(card["meta"])
    cloned_meta["related"] = []
    cloned["meta"] = cloned_meta
    return cloned


def related(args: argparse.Namespace) -> int:
    cards = read_cards()
    target = find_card(cards, args.target)
    if target is None:
        print(f"未找到错题：{args.target}", file=sys.stderr)
        return 1
    target_view = without_declared_related(target) if args.ignore_declared else target
    results = []
    for card in cards:
        if card["id"] == target["id"]:
            continue
        if is_mastered(card):
            continue
        card_view = without_declared_related(card) if args.ignore_declared else card
        score, reasons = similarity(target_view, card_view)
        level, source, adjusted_score = relation_level(target_view, card_view, score, reasons)
        if not has_substantive_relation(reasons):
            continue
        if adjusted_score < args.threshold:
            continue
        results.append((level, adjusted_score, source, card, reasons))
    results.sort(key=lambda item: (RELATION_LEVELS.index(item[0]) if item[0] in RELATION_LEVELS else 9, -item[1], item[3]["id"]))

    print(f"{target['id']} {target['meta'].get('title', '')}")
    shown = 0
    backup: list[tuple[str, float, str, dict[str, Any], list[str]]] = []
    for level, score, source, card, reasons in results:
        if level == "弱关联":
            backup.append((level, score, source, card, reasons))
            continue
        if score <= 0:
            continue
        reason = "；".join(reasons) if reasons else "文本或标签相似"
        print(f"- {score:.2f} {level} {card['id']} {card['meta'].get('title', '')}：{reason}")
        shown += 1
        if shown >= args.top:
            break
    if shown == 0:
        print("暂无强/中关联相似题。")
        for level, score, source, card, reasons in backup[: min(args.top, 5)]:
            if score <= 0:
                continue
            reason = "；".join(reasons) if reasons else "弱文本或标签相似"
            print(f"- {score:.2f} {level} {card['id']} {card['meta'].get('title', '')}：{reason}")
    return 0


def knowledge(args: argparse.Namespace) -> int:
    cards = review_cards(read_cards())
    query = normalize_text(args.query)
    results: list[tuple[int, str, dict[str, Any]]] = []
    for card in cards:
        meta = card["meta"]
        knowledge_items = clean_items(meta.get("knowledge"))
        exact = any(normalize_text(item) == query for item in knowledge_items)
        fuzzy = any(query in normalize_text(item) or normalize_text(item) in query for item in knowledge_items)
        if not exact and not fuzzy:
            continue
        has_wrong = bool(clean_items(meta.get("wrong_point")))
        rank = (2 if exact else 1) + (2 if has_wrong else 0)
        results.append((rank, card["id"], card))

    results.sort(key=lambda item: (-item[0], item[1]))
    if not results:
        print(f"未找到知识点相关错题：{args.query}")
        return 0

    print(f"知识点：{args.query}，相关错题 {len(results)} 道")
    shown = 0
    for _, _, card in results:
        meta = card["meta"]
        wrong = compact_text(", ".join(clean_items(meta.get("wrong_point"))) or "待补充")
        knowledge_text = ", ".join(clean_items(meta.get("knowledge")))
        print(f"- {card['id']} {meta.get('title', '')}：{wrong}｜知识点：{knowledge_text}｜{card['relpath']}")
        shown += 1
        if shown >= args.top:
            break
    return 0


def safe_filename(text: str) -> str:
    text = text.strip()
    text = re.sub(r"[\\/:*?\"<>|]+", "", text)
    text = re.sub(r"\s+", "", text)
    return text[:24] or "未命名"


def new_card(args: argparse.Namespace) -> int:
    print(
        "wrongnet.py new 不用于当前轻量单题入库。\n"
        "请使用 kaoyan-math-wrong-intake 保存完整会话包与 Capture v3；"
        "明确正式入库后再由 kaoyan-math-nightly-qa 冻结、裁决并串行完成正式层。\n"
        "此命令本身不分配 ID、不创建错题卡。",
        file=sys.stderr,
    )
    return 2


def _legacy_new_card_template(args: argparse.Namespace) -> int:
    """Pre-async implementation retained only as source-format documentation.

    It is intentionally unreachable from the CLI.  Keeping the template here
    avoids silently deleting user history while ensuring there is no unlocked
    formal-card writer.
    """
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()
    next_day = today + timedelta(days=1)
    title = args.title or "待补充"
    filename = f"{args.id}_{safe_filename(title)}.md"
    path = CARDS_DIR / filename
    if path.exists():
        print(f"文件已存在：{path}", file=sys.stderr)
        return 1

    content = f"""---
id: {args.id}
title: {title}
subject: {args.subject}
source: 待补充
import_batch: 待补充
lecture_refs:
  - 待补充
chapter: {args.chapter}
question_type: 待补充
date: {today.isoformat()}
status: 待复做
difficulty: 3
priority: B
wrong_point: 待补充
knowledge:
  - 待补充
error_causes:
  - 待补充
methods:
  - 待补充
traps:
  - 待补充
answer: 待补充
related:
  - 待补充
review:
  next: {next_day.isoformat()}
  interval_days: 1
  count: 0
---

# {args.id} {title}

## 题目摘要

待补充。

## 标准答案

待补充。

## 具体错点

待补充。

## 标签

- 知识点：待补充
- 错因：待补充
- 方法：待补充
- 陷阱：待补充

## 必要提示

待补充。

## 复做要求

待补充。
"""
    path.write_text(content, encoding="utf-8")
    print(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="考研数学错题知识网络工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p_rebuild = sub.add_parser("rebuild", help="重建索引、相似题清单和网络图")
    p_rebuild.add_argument("--threshold", type=float, default=0.22, help="相似关系阈值")
    p_rebuild.set_defaults(func=rebuild)

    p_related = sub.add_parser("related", help="查看某道错题的相似题")
    p_related.add_argument("target", help="错题编号或错题卡路径")
    p_related.add_argument("--top", type=int, default=8)
    p_related.add_argument("--threshold", type=float, default=0.10)
    p_related.add_argument(
        "--ignore-declared",
        action="store_true",
        help="忽略正式卡 related 字段，只查看独立知识/方法/题型证据",
    )
    p_related.set_defaults(func=related)

    p_knowledge = sub.add_parser("knowledge", help="按知识点查看相关错题")
    p_knowledge.add_argument("query", help="知识点名称，例如 导数定义")
    p_knowledge.add_argument("--top", type=int, default=20)
    p_knowledge.set_defaults(func=knowledge)

    p_new = sub.add_parser("new", help="生成一张空白错题卡")
    p_new.add_argument("id", help="错题编号，例如 GS-001")
    p_new.add_argument("--title", default="待补充")
    p_new.add_argument("--subject", default="待补充")
    p_new.add_argument("--chapter", default="待补充")
    p_new.set_defaults(func=new_card)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
