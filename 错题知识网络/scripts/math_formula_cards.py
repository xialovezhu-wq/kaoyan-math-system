#!/usr/bin/env python3
"""Build formula-first reference cards from the existing reviewed math registries.

The single current.json selects an immutable local display generation. This
module never changes a reference registry, learner record, or formal writer.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
import datetime as dt
import fcntl
import hashlib
from html import escape
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
import tempfile
from urllib.parse import quote

import math_formula_registry as registry
import math_geometry_projection as geometry
import math_recap as recap

ROOT = Path(__file__).resolve().parents[2]
STORE = Path("错题知识网络/公式结论库/公式卡")
CURRENT = STORE / "current.json"
GEOMETRY_INPUT = Path("错题知识网络/个人知识点索引/做题方法/回顾/公式图形.json")
RENDERER = Path("codex-skill-sources/kaoyan-math-question-worker/assets/katex.min.js")
KATEX_VERSION = "0.16.40"
KATEX_SHA = "759450e87b7d6523ab99fc833330673f400a8cc1a87d0055e1ca261baf98d9e4"
VERSION = "math-formula-card-v1"
POINTER = "math-formula-current-v1"
RELEASE = "math-formula-release-v1"
VIEWS = {"direct", "after_attempt"}
SECTIONS = {"basic_formulas": "basic_formula", "secondary_conclusions": "secondary_conclusion"}
DISPLAY = re.compile(r"(?<!\\)\$\$(.+?)\$\$|(?<!\\)\\\[(.+?)(?<!\\)\\\]", re.S)
INLINE = re.compile(r"\\\((.+?)\\\)|(?<![\\$])\$(?!\$)([^$\n]+?)(?<!\\)\$(?!\$)")
SPECIFIC = re.compile(r"(?:^MATH[123]-\d{4}-|^MRC-.*-Q\d+|(?:本题|此题|该题)(?:的|中|可|取|给|求|结论|答案)"
                      r"|选项\s*[A-D]|正确答案|第\s*[（(]?\s*\d\s*[）)]?\s*问)")
GEOMETRIC = re.compile(r"法向量|方向向量|点向式|点法式|空间.*夹角")

NODE = """
const fs = require('node:fs');
const katex = require(process.argv[1]);
if (katex.version !== process.argv[2]) throw Error('unexpected_renderer_version');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = input.map(([latex, displayMode]) => {
  try {
    return katex.renderToString(latex, {output:'mathml', displayMode,
      trust:false, strict:'error', throwOnError:true, maxExpand:200})
      .replace(/<annotation[^>]*>[^]*?<\\/annotation>/g, '');
  } catch (error) { return null; }
});
process.stdout.write(JSON.stringify(out));
"""
CSS = ("body{font:1rem/1.65 system-ui,sans-serif;color:#18283b;background:#f5f7fb;margin:0}"
       "main{max-width:48rem;margin:1.5rem auto;padding:0 1rem}article{padding:1.3rem;background:#fff;"
       "border:1px solid #c4cedb;border-radius:.8rem}h1{margin:.25em 0;font-size:1.38rem}"
       "h2{font-size:1.04rem;margin:.75em 0 .2em}ul{padding-inline-start:1.3em;margin:.2em 0}"
       ".math{overflow-x:auto;padding:.25rem 0}.condition{border-left:3px solid #37738a;"
       "padding:.45rem .75rem;background:#edf5f7;margin:1rem 0}.condition h2{margin:0}"
       "a{color:#18558c}a:focus-visible,summary:focus-visible{outline:3px solid #245f9a}"
       "details{margin-top:1rem}summary{cursor:pointer;font-weight:600}"
       ".guard{background:#fff6db;padding:.45rem .7rem;margin:.85rem 0}.guard h2{margin:0}"
       ".badge{color:#405971;font-size:.85rem}figure{margin:.9rem 0}"
       "img{display:block;max-width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}")


class CardError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(canonical(value))


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def relative(path):
    if not isinstance(path, str) or "\\" in path or "\x00" in path:
        raise CardError("invalid_relative_path")
    parts = path.split("/")
    if not path or any(p in ("", ".", "..") for p in parts):
        raise CardError("invalid_relative_path")
    return PurePosixPath(path).as_posix()


def read(path, size=24_000_000):
    return json.loads(read_bytes(path, size))


def read_bytes(path, size=24_000_000):
    with path.open("rb") as stream:
        value = stream.read(size + 1)
    if len(value) > size:
        raise CardError("oversized_formula_projection_file")
    return value


def write(path, value):
    payload = value if isinstance(value, bytes) else canonical(value)
    if path.is_file() and path.read_bytes() == payload:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".formula-", delete=False) as stream:
        tmp = Path(stream.name)
        try:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


@contextmanager
def lock(root):
    path = root / STORE
    for parent in list(path.parents)[:len(STORE.parts) - 1] + [path]:
        if parent.is_symlink():
            raise CardError("formula_projection_directory_symlink")
    path.mkdir(parents=True, exist_ok=True)
    with (path / "projection.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def signature(path):
    try:
        return recap._signature(path)
    except (OSError, ValueError):
        return None


def freshness(root, dependencies, *, rehash=False):
    """Missing/unreadable is unresolved; confirmed byte/permission change is stale."""
    outcomes = []
    for ref in dependencies:
        path = root / relative(ref["path"])
        current = signature(path)
        status, reason = "current", "verified"
        if current is None:
            status, reason = "unresolved", "file_missing_or_unreadable"
        elif rehash or current != ref["stat"]:
            try:
                if recap._hash_file(path, current) != ref["sha256"]:
                    status, reason = "stale", "file_content_changed"
            except (OSError, ValueError):
                status, reason = "unresolved", "could_not_verify_bytes"
        if status != "current":
            outcomes.append({"path": ref["path"], "status": status, "reason": reason})
    return {"status": "stale" if any(x["status"] == "stale" for x in outcomes)
            else "unresolved" if outcomes else "current", "issues": outcomes}


def file_proof(root, path, expected=None, *, priority_hint=None):
    path = relative(str(path))
    p = root / path
    stat = recap._signature(p)
    # Reuse an authoritative guard only on the same real file and stat tuple.
    if priority_hint and priority_hint.get("stat") == stat and priority_hint.get("sha256") == expected:
        actual = expected
    else:
        actual = recap._hash_file(p, stat)
    if expected is not None and actual != expected:
        raise CardError("source_hash_changed:" + path)
    return {"path": path, "sha256": actual, "stat": stat}


def proof_many(root, refs, cache, known):
    result = []
    for ref in refs:
        path, expected = ref["path"], ref["sha256"]
        if not recap.SHA.fullmatch(str(expected)):
            raise CardError("unknown_source_hash:" + path)
        key = (path, expected)
        if key not in cache:
            cache[key] = file_proof(root, path, expected, priority_hint=known.get(path))
        result.append(cache[key])
    return result


def strings(values, label):
    if not isinstance(values, list) or any(not isinstance(s, str) or not s.strip() for s in values):
        raise CardError("invalid_" + label)
    return [s.strip() for s in values]


def split_conclusions(content):
    """Use authored display formulas; retain every nonduplicate qualifying fragment."""
    formulas, prose, ordered, offset = [], [], [], 0
    for match in DISPLAY.finditer(content):
        if before := content[offset:match.start()].strip():
            prose.append(before)
            ordered.append({"text": before})
        formula = (match[1] or match[2]).strip()
        formulas.append(formula)
        ordered.append({"latex": formula})
        offset = match.end()
    if tail := content[offset:].strip():
        prose.append(tail)
        ordered.append({"text": tail})
    return formulas, prose, ordered


CASE_BLOCK = re.compile(r"(\\begin\{cases\})(.*?)(\\end\{cases\})", re.S)
LEGACY_CASE_BREAK = re.compile(r",\\(?!\\)(?=(?:\d|[A-Za-z](?![A-Za-z]))[^&\\\n]*&)")


def display_tex(value):
    # Only repair unambiguous legacy *typesetting*: in a cases alignment an
    # invalid single slash after a comma, before a new left cell and &.
    # Preserve every expression and boundary, and leave other errors pending.
    value = CASE_BLOCK.sub(lambda m: m[1] + LEGACY_CASE_BREAK.sub(lambda _: ",\\\\", m[2]) + m[3], value)
    value = value.replace(r"\centernot", r"\not")
    value = re.sub(r"(?<=[A-Za-z0-9})])′", "'", value)
    value = re.sub(r"\\(?:mathrm\{|rm\s+)([\u3400-\u9fff]+)(?=\})",
                   lambda m: (r"\text{" + m[1]) if m[0].startswith(r"\mathrm") else (r"\text{" + m[1] + "}"), value)
    return value


def latex(value):
    if not isinstance(value, str) or not value.strip() or "$" in value or (
            re.search(r"(?<!\\)\\[\[\]()]", value)
            or re.search(r"\\(?:href|url|includegraphics|html\w*|def|newcommand|write)\b", value)):
        raise CardError("invalid_or_unsafe_formula_tex")
    if len(value) > 2400:
        raise CardError("formula_needs_manual_layout")
    return display_tex(value.strip())


def conditions(raw):
    out = []
    for line in strings(raw, "conditions"):
        m = INLINE.fullmatch(line) or DISPLAY.fullmatch(line)
        # English/Chinese source qualifiers remain complete in the same field.
        out.append({"latex": latex(m[1] or m[2])} if m else {"label": line})
    return out


def checked_card(card):
    if card["schema"] != VERSION or not recap.ID.fullmatch(card["card_id"]) or not card["concept_key"]:
        raise CardError("invalid_card_identity")
    scope = card["scope"]
    if (scope.get("type") not in ("general_reference", "exact_question")
            or scope["stage"] != "reviewed_reference"
            or scope["type"] == "exact_question" and not scope.get("question_ids")):
        raise CardError("ambiguous_card_scope")
    if (card["kind"] not in SECTIONS.values() or not card["source_refs"]
            or not recap.SHA.fullmatch(card["source_version"])
            or card["representation_version"] != VERSION
            or not card["allowed_views"] or not set(card["allowed_views"]) <= VIEWS):
        raise CardError("invalid_card_source_or_view")
    if not card["assumptions_latex"] and not card.get("no_extra_assumptions_reason"):
        raise CardError("missing_explicit_conditions")
    for item in card["assumptions_latex"]:
        if not isinstance(item, dict) or not set(item) <= {"latex", "label"} or not any(item.values()):
            raise CardError("invalid_assumption")
        if "latex" in item:
            latex(item["latex"])
    latex(card["conclusion_latex"])
    for item in strings(card["step_latex"], "formula_steps"):
        latex(item)
    return card


def statement_scope(entry, topic):
    identity = entry["entry_id"]
    if entry.get("attempt_id") or entry.get("formal_id"):
        raise CardError("unverified_attempt_scope")
    question_ids = [b["question_id"] for b in topic.get("question_bindings", [])
                    if identity in b["entry_ids"]]
    exact = (entry.get("exact_question_only") or entry.get("question_id")
             or SPECIFIC.search(identity) or SPECIFIC.search(entry.get("name", ""))
             or SPECIFIC.search(entry.get("content", "")))
    if exact:
        # Question-bound examples stay with the guarded native raw-material
        # entry. Static cards cannot be used as a lower-stage partial export.
        raise CardError("exact_question_material_requires_native_view")
    return {"type": "general_reference", "stage": "reviewed_reference",
            "native_question_bindings": sorted(set(question_ids))}


def from_recap(entry, topic):
    if not recap.reference_ready(entry):
        raise CardError("not_reference_ready")
    scope = statement_scope(entry, topic)
    # Display delimiting is the only transformation here. Formula selection and
    # implication direction come from the reviewed source, never a paraphraser.
    equations, prose, _ = split_conclusions(entry["content"])
    if not equations:
        raise CardError("no_explicit_display_formula")
    if entry.get("direct_use") is False:
        prose = [*prose, "本条只作已核参考；先核对象与条件，再判断能否直接引用。"]
    limits = [*entry.get("exceptions", []), *[entry[k] for k in ("scope_restriction", "use_guard") if entry.get(k)]]
    if entry.get("variants"):
        limits.append("变体条件分别核对，见原条目。")
    symbols = entry.get("symbol_roles", [])
    return scope, equations, prose, limits, symbols


def from_registry(entry):
    if not registry.formula_reference_ready(entry):
        raise CardError("not_reference_ready")
    if SPECIFIC.search(entry["title"]) or SPECIFIC.search(entry.get("statement_text", "")):
        raise CardError("exact_question_material_requires_native_view")
    equations = entry.get("formula_latex", [])
    if not equations:
        raise CardError("no_explicit_display_formula")
    guard = entry.get("exceptions_and_counterexamples", [])
    if entry.get("direct_use") is False:
        guard = [*guard, "本条只作已核参考；使用前逐项核对条件。"]
    if entry.get("variants"):
        guard = [*guard, "变体条件分别核对，见原条目。"]
    symbols = []
    for item in entry.get("symbol_roles", []):
        if isinstance(item, str):
            symbols.append(item)
        elif item.get("symbol_latex"):
            symbols.append(r"\(" + latex(item["symbol_latex"]) + r"\)：" + item["role"])
        else:
            symbols.append(f"{item['symbol']}：{item['role']}")
    return {"type": "general_reference", "stage": "reviewed_reference"}, equations, \
        [entry["statement_text"]] if entry.get("statement_text") else [], guard, symbols


def _make_card(entry, *, key, kind, scope, equations, prose, limits, symbols, source_refs, detail_ref,
               subject, name, aliases, triggers, allowed_views, special=None):
    assumptions = conditions(entry.get("conditions", []))
    # Identical text already in a visible condition may be omitted here.
    known = {item.get("label") for item in assumptions} | {name}
    notes = list(dict.fromkeys(x for x in prose if x.strip(" ：。；\n") and x not in known))
    # An interleaved branch qualifier must stay next to the equation it
    # qualifies. For example, do not detach "otherwise" from the second case.
    ordered = split_conclusions(entry.get("content", ""))[2] if entry.get("content") else []
    ordered = [x for x in ordered if "latex" in x or x.get("text") in notes]
    if [x["latex"] for x in ordered if "latex" in x] != equations:
        ordered = [*({"text": x} for x in notes), *({"latex": x} for x in equations)]
    ordered.extend({"text": x} for x in notes if {"text": x} not in ordered)
    ordered = [({"latex": latex(x["latex"])} if "latex" in x else x) for x in ordered]
    derivation = entry.get("derivation") or {}
    result = {
        "schema": VERSION, "card_id": entry["entry_id"], "concept_key": key, "title": name, "subject": subject,
        "kind": kind, "source_refs": source_refs, "detail_ref": detail_ref,
        "source_version": "",
        "assumptions_latex": assumptions,
        "conclusion_latex": latex(equations[0]), "step_latex": [latex(x) for x in equations[1:]],
        "guard_note": strings(list(dict.fromkeys(limits)), "guards"),
        "qualifiers": strings(notes, "qualifiers"),
        "statement_sequence": ordered,
        "symbol_roles": strings(symbols, "symbols"),
        "trigger": triggers[0] if triggers else "",
        "detail_steps": strings(derivation.get("steps") or entry.get("steps") or [], "detail_steps"),
        "representation_version": VERSION, "scope": scope,
        "allowed_views": sorted(set(allowed_views)), "aliases": sorted(set(aliases)),
    }
    if special:
        result.update(special)
    if not assumptions and entry.get("no_extra_assumptions_reason"):
        result["no_extra_assumptions_reason"] = entry["no_extra_assumptions_reason"]
    result["source_version"] = digest(result)
    return checked_card(result)


def _source_ref(ref):
    return {key: ref[key] for key in ("path", "sha256", "pdf_page", "pdf_pages", "printed_page", "section", "source_kind")
            if ref.get(key) is not None}


def _page_doc(title, body, *, article=True):
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'">'
            f'<title>{escape(title)}</title><style>{CSS}</style><main>'
            + (f'<article>{body}</article>' if article else body) + '</main></html>').encode()


def _math_fields(card, diagram):
    yield (card["conclusion_latex"], True)
    yield from ((x, True) for x in card["step_latex"])
    for row in card["assumptions_latex"]:
        if "latex" in row:
            yield (row["latex"], False)
    fields = [*card["guard_note"], *card["qualifiers"], *card["symbol_roles"], *card["detail_steps"],
              card["trigger"], *(x["label"] for x in card["assumptions_latex"] if "label" in x)]
    for sentence in fields:
        for m in INLINE.finditer(sentence):
            yield (m[1] or m[2], False)
    if diagram:
        yield from ((x, True) for x in diagram["formulas"])
        yield (diagram["primary_formula"], True)


def compile_math(root, requests):
    requests = list(dict.fromkeys(requests))
    if not requests:
        return {}
    rendered = subprocess.run(["node", "-e", NODE, str(root / RENDERER), KATEX_VERSION],
                              input=canonical([(display_tex(expr), block) for expr,block in requests]),
                              capture_output=True, timeout=180, check=True)
    result = json.loads(rendered.stdout)
    if not isinstance(result, list) or len(result) != len(requests):
        raise CardError("incomplete_mathml_render")
    return dict(zip(requests, result))


def source_label(ref):
    path = Path(ref["path"])
    page = ref.get("pdf_page") or (ref.get("pdf_pages") or [None])[0]
    return path.name + (f" · PDF {page}" if page else "") + (f" · {ref['section']}" if ref.get("section") else "")


def _md_inline(text):
    return INLINE.sub(lambda m: "$" + (m[1] or m[2]) + "$", text)


def markdown(card, diagram):
    def blocks(formulas):
        return [line for expr in formulas for line in ("$$", expr, "$$", "")]
    title = card["title"]
    out = [f"# {title}", "", "适用条件", ""]
    for row in card["assumptions_latex"]:
        body = "$" + row["latex"] + "$" if "latex" in row else ""
        out += ["- " + " ".join(x for x in (body, _md_inline(row.get("label", ""))) if x)]
    out.append("")
    for part in card["statement_sequence"]:
        out += (blocks([part["latex"]]) if "latex" in part else [_md_inline(part["text"]), ""])
    if card["trigger"]:
        out += ["触发：" + _md_inline(card["trigger"]), ""]
    out += ["边界：" + _md_inline(x) + "\n" for x in card["guard_note"]]
    if diagram:
        out += ["![经校验的空间投影](diagram.svg)", "",
                "按世界坐标重算，此图只核当前图示构型。", "", *blocks([diagram["primary_formula"]])]
    out += ["<details>", "<summary>展开推导／来源</summary>", "",
            *("- " + _md_inline(x) for x in [*card["symbol_roles"], *card["detail_steps"]]),
            *(blocks(diagram["formulas"]) if diagram else []),
            "", *("- [[" + x["path"] + "|" + source_label(x) + "]]" for x in card["source_refs"]),
            "- [[错题知识网络/公式结论库/专题/" + card["detail_ref"]["topic_id"] + "|原参考条目]]"
            if card["detail_ref"].get("topic_id") else "- 条目：" + card["card_id"], "", "</details>", ""]
    return "\n".join(out).encode()


def html(card, diagram, math):
    def inline(s):
        out, end = [], 0
        for m in INLINE.finditer(s):
            out += [escape(s[end:m.start()]), math[(m[1] or m[2], False)]]
            end = m.end()
        return "".join(out) + escape(s[end:])

    def block(expr):
        return f'<div class="math">{math[(expr, True)]}</div>'

    body = [f'<p class="badge">{escape(card["subject"])} · '
            + ("基础公式" if card["kind"] == "basic_formula" else "二级结论") + '</p>',
            f'<h1>{escape(card["title"])}</h1><section class="condition"><h2>适用条件</h2><ul>']
    for row in card["assumptions_latex"]:
        expr = math[(row["latex"], False)] if "latex" in row else ""
        body.append(f'<li>{expr} {inline(row.get("label", ""))}</li>')
    body.append("</ul></section>")
    sequence = card.get("statement_sequence") or [
        {"latex": x} for x in (card["conclusion_latex"], *card["step_latex"])]
    body += [block(x["latex"]) if "latex" in x else f'<p>{inline(x["text"])}</p>' for x in sequence]
    if card["trigger"]:
        body += [f'<p class="badge">触发：{inline(card["trigger"])}</p>']
    if diagram:
        body += ['<figure><img src="diagram.svg" alt="由精确世界坐标计算的空间正交投影。">'
                 '<figcaption>构图、代数核验和投影视角已分别检查；只核此图构型。</figcaption></figure>']
        if diagram["primary_formula"] not in [x.get("latex") for x in sequence]:
            body += [block(diagram["primary_formula"])]
    if card["guard_note"]:
        body += ['<section class="guard"><h2>边界</h2><ul>',
                 *(f'<li>{inline(x)}</li>' for x in card["guard_note"]), '</ul></section>']
    body += ['<details><summary>展开推导／来源</summary><ul>',
             *(f'<li>{inline(x)}</li>' for x in [*card["symbol_roles"], *card["detail_steps"]]),
             *(f'<li>{escape(source_label(x))}<br><small>{escape(x["path"])}</small></li>' for x in card["source_refs"]),
             f'<li>条目：{escape(card["card_id"])}</li>', '</ul>']
    if diagram:
        body += ["<h2>图中坐标与核验</h2>", *map(block, diagram["formulas"])]
    body.append("</details>")
    return _page_doc(card["title"], "".join(body))


def renderer_proofs(root):
    return [file_proof(root, p, KATEX_SHA if p == RENDERER else None) for p in (
        RENDERER, "错题知识网络/scripts/math_formula_cards.py", "错题知识网络/schema/formula_card_v1.json")]


FORMAL_SECTION = re.compile(r"(?m)^## 可迁移结论[ \t]*$\n(.*?)(?=^## |\Z)", re.S | re.M)
FORMAL_CARD_TITLE = re.compile(r"(?m)^### 公式[：:][ \t]*(.+?)\s*$")
FORMAL_CONDITION = re.compile(r"(?m)^(?:[-*] )?适用条件[：:][ \t]*(.+?)\s*$")
FORMAL_BOUND = re.compile(r"(?m)^(?:[-*] )?边界[：:][ \t]*(.+?)\s*$")


def _formal_formula_sources(root, only):
    """Project explicit formula rows in already-indexed formal explanations.

    The original writer owns the card. The only projection convention is a
    named subheading with visible authored assumptions and display equation(s).
    Legacy prose remains available through its original explanation.
    """
    import math_concept_index as index
    target = root / index.INDEX
    if not target.is_file():
        return {}, {}, {}
    rows, needs, watched = {}, {}, {}
    with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("BEGIN")
        for formal, raw_refs in conn.execute(
                "SELECT id,json_extract(payload,'$.source_refs') FROM records "
                "WHERE json_extract(payload,'$.kind')='personal_card' ORDER BY id"):
            if not re.fullmatch(r"(?:GS|LA|PR)-\d+", formal) or (only and not any(x.startswith("FORMULA-" + formal + "-") for x in only)):
                continue
            refs = json.loads(raw_refs or "[]")
            ref = next((x for x in refs if x["path"].startswith("错题知识网络/错题卡/" + formal + "_")), None)
            if not ref:
                continue
            path = ref["path"]
            try:
                raw = read_bytes(root / relative(path), 2_000_000)
                section = FORMAL_SECTION.search(raw.decode())
            except (OSError, ValueError, UnicodeError):
                continue
            if not section:
                continue
            section = section[1].strip()
            heads = list(FORMAL_CARD_TITLE.finditer(section))
            if not heads:
                if DISPLAY.search(section):
                    needs["FORMAL-" + formal] = _failure("formal_conclusion_needs_explicit_conditions_and_scope", path)
                continue
            try:
                proof = file_proof(root, path, ref["sha256"])
                watched[path] = proof
            except (OSError, ValueError) as exc:
                needs["FORMAL-" + formal] = _failure(str(exc), path)
                continue
            for i, heading in enumerate(heads):
                name = heading[1].strip()
                identity = "FORMULA-" + formal + "-" + digest(name)[:16]
                if only and identity not in only:
                    continue
                part = section[heading.end():heads[i+1].start() if i+1 < len(heads) else len(section)].strip()
                try:
                    condition_rows = FORMAL_CONDITION.findall(part)
                    if not condition_rows:
                        raise CardError("missing_explicit_conditions")
                    guard = FORMAL_BOUND.findall(part)
                    remaining = FORMAL_BOUND.sub("", FORMAL_CONDITION.sub("", part)).strip()
                    formulas, prose, _ = split_conclusions(remaining)
                    if not formulas or SPECIFIC.search(name + "\n" + part):
                        raise CardError("formal_formula_requires_general_reference_and_explicit_math")
                    exact_keys = [k for k, in conn.execute(
                        "SELECT m.key FROM membership m JOIN lookup l ON l.key=m.key "
                        "WHERE m.record_id=? AND l.name=? ORDER BY m.key",
                        (formal, index.normalize(name)))]
                    if len(exact_keys) != 1:
                        raise CardError("formal_formula_needs_exact_concept_match")
                    subject = {"GS": "高等数学", "LA": "线性代数", "PR": "概率论与数理统计"}[formal[:2]]
                    result = _make_card({"entry_id": identity, "conditions": condition_rows, "content": remaining},
                                        key=exact_keys[0], kind="secondary_conclusion",
                                        scope={"type": "general_reference", "stage": "reviewed_reference",
                                               "native_formal_id": formal},
                                        equations=formulas, prose=prose, limits=guard, symbols=[],
                                        source_refs=[_source_ref(ref)], detail_ref={"path": path, "entry_id": identity},
                                        subject=subject, name=name, aliases=[name, exact_keys[0]], triggers=[],
                                        allowed_views=["direct"])
                    if identity in rows:
                        raise CardError("duplicate_formal_formula_identity")
                    rows[identity] = (result, [proof])
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    rows.pop(identity, None)
                    needs[identity] = _failure(str(exc), path, {"name": name})
    return rows, needs, watched


def _inventory(root, only=None):
    raw = read_bytes(root / recap.MANIFEST, recap.MAX_MANIFEST_BYTES)
    source = json.loads(raw)
    if source["schema"] != recap.SCHEMA or source["version"] != recap.manifest_version(source):
        raise CardError("invalid_authoritative_recap_manifest")
    manifest_proof = file_proof(root, recap.MANIFEST, sha(raw))
    known = source["sources"]
    render_proofs = renderer_proofs(root)
    catalog_proofs = [manifest_proof]
    files = {}
    refs = {}
    geom = (read(root / GEOMETRY_INPUT) if (root / GEOMETRY_INPUT).exists() else {})
    if geom and (geom.get("schema") != "math-formula-diagram-bindings-v1"
                 or not isinstance(geom.get("cards"), dict) or not isinstance(geom.get("legacy"), list)):
        raise CardError("invalid_geometry_bindings")
    diagram_definitions = geom.get("cards", {})
    geometry_legacy = geom.get("legacy", [])
    if geom:
        catalog_proofs.append(file_proof(root, GEOMETRY_INPUT))
    descriptor, rejected = {}, {}
    for meta in source["topics"]:
        if only and not (only & set(meta.get("entry_keys", {}))):
            continue
        topic_path = relative(meta["path"])
        if not topic_path.startswith(recap.BASE.as_posix() + "/topics/"):
            raise CardError("unexpected_recap_topic_path")
        try:
            raw = read_bytes(root / topic_path, recap.MAX_TOPIC_BYTES)
            if sha(raw) != meta["sha256"]:
                raise CardError("authoritative_topic_changed")
            topic = recap.validate_topic(json.loads(raw))
            if topic["topic_id"] != meta["topic_id"]:
                raise CardError("authoritative_topic_identity_changed")
            topic_proof = file_proof(root, topic_path, meta["sha256"])
            files[topic_path] = topic_proof
        except (OSError, ValueError, KeyError, TypeError) as exc:
            for identity in meta["entry_keys"]:
                if source["entry_owners"].get(identity) == meta["topic_id"]:
                    rejected[identity] = _failure(str(exc), topic_path)
            continue
        for entry in topic["entries"]:
            identity = entry["entry_id"]
            if entry["section"] not in SECTIONS or only and identity not in only:
                continue
            if source["entry_owners"].get(identity) != topic["topic_id"]:
                raise CardError("wrong_authoritative_entry_owner")
            try:
                scope, formulas, prose, limits, symbols = from_recap(entry, topic)
                source_refs = [_source_ref(r) for r in entry["source_refs"]]
                proofs = proof_many(root, source_refs, refs, known)
                card = _make_card(entry, key=identity, kind=SECTIONS[entry["section"]], scope=scope,
                                  equations=formulas, prose=prose, limits=limits, symbols=symbols,
                                  source_refs=source_refs,
                                  detail_ref={"path": topic_path, "entry_id": identity, "topic_id": topic["topic_id"]},
                                  name=entry["name"], subject=topic["subject"],
                                  aliases=[*entry.get("concept_keys", []), *entry.get("source_record_ids", []),
                                           entry["name"], identity],
                                  triggers=entry.get("triggers", []), allowed_views=entry.get("allowed_views", ["direct"]))
                descriptor[identity] = (card, [topic_proof, *proofs])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                rejected[identity] = _failure(str(exc), topic_path, entry)
    active_manifest = root / registry.MANIFEST
    if active_manifest.exists():
        active = registry.FormulaRegistry(root)
        active_proof = file_proof(root, registry.MANIFEST, active.manifest_sha256)
        catalog_proofs.append(active_proof)
        for shard_id, meta in active.shards.items():
            allowed_ids = {identity for identity, row in active.index.items() if row["shard_id"] == shard_id
                           and identity not in source["entry_owners"] and (not only or identity in only)}
            if not allowed_ids:
                continue
            try:
                rows = active._shard(shard_id)
                proof = file_proof(root, meta["path"], meta["sha256"])
                files[meta["path"]] = proof
            except (OSError, ValueError, KeyError, TypeError) as exc:
                for identity in allowed_ids:
                    rejected[identity] = _failure(str(exc), meta["path"])
                continue
            for identity in sorted(allowed_ids):
                entry = rows[identity]
                try:
                    scope, formulas, prose, guards, symbols = from_registry(entry)
                    source_refs = [_source_ref(ref) for ref in entry["source_refs"]]
                    evidence = proof_many(root, source_refs, refs, known)
                    kind = "secondary_conclusion" if entry["kind"] == "secondary_conclusion" else "basic_formula"
                    subject = entry.get("subject") or ("高等数学" if int(identity[5:7]) < 14 else
                                                       "线性代数" if int(identity[5:7]) < 17 else "概率论与数理统计")
                    card = _make_card(entry, key=identity, kind=kind, scope=scope,
                                      equations=formulas, prose=prose, limits=guards, symbols=symbols,
                                      source_refs=source_refs, detail_ref={"path": meta["path"], "entry_id": identity},
                                      name=entry["title"], subject=subject,
                                      aliases=[entry["title"], identity], triggers=[entry["trigger"]] if entry.get("trigger") else [],
                                      allowed_views=["direct"])
                    descriptor[identity] = (card, [proof, *evidence])
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    rejected[identity] = _failure(str(exc), meta["path"], entry)
    formal, formal_needs, watched = _formal_formula_sources(root, only)
    descriptor.update(formal)
    rejected.update(formal_needs)
    files.update(watched)
    return descriptor, rejected, catalog_proofs, render_proofs, diagram_definitions, geometry_legacy, files, geom.get("exact", {})


def _failure(reason, path, entry=None):
    return {"status": "needs_source_review", "reason": reason, "detail_ref": path,
            "freshness": "stale" if "changed" in reason or "mismatch" in reason else "unresolved",
            **({"title": entry.get("name") or entry.get("title")} if entry else {})}


def _diagram(root, card, definition, cache):
    if not definition:
        return None, [], ("missing_reviewed_coordinates_or_constraints" if GEOMETRIC.search(card["title"]) else None)
    definition = dict(definition)
    refs = definition["source_refs"]
    scope = definition["scope"]
    if (scope != {"type": "reference_example", "stage": "direct"}
            or not refs or any(str(ref["path"]).startswith("真题数据库/") for ref in refs)
            or not set((ref["path"], ref["sha256"]) for ref in refs)
                   <= set((ref["path"], ref["sha256"]) for ref in card["source_refs"]) and
                   not definition.get("reviewed_example")):
        raise CardError("diagram_scope_or_source_not_verified")
    checks = geometry.render(definition, card["assumptions_latex"])
    checks.update(source_refs=refs, scope=scope, objects=definition["objects"])
    own_proofs = [file_proof(root, p) for p in (GEOMETRY_INPUT,
                  "错题知识网络/scripts/math_geometry_projection.py", "错题知识网络/schema/math_diagram_v1.json")]
    return checks, [*own_proofs, *proof_many(root, refs, cache, {})], None


def _exact_diagrams(root, definitions, renderer, reference_proofs):
    """Keep worked configurations out of the catalog and protected views."""
    rows, deps = {}, []
    for identity, data in sorted(definitions.items()):
        scope = data.get("scope", {})
        try:
            if (not re.fullmatch(r"(?:GS|LA|PR)-\d+", identity)
                    or scope.get("type") != "exact_formal_question"
                    or scope.get("formal_id") != identity or scope.get("stage") != "solution"
                    or not strings(scope.get("operations", []), "diagram_operations")
                    or scope.get("attempt_id") is not None):
                raise CardError("exact_diagram_scope_incomplete")
            refs = data["source_refs"]
            if not refs or not any(ref["path"].startswith(f"错题知识网络/错题卡/{identity}_") for ref in refs):
                raise CardError("exact_diagram_missing_same_question")
            assumptions = conditions(data["conditions"])
            if not assumptions:
                raise CardError("exact_diagram_missing_conditions")
            result = geometry.render(data, assumptions)
            formulas = [*(latex(x) for x in data.get("coordinate_definitions", [])), result["primary_formula"]]
            if len(formulas) > 3:
                raise CardError("exact_diagram_requires_compact_visible_math")
            # Reuse the same display condition and TeX path as a generic card.
            render_input = {
                "assumptions_latex": assumptions, "conclusion_latex": formulas[0], "step_latex": formulas[1:],
                "qualifiers": [], "guard_note": [], "symbol_roles": [], "detail_steps": [], "trigger": "",
                "source_refs": refs, "card_id": identity, "title": data["title"], "subject": "高等数学",
                "kind": "secondary_conclusion",
            }
            result.update(source_refs=refs, scope=scope, objects=data["objects"])
            svg = result.pop("svg").encode()
            proof = _dependency_union([*proof_many(root, refs, reference_proofs, {}),
                                       *renderer, *(file_proof(root, p) for p in (
                    GEOMETRY_INPUT, "错题知识网络/scripts/math_geometry_projection.py", "错题知识网络/schema/math_diagram_v1.json"))])
            deps.extend(proof)
            oid = digest([identity, scope, result, sha(svg), [(p["path"],p["sha256"]) for p in proof]])
            path = root / STORE / "guarded" / oid
            requests = list(_math_fields(render_input, result))
            math = compile_math(root, requests)
            if any(math[field] is None for field in requests):
                raise CardError("exact_diagram_mathml_failed")
            body = {
                "index.html": html(render_input, result, math),
                "diagram.svg": svg,
                "diagram.json": canonical(result),
            }
            for name, payload in body.items():
                write(path / name, payload)
            rows[identity] = {"status": "ready", "scope": scope, "dependencies": proof, "object": oid,
                              "artifacts": {name: sha(payload) for name,payload in body.items()},
                              "checks": {k:result[k] for k in ("construction_checks", "conclusion_checks", "visual_checks")}}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            rows[identity] = {"status": "needs_source_review", "reason": str(exc)}
    return rows, deps


def pointer(root):
    try:
        value = read(root / CURRENT, 16_384)
    except FileNotFoundError:
        return None
    if value.get("schema") == POINTER and value.get("status") == "disabled":
        return None
    if (value.get("schema") != POINTER or not recap.SHA.fullmatch(str(value.get("version", "")))
            or not recap.SHA.fullmatch(str(value.get("manifest_sha256", "")))):
        raise CardError("invalid_formula_current_pointer")
    return value


def _where(root, version):
    if not recap.SHA.fullmatch(version):
        raise CardError("invalid_generation")
    return root / STORE / "releases" / version


def _manifest(root, p):
    raw = read_bytes(_where(root, p["version"]) / "release.json")
    if sha(raw) != p["manifest_sha256"]:
        raise CardError("formula_release_manifest_changed")
    value = json.loads(raw)
    if value["schema"] != RELEASE or value["version"] != p["version"]:
        raise CardError("invalid_formula_release")
    return value


def _entry_path(root, version, identity):
    if not recap.ID.fullmatch(identity):
        raise CardError("invalid_entry_id")
    return _where(root, version) / "entries" / (identity + ".json")


def _object_path(root, name):
    if not recap.SHA.fullmatch(name):
        raise CardError("invalid_formula_object_id")
    return root / STORE / "objects" / name


def _validate_stub(root, stub, *, catalog_checked=False):
    state = freshness(root, stub["dependencies"])
    if state["status"] != "current":
        return state["status"]
    # A release-level registry changed? The build has to recheck admission and
    # aliases before the old standalone address can be delivered as current.
    return "current" if catalog_checked else freshness(root, stub["catalog_guards"])["status"]


def lookup(root, identity, *, view="protected", source_entry=None, current_pointer=None, full=False):
    """Resolve one prepared card, fail closed at protected/unknown scope.

    source_entry is supplied only after the normal native question/operation
    and alias/hold checks. A projection never overrides those rules.
    """
    if view not in VIEWS:
        return {"status": "protected"}
    root = Path(root).resolve()
    try:
        p = current_pointer or pointer(root)
        if p is None:
            return {"status": "projection_pending", "reason": "not_installed"}
        stub = read(_entry_path(root, p["version"], identity), 256_000)
        if stub.get("card_id") != identity or stub.get("generation") != p["version"]:
            raise CardError("formula_stub_binding_changed")
        if stub.get("status") != "ready":
            return {"status": "projection_pending", "reason": stub.get("reason", "needs_source_review")}
        if view not in stub["allowed_views"] or stub["scope"]["type"] != "general_reference":
            return {"status": "view_restricted"}
        if source_entry is not None:
            # Native authority has additional rules (matched alias, hold,
            # exact part, admitted variant). Keep those in front of the card.
            if (source_entry["entry_id"] != identity or source_entry.get("matched_alias_scope_restrictions")
                    or source_entry.get("matched_alias_policies")
                    or source_entry.get("question_mapping_rationale_status")
                    or source_entry.get("question_mapping_rationale")):
                return {"status": "native_scope_only"}
        state = _validate_stub(root, stub, catalog_checked=source_entry is not None)
        if state != "current":
            return {"status": "projection_pending", "freshness": state}
        if pointer(root) != p:
            return {"status": "projection_pending", "freshness": "stale"}
        address = _object_path(root, stub["object"])
        result = {"status": "ready", "id": identity, "version": p["version"], "source_version": stub["source_version"]}
        if view == "direct":
            if sha(read_bytes(address / "index.html", 1_500_000)) != stub["artifacts"]["index.html"]:
                raise CardError("formula_html_changed")
            result["card_path"] = (address / "index.html").relative_to(root).as_posix()
        if full:
            raw = read_bytes(address / "card.json", 256_000)
            if sha(raw) != stub["artifacts"]["card.json"]:
                raise CardError("formula_payload_changed")
            card = checked_card(json.loads(raw))
            if card["source_version"] != stub["source_version"] or view not in card["allowed_views"]:
                raise CardError("formula_payload_scope_changed")
            if view == "after_attempt":
                # Only the already-admitted core display, no links to direct
                # pages, attached examples, sources, or hidden detail bodies.
                allowed = ("card_id", "kind", "title", "assumptions_latex", "conclusion_latex",
                           "step_latex", "guard_note", "qualifiers", "statement_sequence", "symbol_roles", "trigger")
                card = {k: card[k] for k in allowed}
            result["card"] = card
        # A different writer could publish while we load the immutable object.
        return result if pointer(root) == p else {"status": "projection_pending", "freshness": "stale"}
    except FileNotFoundError:
        return {"status": "projection_pending", "reason": "no_published_card"}
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "projection_pending", "freshness": "unresolved"}


def annotation(root, entries, view):
    if view not in VIEWS or not entries:
        return
    try:
        current = pointer(root)
    except (OSError, ValueError):
        current = None
    for entry in entries:
        entry["formula_card"] = (lookup(root, entry["entry_id"], view=view, source_entry=entry, current_pointer=current)
                                 if current else {"status": "projection_pending", "reason": "not_installed"})


def _artifacts(path):
    refs = read(path / "artifacts.json", 8192)
    expected = {"card.json", "card.md", "index.html"}
    if not expected <= refs.keys() or not refs.keys() <= expected | {"diagram.svg", "diagram.json"}:
        raise CardError("invalid_formula_artifact_inventory")
    for name, digest_value in refs.items():
        if sha(read_bytes(path / name, 1_500_000)) != digest_value:
            raise CardError("formula_artifact_hash_changed")
    return refs


def _read_release_entry(root, version, identity, row):
    raw = read_bytes(_entry_path(root, version, identity), 256_000)
    if sha(raw) != row["sha256"]:
        raise CardError("staged_formula_entry_changed:" + identity)
    entry = json.loads(raw)
    if (entry.get("card_id") != identity or entry.get("generation") != version
            or entry.get("status") != row["status"] or entry.get("object") != row.get("object")):
        raise CardError("staged_formula_entry_binding_changed:" + identity)
    return entry


def _verify_release_assets(root, release):
    version = release["version"]
    directory = _where(root, version)
    for identity, row in release["rows"].items():
        entry = _read_release_entry(root, version, identity, row)
        if row["status"] == "ready":
            actual = _artifacts(_object_path(root, entry["object"]))
            if actual != entry["artifacts"]:
                raise CardError("staged_formula_artifacts_changed:" + identity)

    for identity, row in release["diagram_projection"].items():
        if row.get("scope", {}).get("type") != "exact_formal_question" or row["status"] != "ready":
            continue
        if not recap.ID.fullmatch(identity) or not recap.SHA.fullmatch(row["object"]):
            raise CardError("invalid_guarded_diagram_identity")
        if read(directory / "diagrams" / (identity + ".json"), 128_000) != row:
            raise CardError("staged_guarded_diagram_receipt_changed:" + identity)
        for name in ("index.html", "diagram.svg", "diagram.json"):
            if sha(read_bytes(root / STORE / "guarded" / row["object"] / name)) != row["artifacts"][name]:
                raise CardError("staged_guarded_diagram_changed:" + identity)

    for name in ("index.md", "index.html"):
        if sha(read_bytes(directory / name)) != release["navigation_hashes"][name]:
            raise CardError("formula_navigation_changed")


def _catalog_pages(rows, root, release, preview):
    def location(stub, filename):
        local = os.path.relpath(_object_path(root, stub["object"]) / filename, release)
        return quote(local, safe="/.")

    groups = defaultdict(list)
    for identity, row in sorted(rows.items()):
        if row["status"] == "ready" and "direct" in row["allowed_views"]:
            groups[row["subject"]].append(row)
    heading = "公式卡验收预览" if preview else "数学公式与二级结论"
    md = [f"# {heading}", "", "适用条件和公式同屏；原始材料仍可查阅。", ""]
    h = [f"<h1>{heading}</h1><p>适用条件、公式与必要边界同屏。这里只是可查参考。</p>"]
    for subject, items in sorted(groups.items()):
        md += [f"## {subject}", ""]
        h += [f"<h2>{escape(subject)} · {len(items)}</h2><ul>"]
        for row in items:
            title = row["title"].replace("[", "［").replace("]", "］").replace("\n", " ")
            md.append(f"- [{title}]({location(row, 'card.md')})")
            h.append(f'<li><a href="{location(row, "index.html")}">{escape(title)}</a></li>')
        h.append("</ul>")
        md.append("")
    return ("\n".join(md).encode(), _page_doc(heading, "".join(h), article=False))


def _dependency_union(refs):
    unique = {}
    for row in refs:
        if row["path"] in unique and unique[row["path"]]["sha256"] != row["sha256"]:
            raise CardError("conflicting_dependency_sha")
        unique[row["path"]] = row
    return [unique[k] for k in sorted(unique)]


def _summarize(started, rows, diagram_rows, transitions):
    counts = Counter(row["status"] for row in rows.values())
    return {"checked_at": started, "coverage": len(rows), "ready": counts["ready"],
            "needs_source_review": counts["needs_source_review"], "failed": counts["failed"],
            "stale": sum(row.get("freshness") == "stale" for row in rows.values()),
            "unresolved": sum(row.get("freshness") == "unresolved" for row in rows.values()),
            "first_built": transitions["first_built"], "rebuilt": transitions["rebuilt"],
            "reused": transitions["reused"],
            "by_subject": dict(Counter(row["subject"] for row in rows.values() if row["status"] == "ready")),
            "diagram_projection": dict(Counter(row["status"] for row in diagram_rows.values())),
            "formal_replay_allowed": False, "learning_write_count": 0}


def _build(root, *, only=None):
    started = now()
    native_version = _native_version(root)
    inputs = _inventory(root, only=only)
    descriptor, rejected, catalogs, renderer, diagrams, legacy, catalog_files, exact = inputs
    before = pointer(root)
    previous = _manifest(root, before) if before else {"rows": {}}
    prepare, math_fields, results, diagram_rows, diagram_cache = {}, [], rejected.copy(), {}, {}
    transitions = Counter()
    for identity, (card, dependencies) in sorted(descriptor.items()):
        diagram = None
        diagram_deps = []
        try:
            diagram, diagram_deps, missing = _diagram(root, card, diagrams.get(identity), diagram_cache)
            if missing:
                diagram_rows[identity] = {"status": "needs_source_review", "reason": missing,
                                          "detail_ref": card["detail_ref"]}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            diagram_rows[identity] = {"status": "needs_source_review", "reason": str(exc),
                                      "detail_ref": card["detail_ref"]}
        if diagram:
            diagram_rows[identity] = {"status": "ready", "checks": {
                k: diagram[k] for k in ("construction_checks", "conclusion_checks", "visual_checks")}}
            card["diagram_ref"] = {"path": "diagram.json", "scope": "direct"}
        specific = _dependency_union([*dependencies, *renderer, *diagram_deps])
        oid = digest([card, [(x["path"], x["sha256"]) for x in renderer],
                      (sha(diagram["svg"].encode()), digest({k: v for k, v in diagram.items() if k != "svg"}))
                      if diagram else None])
        path = _object_path(root, oid)
        try:
            artifacts = _artifacts(path)
            old_row = previous["rows"].get(identity)
            if old_row and old_row["status"] == "ready" and old_row["object"] == oid:
                old_entry = _read_release_entry(root, previous["version"], identity, old_row)
                if artifacts != old_entry["artifacts"]:
                    # A copied object and its sidecar may agree with each other
                    # while disagreeing with the published entry.
                    artifacts = None
        except (OSError, ValueError, KeyError, TypeError):
            artifacts = None
        fields = [] if artifacts else list(_math_fields(card, diagram))
        prepare[identity] = (card, diagram, specific, oid, artifacts, fields)
        math_fields.extend(fields)

    orphan_diagrams = set(diagrams) - set(descriptor) if not only else set()
    for identity in sorted(orphan_diagrams):
        diagram_rows[identity] = {"status": "needs_source_review", "reason": "no_eligible_formula_card"}
    for old in legacy if not only else []:
        identity = old["id"]
        if identity in diagram_rows or not old.get("path") or not old.get("reason"):
            raise CardError("invalid_legacy_geometry_inventory")
        paths = [old["path"], *old.get("additional_paths", [])]
        proofs, absent = [], []
        for path in paths:
            try:
                proofs.append(file_proof(root, path))
            except (OSError, ValueError):
                absent.append(path)
        diagram_rows[identity] = {"status": "needs_source_review", "reason": old["reason"], "source_refs": [
            {k: v for k, v in proof.items() if k != "stat"} for proof in proofs], "unresolved_paths": absent}

    math = compile_math(root, math_fields)
    for identity, (card, diagram, dependencies, oid, artifacts, fields) in prepare.items():
        path = _object_path(root, oid)
        if artifacts is None:
            failures = [i for i, field in enumerate(fields) if math[field] is None]
            if failures:
                results[identity] = _failure("mathml_needs_source_review", card["detail_ref"]["path"],
                                             {"name": card["title"]})
                results[identity]["unrenderable_field_ordinals"] = failures
                if diagram:
                    diagram_rows[identity] = {"status": "needs_source_review", "reason": "diagram_mathml_failed"}
                continue
            try:
                built = {"card.json": canonical(card), "card.md": markdown(card, diagram),
                         "index.html": html(card, diagram, math)}
                if diagram:
                    built["diagram.svg"] = diagram["svg"].encode()
                    built["diagram.json"] = canonical({k:v for k,v in diagram.items() if k != "svg"})
                artifacts = {name: sha(data) for name, data in built.items()}
                for name, data in built.items():
                    write(path / name, data)
                write(path / "artifacts.json", artifacts)
                _artifacts(path)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                results[identity] = {"status": "failed", "reason": str(exc), "title": card["title"],
                                     "detail_ref": card["detail_ref"]["path"], "freshness": "unresolved"}
                continue
            transitions["rebuilt" if previous["rows"].get(identity, {}).get("status") == "ready" else "first_built"] += 1
        else:
            transitions["reused"] += 1
        results[identity] = {"status": "ready", "freshness": "current", "card_id": identity, "object": oid,
                             "title": card["title"], "subject": card["subject"], "source_version": card["source_version"],
                             "dependencies": dependencies, "catalog_guards": catalogs, "allowed_views": card["allowed_views"],
                             "scope": card["scope"], "kind": card["kind"], "artifacts": artifacts,
                             "aliases": card["aliases"]}

    exact_rows, exact_deps = _exact_diagrams(root, exact if not only else {}, renderer, diagram_cache)
    diagram_rows.update(exact_rows)
    dependencies = _dependency_union([*catalogs, *renderer, *catalog_files.values(), *exact_deps,
                                     *(dep for row in results.values() for dep in row.get("dependencies", []))])
    if (freshness(root, dependencies)["status"] != "current" or pointer(root) != before
            or _native_version(root) != native_version):
        raise CardError("formula_inputs_changed_during_build")
    # Stamps enable fast readback but do not change immutable content identity
    # just because an equal-byte file was copied or touched.
    identity = {key: [row.get("object"), row.get("reason"), row.get("status"),
                      [(x["path"],x["sha256"]) for x in row.get("dependencies", [])]]
                for key,row in sorted(results.items())}
    version = digest([VERSION, bool(only), identity, diagram_rows, [(d["path"], d["sha256"]) for d in dependencies]])
    release = _where(root, version)
    release_path = release / "release.json"
    summary = _summarize(started, results, diagram_rows, transitions)
    if release_path.is_file():
        existing = read(release_path)
        if existing["version"] != version:
            raise CardError("formula_release_identity_conflict")
    else:
        rows = {}
        for identity, row in results.items():
            row = {**row, "generation": version, "card_id": identity}
            raw = canonical(row)
            write(_entry_path(root, version, identity), raw)
            rows[identity] = {"status": row["status"], "sha256": sha(raw),
                              **{k:row[k] for k in ("object","reason","freshness","title","subject",
                                                    "allowed_views","aliases","kind") if k in row}}
        for identity, row in exact_rows.items():
            if row["status"] == "ready":
                write(release / "diagrams" / (identity + ".json"), row)
        nav_md, nav_html = _catalog_pages(results, root, release, bool(only))
        write(release / "index.md", nav_md)
        write(release / "index.html", nav_html)
        write(release_path, {"schema": RELEASE, "version": version, "built_at": started,
                             "base_pointer": before["version"] if before else None,
                             "covered_formal_basis": native_version,
                             "preview": bool(only), "rows": rows, "diagram_projection": diagram_rows,
                             "navigation_hashes": {"index.md": sha(nav_md), "index.html": sha(nav_html)},
                             "dependencies": dependencies, "catalog_guards": catalogs,
                             "warnings": {k: v for k,v in results.items() if v["status"] != "ready"},
                             "summary": summary})
    return {"status": "staged", "version": version, "preview": bool(only), "covered_formal_basis": native_version, **summary,
            "release_path": release_path.relative_to(root).as_posix()}


def _install_bindings(root, generation, release):
    """Side table in the existing index. Do not alter any learner/index version."""
    import math_concept_index as index
    target = root / index.INDEX
    if not target.is_file():
        return None
    with (target.parent / "build.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        with closing(index._db(target)) as conn, conn:
            lookup = defaultdict(set)
            for name, key in conn.execute("SELECT l.name,l.key FROM lookup l JOIN concepts c ON c.key=l.key"):
                lookup[name].add(key)
            basis = conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()
            basis = json.loads(basis[0]) if basis else None
            cards = defaultdict(list)
            for identity, row in release["rows"].items():
                if row["status"] != "ready":
                    continue
                exact = set()
                for name in row["aliases"]:
                    hits = lookup.get(index.normalize(name), set())
                    if len(hits) == 1:
                        exact.update(hits)
                for key in exact:
                    for view in row["allowed_views"]:
                        cards[key, view, row["kind"]].append(identity)
            rows = [(generation, key, view, sorted(ids)[0], 0 if kind == "basic_formula" else 1)
                    for (key, view, kind), ids in cards.items()]
            conn.execute("DELETE FROM formula_projection_refs WHERE generation=?", (generation,))
            conn.executemany("INSERT INTO formula_projection_refs(generation,key,view,card_id,ordinal) VALUES (?,?,?,?,?)",
                             rows)
    return {"count": len(rows), "bound_profile_version": basis}


def _release_pointer(root, release, *, note, covered_formal_basis=None):
    version = release["version"]
    raw = read_bytes(_where(root, version) / "release.json")
    if json.loads(raw) != release:
        raise CardError("formula_release_manifest_changed")
    _verify_release_assets(root, release)
    paths = {k: (_where(root, version) / k).relative_to(root).as_posix() for k in ("index.html", "index.md")}
    bindings = _install_bindings(root, version, release)
    if (covered_formal_basis is not None
            and (bindings or {}).get("bound_profile_version") != covered_formal_basis):
        raise CardError("formula_native_index_changed_since_staging")
    dependency_state = freshness(root, release["dependencies"])
    if dependency_state["status"] != "current":
        raise CardError("staged_formula_dependencies_drift:" + dependency_state["status"])
    value = {"schema": POINTER, "version": version, "manifest_sha256": sha(raw), "published_at": now(),
             "native_bindings": bindings, "catalog_guards": release["catalog_guards"], "pages": paths,
             "guarded_diagram_ids": {
                 identity: digest(row) for identity,row in release["diagram_projection"].items()
                 if row.get("scope", {}).get("type") == "exact_formal_question" and row["status"] == "ready"},
             "publication": note}
    write(root / CURRENT, value)
    md = Path(paths["index.md"]).relative_to(STORE)
    page = Path(paths["index.html"]).relative_to(STORE)
    locator = ["# 数学公式与二级结论", "", f"- [打开公式卡]({quote(md.as_posix(), safe='/')})",
               f"- [浏览离线 HTML]({quote(page.as_posix(), safe='/')})",
               "- [[错题知识网络/公式结论库/三段回顾总表|原始三段回顾与来源]]", ""]
    write(root / STORE / "index.md", "\n".join(locator).encode())
    return value


def _publish(root, version, *, rollback=False, previous_version=None, covered_formal_basis=None):
    before = pointer(root)
    release_path = _where(root, version) / "release.json"
    release = read(release_path)
    if release["schema"] != RELEASE or release["version"] != version or release["preview"]:
        raise CardError("invalid_or_preview_formula_release")
    if previous_version is not None and (before or {}).get("version", "") != previous_version:
        raise CardError("formula_pointer_cas_conflict")
    disabled = before is None and (root / CURRENT).is_file()
    if (not rollback and not disabled and (before or {}).get("version") != version
            and (before or {}).get("version") != release["base_pointer"]):
        raise CardError("formula_pointer_changed_since_staging")
    if not release["summary"]["ready"]:
        raise CardError("no_valid_formula_cards")
    basis = None if rollback else (covered_formal_basis or release.get("covered_formal_basis"))
    value = _release_pointer(root, release, note="rollback" if rollback else "activated", covered_formal_basis=basis)
    return {"status": "published", **release["summary"], "freshness": "current", "version": version,
            "previous_version": before["version"] if before else None, "current": value}


def lookup_diagram(root, formal_id, operation, view):
    # This is a presentation convenience after the caller authenticated the
    # current formal identity. No exact assets exist in the generic catalog.
    if view != "direct" or not formal_id or not operation:
        return None
    root = Path(root).resolve()
    try:
        p = pointer(root)
        if p is None or formal_id not in p.get("guarded_diagram_ids", {}):
            return None
        row = read(_where(root, p["version"]) / "diagrams" / (formal_id + ".json"), 128_000)
        scope = row.get("scope", {})
        if (row.get("status") != "ready" or scope.get("formal_id") != formal_id
                or digest(row) != p["guarded_diagram_ids"][formal_id]
                or recap._key(operation) not in {recap._key(x) for x in scope["operations"]}
                or not recap.SHA.fullmatch(row["object"])
                or freshness(root, row["dependencies"])["status"] != "current"):
            return None
        address = root / STORE / "guarded" / row["object"]
        raw = read_bytes(address / "diagram.json", 128_000)
        if (sha(raw) != row["artifacts"]["diagram.json"]
                or sha(read_bytes(address / "index.html", 256_000)) != row["artifacts"]["index.html"]
                or pointer(root) != p):
            return None
        return {"status": "ready", "generation": p["version"], "formal_id": formal_id,
                "path": (address / "index.html").relative_to(root).as_posix()}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def profile_refs(root, conn, key, view, *, current=None):
    if view not in VIEWS or current is None:
        return []
    try:
        requested = conn.execute(
            "SELECT card_id FROM formula_projection_refs WHERE generation=? AND key=? AND view=? ORDER BY ordinal",
            (current["version"], key, view))
        found = []
        for identity, in requested:
            ref = lookup(root, identity, view=view, current_pointer=current)
            if ref["status"] == "ready":
                # Small reference only. A full body goes through exact recap.
                found.append({"id": identity, "source_version": ref["source_version"]})
        return found
    except sqlite3.OperationalError as exc:
        if "no such table: formula_projection_refs" not in str(exc):
            raise
        return []


def _native_version(root):
    import math_concept_index as index
    p = root / index.INDEX
    if not p.is_file():
        return None
    with closing(sqlite3.connect(p.as_uri() + "?mode=ro", uri=True)) as conn:
        value = conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()
        return json.loads(value[0]) if value else None


def refresh(repo_root):
    """Resume only this derived component after a committed native event."""
    root = Path(repo_root).resolve()
    if not (root / recap.MANIFEST).is_file():
        return {"status": "NOT_APPLICABLE", "reason": "no_recap_registry", "formal_replay_allowed": False}
    with lock(root):
        p = pointer(root)
        if p is None and (root / CURRENT).is_file() and read(root / CURRENT).get("status") == "disabled":
            return {"status": "NOT_APPLICABLE", "reason": "display_rolled_back", "formal_replay_allowed": False}
        native_version = _native_version(root)
        if p:
            published = _manifest(root, p)
            state = freshness(root, published["dependencies"])
            if (state["status"] == "current" and not published["summary"]["failed"]
                    and (p.get("native_bindings") or {}).get("bound_profile_version") == native_version):
                try:
                    _verify_release_assets(root, published)
                except (OSError, ValueError, KeyError, TypeError):
                    # The sources certify what to render. They do not certify
                    # that the generated files survived a copy or cleanup.
                    pass
                else:
                    older = published["summary"]
                    return {**older, "status": "READY", "version": p["version"],
                            "manifest_sha256": p["manifest_sha256"], "reused": older["ready"],
                            "first_built": 0, "rebuilt": 0, "freshness": "current"}
        built = _build(root)
        if built["failed"]:
            return {**built, "status": "PENDING", "reason": "formula_asset_write_failed"}
        if p and built["version"] == p["version"] and state["status"] == "current":
            current = _release_pointer(root, published, note="bindings_refreshed",
                                       covered_formal_basis=built["covered_formal_basis"])
            return {**built, "status": "READY", "manifest_sha256": current["manifest_sha256"],
                    "freshness": "current"}
        done = _publish(root, built["version"], covered_formal_basis=built["covered_formal_basis"])
        return {**done, "status": "READY", "manifest_sha256": done["current"]["manifest_sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    preview = sub.add_parser("build")
    preview.add_argument("--id", action="append", default=[])
    plan = sub.add_parser("plan")
    plan.add_argument("--id", action="append", default=[])
    for command in ("publish", "rollback"):
        p = sub.add_parser(command)
        p.add_argument("--version", required=True)
        p.add_argument("--if-current")
    off = sub.add_parser("deactivate", help="Return to the existing reference view without deleting anything")
    off.add_argument("--if-current", required=True)
    sub.add_parser("refresh")
    reader = sub.add_parser("query")
    reader.add_argument("--id", required=True)
    reader.add_argument("--view", choices=("protected", "after_attempt", "direct"), default="protected")
    args = parser.parse_args()
    root = args.repo.resolve()
    try:
        if args.command == "status":
            p = pointer(root)
            if p:
                release = _manifest(root, p)
                result = {**release["summary"], "status": "published", "current": p,
                          "freshness": freshness(root, release["dependencies"])}
            else:
                result = {"status": "disabled" if (root / CURRENT).is_file() else "not_installed"}
        elif args.command == "query":
            result = lookup(root, args.id, view=args.view, full=True)
        elif args.command == "plan":
            cards, rejected, catalogs, _, diagrams, legacy, _, exact = _inventory(root, set(args.id) or None)
            result = {"status": "planned", "source_manifests": catalogs, "coverage": len(cards) + len(rejected),
                      "eligible_for_layout": len(cards), "needs_source_review": rejected,
                      "geometry_bindings": sorted(diagrams), "guarded_geometry_bindings": sorted(exact),
                      "legacy_geometry": legacy}
        elif args.command == "refresh":
            result = refresh(root)
        elif args.command == "build":
            with lock(root):
                result = _build(root, only=set(args.id) or None)
        elif args.command == "deactivate":
            with lock(root):
                previous = pointer(root)
                if not previous or previous["version"] != args.if_current:
                    raise CardError("formula_pointer_cas_conflict")
                write(root / CURRENT, {"schema": POINTER, "status": "disabled",
                                      "retained_version": previous["version"], "changed_at": now()})
                write(root / STORE / "index.md",
                      "# 数学公式资料\n\n[[错题知识网络/公式结论库/三段回顾总表|打开原三段回顾资料]]\n".encode())
                result = {"status": "disabled", "retained_version": previous["version"],
                          "formal_replay_allowed": False}
        else:
            with lock(root):
                result = _publish(root, args.version, rollback=args.command == "rollback",
                                  previous_version=args.if_current)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        result = {"status": "error", "reason": str(exc), "formal_replay_allowed": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result["status"] == "error")


if __name__ == "__main__":
    raise SystemExit(main())
