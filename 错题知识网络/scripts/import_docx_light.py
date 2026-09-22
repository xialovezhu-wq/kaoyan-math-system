#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile


BASE_DIR = Path(__file__).resolve().parents[1]
CARDS_DIR = BASE_DIR / "错题卡"
PROCESSED_DIR = BASE_DIR / "批量导入" / "已处理"
DOCX_SOURCE = Path(
    "/Users/your-user/Library/Containers/QReader.MarginStudy.easy/Data/Documents/考研高数(2026-05-07-19-38-02).docx"
)
BATCH_ID = "DOCX-2026-05-07-QReader"
PYTHON = "/Users/your-user/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

PLACEHOLDERS = {"", "待补充", "无", "未知", "none", "null", "-"}


@dataclass
class Item:
    text: str
    images: list[str] = field(default_factory=list)


@dataclass
class Segment:
    title: str
    subject_context: str
    texts: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    order: int = 0

    @property
    def body(self) -> str:
        return "\n".join(text for text in self.texts if text).strip()


WRONG_STRONG = re.compile(
    r"(错因|错误|错题|我的错误|我的漏洞|我的主要问题|失误|忽略|没想到|不会|卡住|断了|计算出错|错在|漏了)"
)
STRUCTURE_HINT = re.compile(
    r"(复习思路|题型识别|核心突破口|Solution|标准答案|正确答案|正确选项|正确思路|主线步骤|最终结论|本题考查)"
)
PROBLEM_TITLE = re.compile(
    r"(1000\s*题?|真题|例题|T\d+|\d{5,6}|20\d{2}[年.]|B组|A组|数[一二三123]|选择题|填空题)"
)
LECTURE_TITLE = re.compile(
    r"(第[一二三四五六七八九十0-9]+讲|三向解题法|理论总结|知识体系|公式|方法|常见|大观|总纲|使用场合|线代强化第|高数强化第|概率强化第)"
)
KNOWLEDGE_TITLE = re.compile(
    r"^(O[₁₂₃④⑤⑥⑦0-9]|[一二三四五六七八九十]+[、.]|\d+[、.]|\(\d\)|计算$|按定义|常见|未定式|极限|三向|第一章|第二章|第三章|第四章|第五章|第六章|第七章|第八章|第九章|高数|线代|概率|知识|方法|公式|对数型|指数差|带头大哥|复合函数|变上限|无穷)"
)

KNOWLEDGE_RULES: list[tuple[str, str]] = [
    ("等价无穷小|无穷小|同阶|泰勒|洛必达|重要极限", "等价无穷小"),
    ("函数极限|极限|未定式|左右极限|取整函数|无穷大|无穷大量", "极限与连续"),
    ("连续|间断|可去|跳跃|无穷间断|振荡间断", "函数极限与连续"),
    ("数列|递推|单调有界|n 次根|n次根|根号", "数列极限"),
    ("导数定义|左右导数|可导|切线|渐近线|单调性|极值|凹凸|拐点", "一元函数微分学应用"),
    ("中值定理|罗尔|拉格朗日|柯西", "中值定理"),
    ("不定积分|原函数|分部积分|换元积分", "不定积分"),
    ("定积分|变上限|积分中值|牛顿|莱布尼茨|反常积分", "定积分"),
    ("微分方程|通解|特解|可分离变量|一阶线性", "微分方程"),
    ("偏导|全微分|多元|二重极限|齐次函数|拉格朗日乘子", "多元函数微分学"),
    ("二重积分|累次积分|极坐标", "二重积分"),
    ("级数|幂级数|泰勒级数", "无穷级数"),
    ("行列式", "行列式"),
    ("矩阵|伴随矩阵|逆矩阵|初等变换|秩", "矩阵运算"),
    ("向量组|线性相关|线性无关", "向量组线性相关"),
    ("线性方程组|基础解系|通解", "线性方程组"),
    ("特征值|特征向量|相似矩阵|相似对角化|对角化", "特征值与特征向量"),
    ("二次型|正定|合同", "二次型"),
    ("概率|随机事件|条件概率|贝叶斯", "随机事件与概率"),
    ("分布函数|密度|二维随机变量|边缘分布|条件分布", "随机变量分布"),
    ("期望|方差|协方差|相关系数", "数字特征"),
]

