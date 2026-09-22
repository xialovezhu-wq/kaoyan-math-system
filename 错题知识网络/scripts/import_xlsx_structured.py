#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
CARDS_DIR = BASE_DIR / "错题卡"
PROCESSED_DIR = BASE_DIR / "批量导入" / "已处理"
ARCHIVE_DIR = BASE_DIR / "批量导入" / "原始文件"

DEFAULT_XLSX = Path("/Users/your-user/Downloads/考研数学错题预处理_结构化表.xlsx")
BATCH_ID = "XLSX-2026-05-07-STRUCTURED"
REPLACED_BATCHES = {
    "DOCX-2026-05-07-QReader",
    BATCH_ID,
}

PLACEHOLDERS = {"", "待补充", "无", "未知", "none", "null", "-", "nan"}

SUBJECT_PREFIX = {
    "高等数学": "GS",
    "线性代数": "LA",
    "概率论与数理统计": "PR",
}

HIGH_MODULES = {
    "极限与连续",
    "函数极限",
    "函数极限与连续",
    "数列极限",
    "一元函数微分学",
    "一元函数微分学概念",
    "一元函数微分学应用",
    "中值定理",
    "不定积分",
    "定积分",
    "反常积分",
    "变上限积分",
    "微分方程",
    "多元函数微分学",
    "二重积分",
    "无穷级数",
    "级数",
}

LINEAR_MODULES = {
    "行列式",
    "矩阵",
    "矩阵运算",
    "矩阵秩",
    "向量组",
    "向量组线性相关",
    "线性方程组",
    "特征值与特征向量",
    "特征值与相似",
    "相似理论",
    "二次型",
}

PROB_MODULES = {
    "随机事件与概率",
    "随机变量及其分布",
    "随机变量分布",
    "数字特征",
    "概率论与数理统计",
}

HIGH_LECTURE_MODULES = {
    1: ["极限与连续"],
    2: ["数列极限"],
    3: ["导数定义", "一元函数微分学应用"],
    4: ["一元函数微分学应用", "导数定义"],
    5: ["一元函数微分学应用"],
    6: ["中值定理", "一元函数微分学应用"],
    7: ["一元函数微分学应用"],
    8: ["定积分"],
    9: ["不定积分", "定积分"],
    10: ["定积分"],
    11: ["定积分", "定积分性质"],
    12: ["定积分"],
    13: ["多元函数微分学"],
    14: ["二重积分"],
    15: ["微分方程"],
    16: ["无穷级数"],
    17: ["多元函数积分学"],
    18: ["多元函数积分学"],
}

LINEAR_LECTURE_MODULES = {
    1: ["行列式"],
    2: ["行列式"],
    3: ["矩阵运算"],
    4: ["矩阵秩", "矩阵运算"],
    5: ["线性方程组"],
    6: ["向量组线性相关"],
    7: ["特征值与特征向量"],
    8: ["相似理论", "特征值与特征向量"],
    9: ["二次型"],
}

SUBJECT_FALLBACK_KNOWLEDGE = {
    "高等数学": "高等数学综合待精分",
    "线性代数": "线性代数综合待精分",
    "概率论与数理统计": "概率统计综合待精分",
}

KNOWLEDGE_RULES: list[tuple[str, str]] = [
    ("幂指|取对数|指数型极限|1\\^|e\\^|对数化", "幂指极限"),
    ("等价无穷小|无穷小|同阶|阶数|主导项", "等价无穷小"),
    ("泰勒|麦克劳林", "泰勒展开"),
    ("洛必达", "洛必达法则"),
    ("极限|未定式|无穷大|无穷小|连续|间断", "极限与连续"),
    ("数列|递推|单调有界|n次根|n 次根", "数列极限"),
    ("导数定义|可导|左右导数", "导数定义"),
    ("切线|法线|渐近线|单调|极值|凹凸|拐点|曲率", "一元函数微分学应用"),
    ("中值定理|拉格朗日|罗尔|柯西", "中值定理"),
    ("不定积分|原函数", "不定积分"),
    ("定积分|变上限|积分中值|反常积分", "定积分"),
    ("微分方程", "微分方程"),
    ("偏导|全微分|多元|二重极限|拉格朗日乘子|约束极值", "多元函数微分学"),
    ("二重积分|极坐标|换序|雅可比", "二重积分"),
    ("级数|幂级数", "无穷级数"),
    ("行列式|代数余子式|余子式|拉普拉斯展开", "行列式"),
    ("矩阵|伴随矩阵|逆矩阵|初等变换|秩", "矩阵运算"),
    ("向量组|线性相关|线性无关", "向量组线性相关"),
    ("线性方程组|基础解系|通解|增广矩阵", "线性方程组"),
    ("特征值|特征向量|相似|对角化|实对称", "特征值与特征向量"),
    ("二次型|正定|合同|惯性指数|配方法", "二次型"),
    ("随机事件|条件概率|贝叶斯|全概率", "随机事件与概率"),
    ("随机变量|分布函数|密度|边缘分布|条件分布", "随机变量分布"),
    ("期望|方差|协方差|相关系数", "数字特征"),
]

