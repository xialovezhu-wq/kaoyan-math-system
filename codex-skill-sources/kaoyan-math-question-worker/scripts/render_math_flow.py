#!/usr/bin/env python3
"""Render the math solution outline from short, already-authorized data."""
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from math_sidebar import panel_target, standalone, write_page


ASSETS = Path(__file__).resolve().parents[1] / "assets"
NODE_RENDER = r"""
const fs = require('fs');
const katex = require(process.argv[1]);
const formulas = JSON.parse(fs.readFileSync(0, 'utf8'));
try {
  const rendered = formulas.map(latex => katex.renderToString(latex, {
    output: 'mathml', displayMode: true, throwOnError: true,
    trust: false, strict: 'error'
  }));
  process.stdout.write(JSON.stringify(rendered));
} catch (error) {
  process.stderr.write(error.message);
  process.exitCode = 1;
}
"""


def required_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def render_formulas(formulas):
    result = subprocess.run(
        ["node", "-e", NODE_RENDER, str(ASSETS / "katex.min.js")],
        input=json.dumps(formulas), text=True, capture_output=True, check=False,
    )
    if result.returncode:
        raise ValueError("formula rendering failed: " + result.stderr.strip())
    return json.loads(result.stdout)


def fill_template(name, values):
    template = (ASSETS / name).read_text()
    return re.sub(r"__([A-Z_]+)__", lambda match: values[match[1]], template)


def render_method_mapping(flow_id, title, method):
    formulas = []

    def render_item(item, field):
        label = item.get("label", "")
        latex = item.get("latex", "")
        if not isinstance(label, str) or not isinstance(latex, str) or not (label.strip() or latex.strip()):
            raise ValueError(f"{field} must contain a label or a formula")
        text = f'<span class="mapping-text">{escape(label)}</span>' if label.strip() else ""
        if not latex.strip():
            return text
        token = f"<!--math:{len(formulas)}-->"
        formulas.append(latex)
        return f'{text}<span class="mapping-equation">{token}</span>'

    def render_node(node, depth=0):
        label = escape(required_text(node.get("label"), "method.label"))
        preview = render_item(node["process"], "method.process")
        sections = []
        for key, heading in (("calculation", "计算细节"), ("formulas", "基本公式"), ("conclusions", "二级结论")):
            items = node.get(key, [])
            if not isinstance(items, list) or (key == "calculation" and not items):
                raise ValueError(f"method.{key} must be a list with the calculation or check for this step")
            if items:
                body = "".join(f'<p>{render_item(item, key)}</p>' for item in items)
                sections.append(f'<div class="mapping-section"><h3>{heading}</h3>{body}</div>')

        children = node.get("children", [])
        if not isinstance(children, list):
            raise ValueError("method.children must be a list")
        branches = ""
        if children:
            branches = '<ul role="list">' + "".join(render_node(child, depth + 1) for child in children) + "</ul>"
        details = "".join(sections)
        return (
            f'<li style="--depth:{depth}"><div class="mapping-row">'
            f'<div class="mapping-method"><span>{label}</span></div>'
            '<span class="mapping-arrow" aria-hidden="true"></span>'
            '<details class="mapping-process"><summary class="cursor-interaction">'
            f'<span class="mapping-preview">{preview}</span>'
            '<span class="mapping-chevron" aria-hidden="true"></span></summary>'
            f'<div class="mapping-detail">{details}</div></details></div>{branches}</li>'
        )

    rows = render_node(method)
    rendered = render_formulas(formulas)
    rows = re.sub(r"<!--math:(\d+)-->", lambda match: rendered[int(match[1])], rows)
    return fill_template("method-mapping.html", {"FLOW_ID": flow_id, "TITLE": escape(title), "ROWS": rows})


def render(data):
    flow_id = required_text(data.get("id"), "id")
    if not re.fullmatch(r"[a-z][a-z0-9-]*", flow_id):
        raise ValueError("id must use lowercase ASCII letters, digits and hyphens")
    title = required_text(data.get("title"), "title")
    if "method" in data:
        if "steps" in data:
            raise ValueError("provide either method or steps")
        return render_method_mapping(flow_id, title, data["method"])
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a nonempty list")

    formulas = []
    for step in steps:
        required_text(step.get("label"), "step.label")
        required_text(step.get("title", step["label"]), "step.title")
        blocks = step.get("formulas", [])
        if not isinstance(blocks, list):
            raise ValueError("step.formulas must be a list")
        for block in blocks:
            formulas.append(required_text(block.get("latex"), "formula.latex"))
            if not isinstance(block.get("label", ""), str):
                raise ValueError("formula.label must be a string")
        if not isinstance(step.get("note", ""), str):
            raise ValueError("step.note must be a string")

    rendered = iter(render_formulas(formulas))
    bodies = []
    buttons = []
    panels = []
    for index, step in enumerate(steps):
        blocks = []
        for block in step.get("formulas", []):
            label = escape(block.get("label", ""))
            heading = f'<div class="text-small">{label}</div>' if label else ""
            blocks.append(f'<div class="formula-group">{heading}{next(rendered)}</div>')
        note = escape(step.get("note", ""))
        if note:
            blocks.append(f'<div class="flow-note text-small">{note}</div>')
        body = "\n".join(blocks)
        bodies.append(body)
        pressed = str(index == 0).lower()
        label = escape(step["label"])
        step_title = escape(step.get("title", step["label"]))
        buttons.append(
            f'<button class="btn btn-block" type="button" aria-pressed="{pressed}" '
            f'aria-controls="{flow_id}-detail">{label}</button>'
        )
        panels.append(f'<template data-title="{step_title}">{body}</template>')

    values = {
        "FLOW_ID": flow_id,
        "TITLE": escape(title),
        "BUTTONS": '<span class="flow-arrow" aria-hidden="true">→</span>'.join(buttons),
        "COLUMNS": " auto ".join(["minmax(0, 1fr)"] * len(steps)),
        "FIRST_TITLE": escape(steps[0].get("title", steps[0]["label"])),
        "FIRST_BODY": bodies[0],
        "PANELS": "\n".join(panels),
    }
    return fill_template("horizontal-math-flow.html", values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="-", help="JSON file or - for stdin")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--figure", type=Path, help="Optional local math-renderer fragment approved for this same question and stage")
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        source = sys.stdin.read() if args.input == "-" else Path(args.input).read_text()
        data = json.loads(source)
        fragment = render(data)
        if args.figure:
            fragment += "\n" + args.figure.read_text(encoding="utf-8")
        output = args.output.expanduser().resolve()
        write_page(output, standalone(data["title"], fragment))
        print(json.dumps({
            "status": "rendered", **panel_target(output, data["title"]),
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        }, ensure_ascii=False))
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