ERROR_RULES: list[tuple[str, str]] = [
    ("审题|题意|条件没看|关键词", "审题遗漏"),
    ("条件|使用条件|适用条件|没有把.*条件|非零|正负|单调|连续", "条件忽略"),
    ("概念|定义|无界数列|无穷大数列|连续性定义|导数定义", "概念混淆"),
    ("公式|记错|忘记|差角公式|运算法则", "公式记错"),
    ("方法|路线|思路|没想到|不会想到|不熟|反例|构造", "方法选择错误"),
    ("计算|算错|收尾|截距|符号|化简", "计算失误"),
    ("符号|正负号|方向|不等号", "符号错误"),
    ("定义域|无定义|可疑点|间断点|左右极限|取整", "定义域错误"),
    ("参数|范围|分类|分情况|边界", "参数范围错误"),
    ("跳步|断了|继续|没有继续|收尾", "过程跳步"),
    ("分类|分情况|左右|正负|绝对值", "分类讨论不全"),
    ("证明|反证|结构|目标", "证明结构不完整"),
    ("图像|几何|面积|旋转体", "图像理解错误"),
    ("不熟|记忆|忘记|没背牢", "复习记忆不牢"),
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
    ("标准流程|SOP|依次|先.*再", "标准化计算流程"),
    ("初等变换|行变换", "矩阵初等变换"),
    ("特征值|特征向量|相似对角化|正交", "特征分解"),
    ("概率模型|分布|独立", "概率模型拆解"),
    ("中值定理|拉格朗日|罗尔|柯西", "中值定理"),
    ("夹逼|放缩", "夹逼准则"),
    ("单调有界", "单调有界准则"),
]

TRAP_RULES: list[tuple[str, str]] = [
    ("适用条件|使用条件|非零|连续|可导", "适用条件"),
    ("定义域|无定义|分母|对数|根号", "定义域"),
    ("参数|边界|范围|等号", "参数边界"),
    ("左右极限|趋近|趋于|极限过程|取整", "极限过程"),
    ("正负|符号|绝对值|不等号", "正负号"),
    ("常数|截距", "常数项"),
    ("阶数|量级|主导项|高阶|低阶", "量纲/阶数"),
    ("独立", "独立性"),
    ("可逆|行列式", "可逆性"),
    ("秩|线性相关|线性无关", "秩条件"),
    ("重根|根的个数|零点个数", "根的重数"),
    ("分段|分界点", "分段点"),
    ("端点|闭区间", "端点取值"),
]


def clean_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\$+", "", text)
    text = re.sub(r"\\\[|\\\]|\\\(|\\\)", " ", text)
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"[*_`>]+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def compact(text: str, limit: int = 180) -> str:
    text = clean_text(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].strip()


def safe_filename(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "", text.strip())
    text = re.sub(r"\s+", "", text)
    return text[:32] or "未命名"


def is_title(text: str) -> bool:
    return text.endswith(">>") and len(text) <= 180


def relationship_map(zip_file: ZipFile) -> dict[str, str]:
    rels = ET.fromstring(zip_file.read("word/_rels/document.xml.rels"))
    mapping: dict[str, str] = {}
    for rel in rels.findall(".//rel:Relationship", NS):
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target", "")
        if rid and target.startswith("media/"):
            mapping[rid] = f"word/{target}"
    return mapping


def extract_items(docx: Path) -> list[Item]:
    with ZipFile(docx) as z:
        rels = relationship_map(z)
        root = ET.fromstring(z.read("word/document.xml"))
    items: list[Item] = []
    for para in root.findall(".//w:p", NS):
        text = "".join((t.text or "") for t in para.findall(".//w:t", NS)).strip()
        images: list[str] = []
        for blip in para.findall(".//a:blip", NS):
            rid = blip.attrib.get(f"{{{NS['r']}}}embed")
            if rid and rid in rels:
                images.append(rels[rid])
        if text or images:
            items.append(Item(text=text, images=images))
    return items