ERROR_RULES: list[tuple[str, str]] = [
    ("审题|题意|条件没看|关键词", "审题遗漏"),
    ("条件|适用条件|使用条件|非零|正负|连续|可导|单调", "条件忽略"),
    ("概念|定义|无界|无穷大|连续性定义|导数定义", "概念混淆"),
    ("公式|忘记|记错|差角公式|运算法则", "公式记错"),
    ("没想到|不会想到|方法|路线|构造|反例|不熟", "方法选择错误"),
    ("计算|算错|化简|收尾|符号", "计算失误"),
    ("符号|正负号|方向|不等号", "符号错误"),
    ("定义域|无定义|分母|对数|根号", "定义域错误"),
    ("参数|范围|分类|分情况|边界", "参数范围错误"),
    ("断了|跳步|没有继续|收尾", "过程跳步"),
    ("分类|左右|正负|绝对值", "分类讨论不全"),
    ("证明|反证|目标", "证明结构不完整"),
    ("图像|几何|面积|旋转体", "图像理解错误"),
    ("记忆|忘记|没背牢", "复习记忆不牢"),
]

METHOD_RULES: list[tuple[str, str]] = [
    ("判型|题型识别|先判", "先判型"),
    ("转化|翻译|改写|换元|令", "条件转化"),
    ("特值|反例|构造反例", "特殊值检验"),
    ("分类|左右|正负|绝对值|参数范围", "分类讨论"),
    ("辅助函数|构造函数|设.*函数", "构造辅助函数"),
    ("等价|同阶|有理化|通分|提公因子|合并对数|对数化|指数化|主导项", "等价变形"),
    ("数形|几何|面积|图像", "数形结合"),
    ("反证", "反证法"),
    ("中值定理|拉格朗日|罗尔|柯西", "中值定理"),
    ("夹逼|放缩", "夹逼准则"),
    ("单调有界", "单调有界准则"),
    ("分部积分", "分部积分"),
    ("初等变换|行变换|列变换", "矩阵初等变换"),
    ("特征值|特征向量|相似对角化|正交", "特征分解"),
    ("概率模型|分布|独立", "概率模型拆解"),
]

TRAP_RULES: list[tuple[str, str]] = [
    ("适用条件|使用条件|非零|连续|可导", "适用条件"),
    ("定义域|无定义|分母|对数|根号", "定义域"),
    ("参数|边界|范围|等号", "参数边界"),
    ("左右极限|趋近|趋于|极限过程|取整", "极限过程"),
    ("正负|符号|绝对值|不等号", "正负号"),
    ("阶数|量级|主导项|高阶|低阶", "量纲/阶数"),
    ("端点|闭区间", "端点取值"),
    ("可逆|行列式", "可逆性"),
    ("秩|线性相关|线性无关", "秩条件"),
    ("独立", "独立性"),
]


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r", "\n")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def compact(value: Any, limit: int = 220) -> str:
    text = clean_text(value)
    return text[:limit].strip()


def is_placeholder(value: Any) -> bool:
    return clean_text(value).lower() in PLACEHOLDERS


def safe_filename(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "", text.strip())
    text = re.sub(r"\s+", "", text)
    return text[:32] or "未命名"


