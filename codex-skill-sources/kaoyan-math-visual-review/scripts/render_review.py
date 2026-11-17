#!/usr/bin/env python3
"""Render the night's sourced math memory cards as a single offline HTML page."""

import argparse
import base64
from datetime import date
import hashlib
from html import escape
import json
import os
from pathlib import Path
import re
from string import Template
import subprocess
import sys
import tempfile

SKILL = Path(__file__).resolve().parents[1]
INLINE_MATH = re.compile(r"\\\((.+?)\\\)|(?<![\\$])\$(?!\$)([^$\n]+?)(?<!\\)\$(?!\$)")
MATH_TOKEN = re.compile(r"@@MATH-(\d+)@@")
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}

NODE_RENDER = """
const fs = require('node:fs');
const katex = require(process.argv[1]);
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
try {
  const rendered = input.map(({latex, block}) => katex.renderToString(latex, {
    output: 'mathml', displayMode: block, throwOnError: true, trust: false, strict: 'error'
  }).replace(/<annotation[^>]*>[^]*?<\\/annotation>/g, ''));
  process.stdout.write(JSON.stringify(rendered));
} catch (error) {
  process.stderr.write(error.message);
  process.exitCode = 1;
}
"""


def image_markup(repo, reference, title):
    path = repo / reference["path"]
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != reference["sha256"]:
        raise ValueError(f"题图哈希不符：{path}")
    uri = f'data:{IMAGE_TYPES[path.suffix.lower()]};base64,' + base64.b64encode(content).decode("ascii")
    alt = escape(reference.get("alt", f"{title}的原题面"))
    dimensions = ""
    if reference.get("width") and reference.get("height"):
        dimensions = f' width="{int(reference["width"])}" height="{int(reference["height"])}"'
    return f'<figure class="question"><img src="{uri}" alt="{alt}"{dimensions} loading="lazy" decoding="async"></figure>'