def split_segments(items: list[Item]) -> list[Segment]:
    segments: list[Segment] = []
    current: Segment | None = None
    subject = "高等数学"
    order = 0

    for item in items:
        text = item.text
        if "线代" in text or "线性代数" in text:
            subject = "线性代数"
        elif "概率" in text or "数理统计" in text:
            subject = "概率论与数理统计"
        elif "高数" in text or "高等数学" in text:
            subject = "高等数学"

        if text and is_title(text):
            if current is not None:
                segments.append(current)
            order += 1
            current = Segment(title=text[:-2].strip(), subject_context=subject, order=order)
            current.images.extend(item.images)
        else:
            if current is None:
                order += 1
                current = Segment(title="未归类", subject_context=subject, order=order)
            current.texts.append(text)
            current.images.extend(item.images)

    if current is not None:
        segments.append(current)
    return segments


def is_problem_segment(segment: Segment) -> bool:
    title = segment.title.strip()
    body = segment.body
    if not title and not body:
        return False

    problem_title = bool(PROBLEM_TITLE.search(title))
    strong_wrong = bool(WRONG_STRONG.search(title) or WRONG_STRONG.search(body))
    structure = bool(STRUCTURE_HINT.search(body))
    lecture = bool(LECTURE_TITLE.search(title))
    knowledge = bool(KNOWLEDGE_TITLE.search(title)) and not problem_title and not strong_wrong

    if lecture and not problem_title and not strong_wrong:
        return False
    if knowledge and not strong_wrong:
        return False
    if problem_title:
        return bool(segment.images or body)
    if strong_wrong:
        return True
    if structure and segment.images and len(body) >= 120:
        return True
    return False


def infer_subject(segment: Segment) -> str:
    text = f"{segment.title}\n{segment.body}"
    if re.search(r"概率|随机|分布函数|概率密度|期望|方差|协方差|相关系数|贝叶斯|假设检验|参数估计", text):
        return "概率论与数理统计"
    if re.search(
        r"线代|线性代数|矩阵|行列式|向量组|特征值|特征向量|二次型|线性方程组|相似矩阵|相似对角化|正交矩阵",
        text,
    ):
        return "线性代数"
    if re.search(
        r"高数|高等数学|函数|极限|连续|间断|数列|导数|可导|微分|中值定理|罗尔|拉格朗日|切线|法线|渐近线|积分|原函数|级数|曲线|曲率|多元|偏导|二重|微分方程|极值|单调|凹凸",
        text,
    ):
        return "高等数学"
    return segment.subject_context or "高等数学"


def subject_prefix(subject: str) -> str:
    if subject == "线性代数":
        return "LA"
    if subject == "概率论与数理统计":
        return "PR"
    return "GS"


def chapter_from_text(text: str, subject: str) -> str:
    rules = [
        ("极限|连续|间断|无穷小|无穷大", "极限与连续"),
        ("数列|递推", "数列极限"),
        ("导数|切线|渐近线|单调|极值|凹凸|中值定理", "一元函数微分学"),
        ("不定积分|原函数", "不定积分"),
        ("定积分|变上限|反常积分", "定积分"),
        ("微分方程", "微分方程"),
        ("多元|偏导|全微分|二重极限|极值", "多元函数微分学"),
        ("二重积分", "二重积分"),
        ("级数|幂级数", "级数"),
        ("行列式", "行列式"),
        ("矩阵|秩", "矩阵"),
        ("向量组", "向量"),
        ("线性方程组|基础解系", "线性方程组"),
        ("特征值|特征向量|相似", "特征值与相似"),
        ("二次型|正定", "二次型"),
        ("随机事件|概率", "随机事件与概率"),
        ("随机变量|分布", "随机变量及其分布"),
        ("期望|方差|数字特征", "数字特征"),
    ]
    for pattern, label in rules:
        if re.search(pattern, text):
            return label
    if subject == "线性代数":
        return "线性代数"
    if subject == "概率论与数理统计":
        return "概率论与数理统计"
    return "高等数学"