def split_tags(value: Any) -> list[str]:
    if is_placeholder(value):
        return []
    text = clean_text(value)
    text = re.sub(r"[，、；;|/]+", ",", text)
    tags: list[str] = []
    for item in text.split(","):
        item = compact(item, 28)
        if not item or item.lower() in PLACEHOLDERS:
            continue
        if re.search(r"题干含图片|摘要主要来自解析|OCR|同编号|需核对|待核对", item):
            continue
        if item not in tags:
            tags.append(item)
    return tags


def collect_tags(text: str, rules: list[tuple[str, str]]) -> list[str]:
    tags: list[str] = []
    for pattern, tag in rules:
        if re.search(pattern, text):
            tags.append(tag)
    return dedupe(tags)


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        item = compact(item, 32)
        if item and item.lower() not in PLACEHOLDERS and item not in result:
            result.append(item)
    return result


def row_text(row: pd.Series) -> str:
    return "\n".join(clean_text(row.get(col, "")) for col in row.index)


def update_subject_context(text: str, current: str) -> str:
    if re.search(r"概率强化|概率论|数理统计", text):
        return "概率论与数理统计"
    if re.search(r"线代强化|线性代数|线代[—\\-]|线代", text):
        return "线性代数"
    if re.search(r"高数强化|高等数学专项|高数专项", text):
        return "高等数学"
    return current


def infer_subject(row: pd.Series, context: str) -> str:
    text = row_text(row)
    title = clean_text(row.get("编号", ""))
    chapter = clean_text(row.get("章节模块", ""))
    chapter_label = canonical_chapter(chapter, "高等数学")

    if re.search(r"概率强化|概率论|数理统计|随机变量|概率密度|分布函数|条件概率|贝叶斯|全概率|期望|方差|协方差|假设检验|参数估计", text):
        return "概率论与数理统计"

    if chapter_label in HIGH_MODULES and not re.search(r"线代|线性代数", title + chapter):
        return "高等数学"

    if re.search(
        r"线代|线性代数|行列式|矩阵|向量组|特征值|特征向量|二次型|线性方程组|基础解系|伴随矩阵|代数余子式|相似对角化|正交变换|合同|惯性指数",
        text,
    ):
        return "线性代数"

    if canonical_chapter(chapter, "线性代数") in LINEAR_MODULES:
        return "线性代数"

    if context:
        return context

    subject = clean_text(row.get("科目", ""))
    return subject if subject in SUBJECT_PREFIX else "高等数学"


def canonical_chapter(raw: Any, subject: str) -> str:
    text = clean_text(raw)
    if not text or text.lower() in PLACEHOLDERS:
        text = ""
    if (
        len(text) > 36
        or re.search(r"待补充|OCR|题干为图片|与方法|所用方法|张宇风格|对应章节|方法选型|三向解题", text)
    ):
        text = ""

    combined = text
    rules = [
        ("二重积分|极坐标|换序", "二重积分"),
        ("多元函数|偏导|全微分|约束极值|拉格朗日乘子|多元", "多元函数微分学"),
        ("微分方程", "微分方程"),
        ("反常积分|变上限|定积分|积分估计", "定积分"),
        ("不定积分|原函数", "不定积分"),
        ("中值定理|拉格朗日|罗尔|柯西", "中值定理"),
        ("导数|微分学|切线|渐近线|单调|极值|凹凸", "一元函数微分学应用"),
        ("数列|递推", "数列极限"),
        ("极限|连续|间断|无穷小|无穷大", "极限与连续"),
        ("级数|幂级数", "无穷级数"),
        ("行列式|余子式", "行列式"),
        ("矩阵秩|求矩阵的秩", "矩阵秩"),
        ("矩阵|伴随矩阵|逆矩阵|初等变换", "矩阵运算"),
        ("向量组|线性相关|线性无关", "向量组线性相关"),
        ("线性方程组|基础解系|通解", "线性方程组"),
        ("特征值|特征向量|相似|对角化|实对称", "特征值与特征向量"),
        ("二次型|正定|合同|惯性", "二次型"),
        ("随机事件|条件概率|贝叶斯|全概率", "随机事件与概率"),
        ("随机变量|分布函数|密度|分布", "随机变量分布"),
        ("期望|方差|数字特征|协方差", "数字特征"),
    ]
    for pattern, label in rules:
        if re.search(pattern, combined):
            return label
    if text:
        return text
    if subject == "线性代数":
        return "线性代数"
    if subject == "概率论与数理统计":
        return "概率论与数理统计"
    return "高等数学"