def render(data, repo):
    day = date.fromisoformat(data["date"])
    heading = f"{day.month} 月 {day.day} 日数学复盘"
    formulas = []

    def mark(latex, block=False):
        formulas.append({"latex": latex, "block": block})
        return f"@@MATH-{len(formulas) - 1}@@"

    def inline(text):
        parts, start = [], 0
        for match in INLINE_MATH.finditer(text):
            parts.extend((escape(text[start:match.start()]), mark(match[1] or match[2])))
            start = match.end()
        return "".join(parts) + escape(text[start:])

    def equation(latex):
        return f'<div class="equation">{mark(latex, block=True)}</div>'

    def render_items(items, view):
        if not items:
            return '<p class="condition">本题无另列的已核条目。</p>'
        rows = []
        for item in items:
            if view == "direct" and item.get("entry_id"):
                scripts = str(repo / "错题知识网络/scripts")
                if scripts not in sys.path:
                    sys.path.insert(0, scripts)
                from math_formula_cards import lookup
                ready = lookup(repo, item["entry_id"], view=view, full=True)
                if ready["status"] == "ready":
                    card = ready["card"]
                    terms = []
                    for cond in card["assumptions_latex"]:
                        terms.append(" ".join(x for x in (
                            mark(cond["latex"]) if cond.get("latex") else "",
                            inline(cond.get("label", ""))) if x))
                    conditions = '<ul class="condition">' + "".join(f'<li>{x}</li>' for x in terms) + "</ul>"
                    statement = "".join(equation(x["latex"]) if "latex" in x else f'<p>{inline(x["text"])}</p>'
                                        for x in card["statement_sequence"])
                    boundaries = "".join(f'<p class="condition">边界：{inline(x)}</p>' for x in card["guard_note"])
                    sources = "".join(f"<li>{escape(Path(ref['path']).name)}"
                                      f"{' · PDF ' + str(ref['pdf_page']) if ref.get('pdf_page') else ''}</li>"
                                      for ref in card["source_refs"])
                    details = ("<details><summary>展开推导／来源</summary><ul>"
                               + "".join(f"<li>{inline(x)}</li>" for x in card["detail_steps"])
                               + sources + "</ul></details>")
                    rows.append(f'<li><div>{escape(card["title"])}</div>{conditions}{statement}{boundaries}{details}</li>')
                    continue
            label = inline(item["label"])
            if item.get("entry_id") and not item.get("condition"):
                # A stale ID cannot act as evidence for a detached fallback.
                rows.append('<li class="condition">公式派生待更新；本页未附已核适用条件。</li>')
                continue
            condition = f'<div class="condition">{inline(item["condition"])}</div>' if item.get("condition") else ""
            formula = equation(item["latex"]) if item.get("latex") else ""
            rows.append(f"<li><div>{label}</div>{condition}{formula}</li>")
        return '<ul class="study-list">' + "".join(rows) + "</ul>"

    def render_process(node):
        lines = node.get("process")
        if not isinstance(lines, list) or not lines:
            raise ValueError(f'方法节点缺少本题解题过程：{node["label"]}')
        parts = []
        for line in lines:
            if set(line) == {"latex"} and line["latex"].strip():
                parts.append(equation(line["latex"]))
            elif set(line) == {"text"} and line["text"].strip():
                parts.append(f'<p>{inline(line["text"])}</p>')
            else:
                raise ValueError(f'解题过程的每行须为一条短文或公式：{node["label"]}')
        return '<div class="solution-box">' + "".join(parts) + "</div>"

    def render_tree(node, depth=0):
        children = node.get("children", [])
        branches = ""
        if children:
            branches = '<ul role="list">' + "".join(render_tree(child, depth + 1) for child in children) + "</ul>"
        item = f'<span class="node">{inline(node["label"])}</span>'
        if mapped:
            arrow = '<span class="step-arrow" aria-hidden="true"></span>'
            row = f'<div class="method-row"><div class="method-step">{item}</div>{arrow}{render_process(node)}</div>'
        else:
            if "process" in node:
                raise ValueError(f'方法树根节点缺少本题解题过程：{node["label"]}')
            row = f'<div class="method-row"><div class="method-step">{item}</div></div>'
        return f'<li style="--depth:{depth}">{row}{branches}</li>'

    def render_part(title, css, body):
        return f'<section class="card-part {css}"><h4>{title}</h4>{body}</section>'

    def render_card(card):
        ident = escape(card["id"])
        title = escape(card["title"])
        view = card.get("view", "legacy_reviewed")
        if view not in ("direct", "protected", "legacy_reviewed"):
            raise ValueError("复盘卡只能发布已解锁内容或受保护题面")
        if view == "protected":
            # Never embed a protected title, answer, formula ID, method tree,
            # hidden details, or solution-side file path in the artifact.
            ident = "protected-" + str(protected_positions[id(card)])
            title = "受保护题面"
        source = escape(card["source"]) if view != "protected" else ""
        if "question_image" in card:
            ref = card["question_image"]
            if view == "protected":
                if ref.get("role") != "question_image" and not Path(ref["path"]).name.startswith("question_"):
                    raise ValueError("受保护题面的原图角色未核验")
                ref = {**ref, "alt": "受保护题面原图"}
            question = image_markup(repo, ref, card["title"] if view != "protected" else "受保护题面")
        else:
            fields = "".join(
                f'<dt>{escape(row["label"])}</dt><dd>{inline(row["text"])}</dd>' for row in card["question_parts"]
            )
            question = f'<dl class="question question-parts">{fields}</dl>'
        if view == "protected":
            return f'<article class="card" id="{ident}"><h3>{title}</h3>{question}</article>'
        tree = '<ul class="method-tree" role="list">' + render_tree(card["method"]) + "</ul>"
        if mapped:
            method = ('<section class="card-part methods mapped">'
                      '<div class="method-headings"><h4>基本方法</h4><span>解题过程</span></div>'
                      f'{tree}</section>')
        else:
            method = render_part("基本方法", "methods", tree)
        return "\n".join([
            f'<article class="card" id="{ident}">',
            f'<div class="card-heading"><h3>{title}</h3><span class="source">{source}</span></div>',
            question,
            render_part("二级结论", "conclusions", render_items(card["conclusions"], view)),
            method,
            render_part("基本公式", "formulas", render_items(card["formulas"], view)),
            "</article>",
        ])

    groups = data["sections"]
    all_cards = [card for group in groups for card in group["cards"]]
    protected_positions = {id(card): i for i,card in enumerate(all_cards, 1)}
    card_ids = [card["id"] for card in all_cards]
    mapped = any("process" in card["method"] for card in all_cards if card.get("view") != "protected")
    keys = [group["key"] for group in groups]
    if not card_ids or len(set(card_ids + keys + ["all", "topics"])) != len(card_ids) + len(keys) + 2:
        raise ValueError("专题或卡片标识为空或冲突")
    controls = ['<a href="#topics" data-filter="all" aria-current="true">全部</a>']
    sections = []
    for group in groups:
        key = escape(group["key"])
        title = escape(group["title"])
        if any(card.get("view") == "protected" for card in group["cards"]):
            key = "review-group-" + str(len(sections) + 1)
            title = "待作答题面" if all(card.get("view") == "protected" for card in group["cards"]) else "复盘与待作答"
        cards = "\n".join(render_card(card) for card in group["cards"])
        controls.append(f'<a href="#{key}" data-filter="{key}">{title}</a>')
        sections.append(f'<section id="{key}" data-topic="{key}"><h2>{title}</h2>{cards}</section>')

    katex = SKILL.parent / "kaoyan-math-question-worker/assets/katex.min.js"
    if not katex.is_file():
        codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        katex = codex_home / "skills/kaoyan-math-question-worker/assets/katex.min.js"
    compiled = subprocess.run(["node", "-e", NODE_RENDER, str(katex)],
                              input=json.dumps(formulas), capture_output=True, text=True)
    if compiled.returncode:
        raise ValueError("MathML 渲染失败：" + compiled.stderr.strip())
    mathml = json.loads(compiled.stdout)
    template = Template((SKILL / "assets/review.html").read_text(encoding="utf-8"))
    page = template.substitute(heading=heading, count=len(card_ids), year=day.year,
                               filters="\n".join(controls), sections="\n".join(sections))
    return MATH_TOKEN.sub(lambda match: mathml[int(match[1])], page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    html = render(json.loads(args.input.read_bytes()), args.repo.resolve())
    output = args.output.resolve()
    temp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as file:
            temp = Path(file.name)
            file.write(html)
        temp.replace(output)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    print(output)


if __name__ == "__main__":
    main()