def question_type_from_text(text: str) -> str:
    patterns = [
        ("1\\^\\s*∞|1\\^|幂指|指数型极限|取对数", "幂指函数极限"),
        ("等价无穷小|同阶|阶数比较", "无穷小阶数比较"),
        ("n 次根|n次根|根号.*n|数列极限", "数列极限"),
        ("递推|单调有界", "递推数列极限"),
        ("间断点|连续性", "连续与间断判定"),
        ("渐近线|切线", "曲线性质"),
        ("中值定理|罗尔|拉格朗日", "中值定理证明/估计"),
        ("参数|范围|判参", "含参数问题"),
        ("变上限积分|定积分", "积分型问题"),
        ("矩阵|行列式|秩|特征值|二次型", "线性代数综合题"),
        ("概率|随机|分布|期望|方差", "概率统计题"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, text):
            return label
    return "待补充"


def collect_tags(text: str, rules: list[tuple[str, str]], fallback: str = "待补充") -> list[str]:
    tags = []
    for pattern, tag in rules:
        if re.search(pattern, text):
            tags.append(tag)
    seen = []
    for tag in tags:
        if tag not in seen:
            seen.append(tag)
    return seen or [fallback]


def section_after(text: str, headers: list[str], max_chars: int = 500) -> str:
    for header in headers:
        match = re.search(header, text)
        if not match:
            continue
        tail = text[match.end() :]
        stop = re.search(r"\n\s*(#{1,4}\s*)?(⑦|①|②|③|④|⑤|##|# |---|正确|标准|知识|题型|核心|主线)", tail)
        if stop and stop.start() > 10:
            tail = tail[: stop.start()]
        return compact(tail, max_chars)
    return ""


def infer_wrong_point(segment: Segment) -> str:
    text = clean_text(f"{segment.title}\n{segment.body}")
    extracted = section_after(
        text,
        [
            r"错因归纳",
            r"错误原因",
            r"我的错误",
            r"我的主要问题",
            r"我的漏洞",
            r"你的问题",
            r"主要失误",
            r"核心失误",
            r"错因",
        ],
        260,
    )
    if extracted:
        return normalize_wrong_point(extracted)
    title = segment.title.strip()
    if re.search(r"忽略|计算出错|不会|没想到|错", title):
        return compact(title, 120)
    for line in clean_text(segment.body).splitlines():
        if WRONG_STRONG.search(line):
            return normalize_wrong_point(line)
    return "待补充"


def normalize_wrong_point(text: str) -> str:
    raw_lines = []
    for line in clean_text(text).splitlines():
        line = line.strip()
        if not line:
            continue
        if re.fullmatch(r"(错题归纳笔记|错题回顾|错误总结|错因总结|总结|解题思路|正确解题步骤|下面整理.*|Solution By Steps)", line):
            continue
        if line in {"[", "]", "$$"}:
            continue
        if line.startswith(("\\", "{", "}")):
            continue
        if re.search(r"(忘记|忽略|没有|没能|没想到|误判|错|失误|不熟|不会|漏|混淆|导致)", line):
            raw_lines.append(line)
    if raw_lines:
        text = "；".join(raw_lines[:2])
    text = re.sub(r"\\[a-zA-Z]+(\{[^{}]*\})?", "", text)
    text = re.sub(r"[_^{}[\]$]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^[：:。\\-—、\\s]+", "", text)
    text = re.sub(r"^\d+[).、]\s*", "", text)
    text = re.sub(r"这次失误的本质[，,是]*", "", text)
    text = re.sub(r"这题你的核心失误[有两点：:]*", "", text)
    text = re.sub(r"你的主要失误[在于：:]*", "", text)
    text = re.sub(r"你的核心失误[不是]*", "", text)
    text = re.split(r"[。；;]\s*", text)[0].strip()
    return compact(text, 140) or "待补充"


def infer_answer(segment: Segment) -> str:
    text = clean_text(segment.body)
    for pattern in [
        r"最终结论[:：]?\s*(.+)",
        r"标准答案[:：]?\s*(.+)",
        r"正确答案[:：]?\s*(.+)",
        r"正确选项[:：]?\s*(.+)",
        r"答案[:：]?\s*(.+)",
    ]:
        match = re.search(pattern, text)
        if match:
            return compact(match.group(1), 120)
    match = re.search(r"正确答案选\s*([A-D])", text)
    if match:
        return f"选 {match.group(1)}"
    return "待补充"


def infer_hint(segment: Segment) -> str:
    text = clean_text(segment.body)
    for header in ["核心突破口", "主线步骤", "正确思路", "复盘口诀", "下次遇到", "下次看到"]:
        snippet = section_after(text, [header], 220)
        if snippet:
            return snippet
    for line in text.splitlines():
        if re.search(r"先|优先|必须|下次|关键", line) and len(line.strip()) >= 8:
            return compact(line, 180)
    return "待补充"


def infer_summary(segment: Segment, ocr_text: str) -> str:
    text = clean_text(segment.body)
    q = section_after(text, [r"题目", r"题设", r"本题考点"], 260)
    if q and "待补充" not in q:
        return q
    if ocr_text:
        return compact(f"{segment.title}；OCR题干：{ocr_text}", 220)
    if text:
        qt = question_type_from_text(text)
        return compact(f"{segment.title}；{qt}", 180)
    return compact(f"{segment.title}；题干在源 DOCX 图片中，待补充文字题干。", 180)


def existing_batch_files(batch_id: str) -> list[Path]:
    files = []
    for path in CARDS_DIR.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if f"import_batch: {batch_id}" in text:
            files.append(path)
    return files


def next_counters() -> dict[str, int]:
    counters = {"GS": 1, "LA": 1, "PR": 1, "MX": 1}
    for path in CARDS_DIR.glob("*.md"):
        match = re.search(r"\b(GS|LA|PR|MX)-(\d{3,})\b", path.stem)
        if not match:
            continue
        prefix, number = match.group(1), int(match.group(2))
        counters[prefix] = max(counters[prefix], number + 1)
    return counters


def yaml_list(items: list[str]) -> str:
    return "\n".join(f"  - {item}" for item in items)


def md_card(
    qid: str,
    title: str,
    subject: str,
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
    priority: str,
    source_title: str,
) -> str:
    today = date.today()
    next_day = today + timedelta(days=1)
    return f"""---
id: {qid}
title: {title}
subject: {subject}
source: 考研高数(2026-05-07-19-38-02).docx / {source_title}
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

## 复做提醒

下次遇到同类题，先检查：{wrong_point if wrong_point != "待补充" else "题型识别、关键条件和方法入口"}。
"""


def build_ocr_binary() -> Path | None:
    swift = shutil.which("swiftc")
    if swift is None:
        return None
    source = BASE_DIR / "scripts" / "vision_ocr.swift"
    binary = Path(tempfile.gettempdir()) / "wrongnet_vision_ocr"
    subprocess.run([swift, str(source), "-o", str(binary)], check=True)
    return binary


def ocr_images(docx: Path, segments: list[Segment], max_images: int | None) -> dict[int, str]:
    needed: list[tuple[int, str]] = []
    for idx, segment in enumerate(segments):
        if not segment.images:
            continue
        if len(segment.body.strip()) >= 80:
            continue
        needed.append((idx, segment.images[0]))
        if max_images is not None and len(needed) >= max_images:
            break

    if not needed:
        return {}

    binary = build_ocr_binary()
    if binary is None:
        return {}

    results: dict[int, str] = {}
    with tempfile.TemporaryDirectory(prefix="wrongnet_docx_ocr_") as tmp_name:
        tmp = Path(tmp_name)
        image_paths: list[tuple[int, Path]] = []
        with ZipFile(docx) as z:
            for idx, image_name in needed:
                suffix = Path(image_name).suffix or ".png"
                out = tmp / f"{idx:04d}{suffix}"
                out.write_bytes(z.read(image_name))
                image_paths.append((idx, out))

        proc = subprocess.Popen(
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc.stdin is not None
        for _, path in image_paths:
            proc.stdin.write(str(path) + "\n")
        proc.stdin.close()
        assert proc.stdout is not None
        by_path = {str(path): idx for idx, path in image_paths}
        for line in proc.stdout:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            idx = by_path.get(payload.get("path", ""))
            if idx is not None:
                results[idx] = compact(payload.get("text", ""), 260)
        proc.wait(timeout=60 * max(1, len(image_paths)))
    return results


def write_report(cards: list[dict[str, Any]], skipped: list[Segment], ocr_count: int) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    subject_counter = Counter(card["subject"] for card in cards)
    knowledge_counter: Counter[str] = Counter()
    wrong_counter: Counter[str] = Counter()
    missing = []
    for card in cards:
        knowledge_counter.update([x for x in card["knowledge"] if x.lower() not in PLACEHOLDERS])
        if card["wrong_point"] != "待补充":
            wrong_counter[card["wrong_point"]] += 1
        else:
            missing.append(card)

    lines = [
        "# DOCX 轻量导入报告",
        "",
        f"- 批次：{BATCH_ID}",
        f"- 日期：{date.today().isoformat()}",
        f"- 新增错题卡：{len(cards)}",
        f"- OCR 识别截图节点：{ocr_count}",
        f"- 跳过知识点/非错题节点：{len(skipped)}",
        f"- 待补充具体错点：{len(missing)}",
        "",
        "## 科目分布",
        "",
    ]
    lines.extend(f"- {name}：{count}" for name, count in subject_counter.most_common())
    lines.extend(["", "## 高频知识点", ""])
    lines.extend(
        f"- {name}：{count}" for name, count in knowledge_counter.most_common(20)
    )
    lines.extend(["", "## 高频具体错点", ""])
    if wrong_counter:
        lines.extend(f"- {name}：{count}" for name, count in wrong_counter.most_common(20))
    else:
        lines.append("- 暂无")
    lines.extend(["", "## 待补充错点样本", ""])
    if missing:
        for card in missing[:80]:
            lines.append(f"- {card['id']} {card['title']}：{card['summary']}")
    else:
        lines.append("- 无")

    report = "\n".join(lines) + "\n"
    (PROCESSED_DIR / "DOCX-2026-05-07-QReader.md").write_text(report, encoding="utf-8")


def import_docx(args: argparse.Namespace) -> int:
    docx = Path(args.docx)
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    if args.replace_batch:
        for path in existing_batch_files(BATCH_ID):
            path.unlink()

    items = extract_items(docx)
    segments = split_segments(items)
    candidates = [segment for segment in segments if is_problem_segment(segment)]
    skipped = [segment for segment in segments if segment not in candidates]

    if args.limit:
        candidates = candidates[: args.limit]

    ocr_texts = ocr_images(docx, candidates, args.max_ocr) if args.ocr else {}
    counters = next_counters()
    seen_titles: Counter[str] = Counter()
    cards: list[dict[str, Any]] = []

    for idx, segment in enumerate(candidates):
        subject = infer_subject(segment)
        prefix = subject_prefix(subject)
        qid = f"{prefix}-{counters[prefix]:03d}"
        counters[prefix] += 1

        source_title = segment.title or f"未命名节点{segment.order}"
        seen_titles[source_title] += 1
        title = source_title
        if seen_titles[source_title] > 1:
            title = f"{source_title}-{seen_titles[source_title]}"
        title = compact(title, 40)

        combined = f"{title}\n{segment.body}"
        wrong_point = infer_wrong_point(segment)
        answer = infer_answer(segment)
        chapter = chapter_from_text(combined, subject)
        question_type = question_type_from_text(combined)
        knowledge = collect_tags(combined, KNOWLEDGE_RULES)
        error_causes = collect_tags(wrong_point + "\n" + combined, ERROR_RULES)
        methods = collect_tags(combined, METHOD_RULES)
        traps = collect_tags(wrong_point + "\n" + combined, TRAP_RULES)
        hint = infer_hint(segment)
        summary = infer_summary(segment, ocr_texts.get(idx, ""))
        priority = "C" if wrong_point == "待补充" else "B"

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
                priority=priority,
                source_title=source_title,
            ),
            encoding="utf-8",
        )

    write_report(cards, skipped, len(ocr_texts))
    print(
        f"imported={len(cards)} skipped={len(skipped)} ocr={len(ocr_texts)} batch={BATCH_ID}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从 DOCX 轻量导入错题网络")
    parser.add_argument("--docx", default=str(DOCX_SOURCE))
    parser.add_argument("--replace-batch", action="store_true")
    parser.add_argument("--ocr", action="store_true", help="对纯截图节点使用 macOS Vision OCR")
    parser.add_argument("--max-ocr", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    return parser


def main() -> int:
    parser = build_parser()
    parser.parse_args()
    parser.error(
        "生产写入入口已关闭：DOCX 原件须完整保留，当前题通过 wrong-intake 保存事实包；明确正式入库后再由 nightly-qa 串行裁决"
    )


if __name__ == "__main__":
    raise SystemExit(main())