def title_lecture_number(title: str) -> int | None:
    patterns = [
        r"强化例题\s*(\d+)",
        r"1000[题讲]?[ABab]?组?\s*(\d+)[\.、]",
        r"1000[题讲]?.*?[ABab]组\s*(\d+)[\.、]",
        r"第\s*(\d+)\s*讲",
    ]
    for pattern in patterns:
        match = re.search(pattern, title)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def infer_title_modules(title: str, subject: str) -> list[str]:
    number = title_lecture_number(title)
    if number is None:
        return []
    if subject == "线性代数":
        return LINEAR_LECTURE_MODULES.get(number, [])
    if subject == "高等数学":
        return HIGH_LECTURE_MODULES.get(number, [])
    return []


def infer_chapter(row: pd.Series, subject: str) -> str:
    raw = clean_text(row.get("章节模块", ""))
    merged = "\n".join(
        [
            raw,
            clean_text(row.get("编号", "")),
            clean_text(row.get("题目摘要", "")),
            clean_text(row.get("知识点标签", "")),
            clean_text(row.get("方法标签", "")),
        ]
    )
    chapter = canonical_chapter(raw, subject)
    if chapter in {"高等数学", "线性代数", "概率论与数理统计"}:
        inferred = canonical_chapter(merged, subject)
        if inferred not in {"高等数学", "线性代数", "概率论与数理统计"}:
            return inferred
        title_modules = infer_title_modules(clean_text(row.get("编号", "")), subject)
        if title_modules:
            return title_modules[0]
    return chapter


def question_type_from_text(text: str, subject: str) -> str:
    patterns = [
        ("幂指|指数型极限|取对数|1\\^", "幂指函数极限"),
        ("等价无穷小|同阶|阶数比较|主导项", "无穷小阶数比较"),
        ("递推|单调有界", "递推数列极限"),
        ("数列|n次根|n 次根", "数列极限"),
        ("间断点|连续性", "连续与间断判定"),
        ("渐近线|切线|法线|曲率", "曲线性质"),
        ("中值定理|罗尔|拉格朗日|柯西", "中值定理证明/估计"),
        ("参数|范围|判参", "含参数问题"),
        ("变上限积分|定积分|反常积分", "积分型问题"),
        ("二重积分|极坐标|换序", "二重积分计算"),
        ("行列式", "行列式计算"),
        ("矩阵|秩|伴随矩阵", "矩阵综合题"),
        ("线性方程组|基础解系|通解", "线性方程组"),
        ("特征值|特征向量|相似|对角化", "特征值与相似"),
        ("二次型|正定|合同", "二次型"),
        ("概率|随机|分布|期望|方差", "概率统计题"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, text):
            return label
    if subject == "线性代数":
        return "线性代数综合题"
    if subject == "概率论与数理统计":
        return "概率统计题"
    return "待补充"


def filter_noisy_tags(tags: list[str], row: pd.Series, subject: str) -> list[str]:
    text = row_text(row)
    evidence = "\n".join(
        clean_text(row.get(col, ""))
        for col in ["编号", "章节模块", "题目摘要", "标准答案", "我的具体错点", "方法标签", "易错陷阱", "备注"]
    )
    filtered: list[str] = []
    for tag in tags:
        if tag == "绝对值分类" and "绝对值" not in evidence:
            continue
        if tag in {"与方法", "与所用方法", "与方法（张宇风格）"}:
            continue
        filtered.append(tag)
    return dedupe(filtered)


def infer_lists(row: pd.Series, subject: str, chapter: str) -> tuple[list[str], list[str], list[str], list[str]]:
    text = row_text(row)
    wrong = clean_text(row.get("我的具体错点", ""))
    title = clean_text(row.get("编号", ""))

    knowledge = split_tags(row.get("知识点标签", "")) + collect_tags(text, KNOWLEDGE_RULES)
    if chapter not in {"高等数学", "线性代数", "概率论与数理统计"}:
        knowledge.insert(0, chapter)
    knowledge.extend(infer_title_modules(title, subject))
    knowledge = filter_noisy_tags(dedupe(knowledge), row, subject)
    if not knowledge:
        knowledge = [SUBJECT_FALLBACK_KNOWLEDGE.get(subject, "综合待精分")]

    if is_placeholder(wrong):
        error_causes = ["待补充"]
    else:
        # 错因只从用户明确写出的错点里归类；不从题干/摘要硬推，避免污染错因网络。
        error_causes = collect_tags(wrong, ERROR_RULES) or ["待补充"]

    methods = split_tags(row.get("方法标签", "")) + collect_tags(text, METHOD_RULES)
    methods = filter_noisy_tags(dedupe(methods), row, subject) or ["待补充"]

    traps = split_tags(row.get("易错陷阱", "")) + collect_tags(wrong + "\n" + text, TRAP_RULES)
    traps = filter_noisy_tags(dedupe(traps), row, subject) or ["待补充"]
    return knowledge, error_causes, methods, traps


def normalize_wrong_point(row: pd.Series) -> str:
    wrong = compact(row.get("我的具体错点", ""), 180)
    if not wrong or wrong.lower() in PLACEHOLDERS:
        return "待补充"
    if wrong.strip(" ：:。") in {"总结", "错误总结", "错题归纳笔记", "这题的核心失误有三层"}:
        return "待补充"
    return wrong


def normalize_answer(row: pd.Series) -> str:
    answer = compact(row.get("标准答案", ""), 160)
    return answer if answer and answer.lower() not in PLACEHOLDERS else "待补充"


def normalize_summary(row: pd.Series) -> str:
    summary = compact(row.get("题目摘要", ""), 260)
    if not summary or summary.lower() in PLACEHOLDERS:
        title = clean_text(row.get("编号", ""))
        return f"{title}；题干摘要待补充。"
    return summary


def normalize_hint(row: pd.Series, wrong_point: str, methods: list[str]) -> str:
    if wrong_point != "待补充":
        return f"先定位这题的错点：{compact(wrong_point, 120)}"
    usable_methods = [item for item in methods if item != "待补充"]
    if usable_methods:
        return f"这题先作为知识点节点保留；复做时按方法入口检查：{', '.join(usable_methods[:3])}。"
    return "这题先作为知识点节点保留；复做时补齐具体错因，再参与错因匹配。"


def yaml_list(items: list[str]) -> str:
    return "\n".join(f"  - {item}" for item in items)


def md_card(
    *,
    qid: str,
    title: str,
    subject: str,
    source_title: str,
    chapter: str,
    question_type: str,
    wrong_point: str,
    knowledge: list[str],
    error_causes: list[str],
    methods: list[str],
    traps: list[str],
    answer: str,
    summary: str,
    hint: str,
    note: str,
) -> str:
    today = date.today()
    next_day = today + timedelta(days=1)
    priority = "C" if wrong_point == "待补充" else "B"
    note_text = compact(note, 180) if not is_placeholder(note) else "来源表未提供额外备注。"
    return f"""---
id: {qid}
title: {title}
subject: {subject}
source: 考研数学错题预处理_结构化表.xlsx / {source_title}
import_batch: {BATCH_ID}
lecture_refs:
  - 待补充
chapter: {chapter}
question_type: {question_type}
date: {today.isoformat()}
status: 待复做
difficulty: 3
priority: {priority}
wrong_point: {wrong_point}
knowledge:
{yaml_list(knowledge)}
error_causes:
{yaml_list(error_causes)}
methods:
{yaml_list(methods)}
traps:
{yaml_list(traps)}
answer: {answer}
related:
  - 待补充
review:
  next: {next_day.isoformat()}
  interval_days: 1
  count: 0
---

# {qid} {title}

## 题目摘要

{summary}

## 标准答案

{answer}

## 具体错点

{wrong_point}

## 标签

- 知识点：{", ".join(knowledge)}
- 错因：{", ".join(error_causes)}
- 方法：{", ".join(methods)}
- 陷阱：{", ".join(traps)}

## 必要提示

{hint}

## 来源备注

{note_text}

## 复做提醒

下次遇到同类题，优先检查：{wrong_point if wrong_point != "待补充" else "题型识别、关键条件、方法入口和易错限制"}。
"""


def existing_batch_files(batch_ids: set[str]) -> list[Path]:
    files: list[Path] = []
    for path in CARDS_DIR.glob("*.md"):
        if path.name == "README.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(f"import_batch: {batch_id}" in text for batch_id in batch_ids):
            files.append(path)
    return files


def write_knowledge_catalog(df: pd.DataFrame) -> None:
    lines = [
        "# 结构化知识点目录",
        "",
        f"- 批次：{BATCH_ID}",
        f"- 日期：{date.today().isoformat()}",
        f"- 条目数：{len(df)}",
        "",
        "| 科目 | 章节 | 知识点名称 | 核心提醒 |",
        "| --- | --- | --- | --- |",
    ]
    for _, row in df.fillna("").iterrows():
        lines.append(
            "| "
            + " | ".join(
                md_cell(compact(row.get(col, ""), 180))
                for col in ["科目", "章节", "知识点名称", "核心提醒"]
            )
            + " |"
        )
    (PROCESSED_DIR / "结构化知识点目录.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def md_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br/>")


def write_report(
    *,
    xlsx: Path,
    archived: Path | None,
    cards: list[dict[str, Any]],
    removed: int,
    raw_subjects: Counter[str],
    duplicate_sources: int,
    knowledge_rows: int,
) -> None:
    subject_counter = Counter(card["subject"] for card in cards)
    chapter_counter = Counter(card["chapter"] for card in cards)
    knowledge_counter: Counter[str] = Counter()
    method_counter: Counter[str] = Counter()
    wrong_counter: Counter[str] = Counter()
    missing_wrong = []
    missing_knowledge = []
    coarse_knowledge = []
    for card in cards:
        usable_knowledge = [x for x in card["knowledge"] if x != "待补充"]
        knowledge_counter.update(usable_knowledge)
        if not usable_knowledge:
            missing_knowledge.append(card)
        if any(x.endswith("待精分") for x in usable_knowledge):
            coarse_knowledge.append(card)
        method_counter.update([x for x in card["methods"] if x != "待补充"])
        if card["wrong_point"] == "待补充":
            missing_wrong.append(card)
        else:
            wrong_counter[card["wrong_point"]] += 1

    lines = [
        "# XLSX 结构化导入报告",
        "",
        f"- 批次：{BATCH_ID}",
        f"- 日期：{date.today().isoformat()}",
        f"- 来源文件：{xlsx}",
        f"- 归档文件：{archived if archived else '未归档'}",
        f"- 替换旧批次错题卡：{removed}",
        f"- 新增错题卡：{len(cards)}",
        f"- 知识点目录条目：{knowledge_rows}",
        f"- 来源编号重复行数：{duplicate_sources}",
        f"- 待补充具体错点：{len(missing_wrong)}",
        f"- 待补充知识点：{len(missing_knowledge)}",
        f"- 粗分待精分知识点：{len(coarse_knowledge)}",
        "- 处理策略：缺少具体错点的题保留为知识点节点，但不从题干硬推错因。",
        "",
        "## 来源表科目列分布",
        "",
    ]
    lines.extend(f"- {name}：{count}" for name, count in raw_subjects.most_common())
    lines.extend(["", "## 导入后科目分布", ""])
    lines.extend(f"- {name}：{count}" for name, count in subject_counter.most_common())
    lines.extend(["", "## 高频章节", ""])
    lines.extend(f"- {name}：{count}" for name, count in chapter_counter.most_common(20))
    lines.extend(["", "## 高频知识点", ""])
    lines.extend(f"- {name}：{count}" for name, count in knowledge_counter.most_common(20))
    lines.extend(["", "## 高频方法", ""])
    lines.extend(f"- {name}：{count}" for name, count in method_counter.most_common(20))
    lines.extend(["", "## 高频具体错点", ""])
    if wrong_counter:
        lines.extend(f"- {name}：{count}" for name, count in wrong_counter.most_common(20))
    else:
        lines.append("- 暂无")
    lines.extend(["", "## 待补充错点样本", ""])
    if missing_wrong:
        for card in missing_wrong[:80]:
            lines.append(f"- {card['id']} {card['title']}：{card['summary']}")
    else:
        lines.append("- 无")

    report = "\n".join(lines) + "\n"
    (PROCESSED_DIR / "XLSX-2026-05-07-STRUCTURED.md").write_text(report, encoding="utf-8")


def import_xlsx(args: argparse.Namespace) -> int:
    xlsx = Path(args.xlsx).expanduser().resolve()
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    removed = 0
    if args.replace_previous:
        files = existing_batch_files(REPLACED_BATCHES)
        for path in files:
            path.unlink()
        removed = len(files)

    archived: Path | None = None
    if args.archive_source:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archived = ARCHIVE_DIR / xlsx.name
        shutil.copy2(xlsx, archived)

    wrong_df = pd.read_excel(xlsx, sheet_name="错题表").fillna("")
    knowledge_df = pd.read_excel(xlsx, sheet_name="知识点目录").fillna("")
    raw_subjects = Counter(clean_text(x) for x in wrong_df.get("科目", []))
    duplicate_sources = int(wrong_df["编号"].duplicated().sum()) if "编号" in wrong_df else 0

    counters = {"GS": 1, "LA": 1, "PR": 1, "MX": 1}
    cards: list[dict[str, Any]] = []
    seen_source: Counter[str] = Counter()
    context = "高等数学"

    for _, row in wrong_df.iterrows():
        text = row_text(row)
        context = update_subject_context(text, context)
        subject = infer_subject(row, context)
        context = subject if subject in SUBJECT_PREFIX else context
        prefix = SUBJECT_PREFIX.get(subject, "MX")
        qid = f"{prefix}-{counters[prefix]:03d}"
        counters[prefix] += 1

        source_title = clean_text(row.get("编号", "")) or qid
        seen_source[source_title] += 1
        title = source_title
        if seen_source[source_title] > 1:
            title = f"{source_title}-{seen_source[source_title]}"
        title = compact(title, 42)

        chapter = infer_chapter(row, subject)
        merged = "\n".join([title, chapter, text])
        question_type = question_type_from_text(merged, subject)
        wrong_point = normalize_wrong_point(row)
        answer = normalize_answer(row)
        summary = normalize_summary(row)
        knowledge, error_causes, methods, traps = infer_lists(row, subject, chapter)
        hint = normalize_hint(row, wrong_point, methods)
        note = clean_text(row.get("备注", ""))

        card = {
            "id": qid,
            "title": title,
            "subject": subject,
            "chapter": chapter,
            "question_type": question_type,
            "wrong_point": wrong_point,
            "knowledge": knowledge,
            "error_causes": error_causes,
            "methods": methods,
            "traps": traps,
            "answer": answer,
            "summary": summary,
        }
        cards.append(card)
        path = CARDS_DIR / f"{qid}_{safe_filename(title)}.md"
        path.write_text(
            md_card(
                qid=qid,
                title=title,
                subject=subject,
                source_title=source_title,
                chapter=chapter,
                question_type=question_type,
                wrong_point=wrong_point,
                knowledge=knowledge,
                error_causes=error_causes,
                methods=methods,
                traps=traps,
                answer=answer,
                summary=summary,
                hint=hint,
                note=note,
            ),
            encoding="utf-8",
        )

    write_knowledge_catalog(knowledge_df)
    write_report(
        xlsx=xlsx,
        archived=archived,
        cards=cards,
        removed=removed,
        raw_subjects=raw_subjects,
        duplicate_sources=duplicate_sources,
        knowledge_rows=len(knowledge_df),
    )
    print(
        f"imported={len(cards)} removed={removed} knowledge_rows={len(knowledge_df)} batch={BATCH_ID}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从结构化 XLSX 导入错题知识网络")
    parser.add_argument("--xlsx", default=str(DEFAULT_XLSX))
    parser.add_argument("--replace-previous", action="store_true", help="替换上一版 DOCX/XLSX 批次")
    parser.add_argument("--archive-source", action="store_true", help="把来源 XLSX 归档到批量导入/原始文件")
    return parser


def main() -> int:
    parser = build_parser()
    parser.parse_args()
    parser.error(
        "生产写入入口已关闭：XLSX 原件须完整保留，当前题通过 wrong-intake 保存事实包；明确正式入库后再由 nightly-qa 串行裁决"
    )


if __name__ == "__main__":
    raise SystemExit(main())
