#!/usr/bin/env python3
"""Safely normalize visual-detail math for Obsidian.

The migration is deliberately two-phase. The plan command verifies every
frozen preimage and writes deterministic candidates. The apply command is a
serial writer with an optimistic per-file SHA-256 lock. Verify proves the
applied state and idempotency. Rollback only restores a file when its current
bytes still equal the recorded postimage.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator, Sequence


SUBJECTS = ("高等数学", "线性代数", "概率论与数理统计")
VISUAL_ROOT = Path("错题知识网络/可视化错题详情")
DEFAULT_RUN_ROOT = Path(".codex_tmp/visual_math_migration_20260801")
BACKTICK = chr(96)
TOKEN_OPEN = "\ue000VM"
TOKEN_CLOSE = "\ue001"


class MigrationError(RuntimeError):
    """A deterministic migration or validation failure."""


@dataclasses.dataclass(frozen=True)
class Fragment:
    kind: str
    raw: str


@dataclasses.dataclass
class TransformStats:
    legacy_inline_pairs: int = 0
    legacy_display_pairs: int = 0
    parent_lines_structured: int = 0
    parent_lines_high_confidence: int = 0
    parent_lines_low_confidence: int = 0
    flattened_lines_structured: int = 0
    display_delimiters_reflowed: int = 0
    heading_markers_structured: int = 0
    separators_reflowed: int = 0
    list_markers_reflowed: int = 0
    table_rows_reflowed: int = 0
    horizontal_rule_blank_lines_added: int = 0
    explicit_repairs: int = 0

    def add(self, other: "TransformStats") -> None:
        for field in dataclasses.fields(self):
            name = field.name
            setattr(self, name, getattr(self, name) + getattr(other, name))


@dataclasses.dataclass(frozen=True)
class Repair:
    repair_id: str
    old: str
    new: str
    evidence: str


def _repair_map() -> dict[str, tuple[Repair, ...]]:
    """Public export: private card-specific repair text is not distributed."""
    return {}


EXPLICIT_REPAIRS = _repair_map()

KNOWN_OUT_OF_SCOPE_TRUNCATIONS = ()  # Public export: no private card inventory.


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")


def jsonl_write(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def jsonl_read(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def split_frontmatter(raw: bytes) -> tuple[bytes, bytes]:
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].rstrip(b"\r\n") != b"---":
        return b"", raw
    for index in range(1, len(lines)):
        if lines[index].rstrip(b"\r\n") == b"---":
            return b"".join(lines[: index + 1]), b"".join(lines[index + 1 :])
    raise MigrationError("frontmatter opener has no closing delimiter")


def is_escaped(text: str, index: int) -> bool:
    slash_count = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        slash_count += 1
        cursor -= 1
    return slash_count % 2 == 1


def find_unescaped(text: str, token: str, start: int, stop_at_newline: bool = False) -> int:
    cursor = start
    while True:
        found = text.find(token, cursor)
        if found < 0:
            return -1
        if stop_at_newline and "\n" in text[start:found]:
            return -1
        if not is_escaped(text, found):
            return found
        cursor = found + 1


def _fence_match(line: str) -> re.Match[str] | None:
    return re.match(r"^(?:[ \t]*>[ \t]*)*[ \t]*(" + re.escape(BACKTICK) + r"{3,}|~{3,})", line)


def split_fenced_chunks(text: str) -> Iterator[tuple[bool, str]]:
    in_fence = False
    fence_char = ""
    fence_length = 0
    current: list[str] = []
    current_protected: bool | None = None
    for line in text.splitlines(keepends=True):
        match = _fence_match(line)
        protected = in_fence or match is not None
        if current_protected is None:
            current_protected = protected
        if protected != current_protected:
            yield current_protected, "".join(current)
            current = []
            current_protected = protected
        current.append(line)
        if match:
            marker = match.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                in_fence = False
                fence_char = ""
                fence_length = 0
    if current:
        yield bool(current_protected), "".join(current)


def _consume_protected(text: str, index: int, include_math: bool = True) -> tuple[int, str] | None:
    if text.startswith("![[", index) or text.startswith("[[", index):
        end = text.find("]]", index + 2)
        if end >= 0:
            return end + 2, "wikilink"
    if text.startswith("https://", index) or text.startswith("http://", index):
        match = re.match(r"https?://[^\s<>]+", text[index:])
        if match:
            return index + len(match.group(0)), "url"
    if text[index] == BACKTICK:
        run = 1
        while index + run < len(text) and text[index + run] == BACKTICK:
            run += 1
        marker = BACKTICK * run
        end = text.find(marker, index + run)
        if end >= 0:
            return end + run, "code"
    if include_math and text[index] == "$" and not is_escaped(text, index):
        if text.startswith("$$", index):
            end = find_unescaped(text, "$$", index + 2)
            if end >= 0:
                return end + 2, "display_math"
        else:
            end = find_unescaped(text, "$", index + 1, stop_at_newline=True)
            if end >= 0 and not text.startswith("$$", end):
                return end + 1, "inline_math"
    return None


def protect_fragments(text: str, include_math: bool = True) -> tuple[str, list[Fragment]]:
    fragments: list[Fragment] = []
    output: list[str] = []
    cursor = 0
    while cursor < len(text):
        consumed = _consume_protected(text, cursor, include_math=include_math)
        if consumed:
            end, kind = consumed
            token = f"{TOKEN_OPEN}{len(fragments)}{TOKEN_CLOSE}"
            fragments.append(Fragment(kind, text[cursor:end]))
            output.append(token)
            cursor = end
            continue
        output.append(text[cursor])
        cursor += 1
    return "".join(output), fragments


def restore_fragments(text: str, fragments: Sequence[Fragment]) -> str:
    for index, fragment in enumerate(fragments):
        text = text.replace(f"{TOKEN_OPEN}{index}{TOKEN_CLOSE}", fragment.raw)
    return text


def apply_explicit_repairs(relpath: str, body: str) -> tuple[str, list[dict[str, str]]]:
    applied: list[dict[str, str]] = []
    for repair in EXPLICIT_REPAIRS.get(relpath, ()):
        count = body.count(repair.old)
        if count == 0:
            if repair.new in body:
                continue
            normalized_new, _repair_stats = convert_legacy_math(repair.new)
            normalized_new_stream = canonical_content_stream(normalized_new)
            if normalized_new_stream and normalized_new_stream in canonical_content_stream(body):
                continue
            raise MigrationError(f"{repair.repair_id}: expected source text not found")
        if count != 1:
            raise MigrationError(f"{repair.repair_id}: expected one source match, got {count}")
        body = body.replace(repair.old, repair.new, 1)
        applied.append(
            {
                "repair_id": repair.repair_id,
                "evidence": repair.evidence,
                "old_sha256": sha256_bytes(repair.old.encode()),
                "new_sha256": sha256_bytes(repair.new.encode()),
            }
        )
    return body, applied


def convert_legacy_math_plain(text: str) -> tuple[str, TransformStats]:
    stats = TransformStats()
    output: list[str] = []
    cursor = 0
    while cursor < len(text):
        consumed = _consume_protected(text, cursor, include_math=True)
        if consumed:
            end, _kind = consumed
            output.append(text[cursor:end])
            cursor = end
            continue
        if text.startswith(r"\(", cursor) and not is_escaped(text, cursor):
            end = find_unescaped(text, r"\)", cursor + 2, stop_at_newline=True)
            if end < 0:
                line = text.count("\n", 0, cursor) + 1
                raise MigrationError(f"unclosed legacy inline math at body line {line}")
            output.extend(("$", text[cursor + 2 : end], "$"))
            stats.legacy_inline_pairs += 1
            cursor = end + 2
            continue
        if text.startswith(r"\[", cursor) and not is_escaped(text, cursor):
            end = find_unescaped(text, r"\]", cursor + 2)
            if end < 0:
                line = text.count("\n", 0, cursor) + 1
                raise MigrationError(f"unclosed legacy display math at body line {line}")
            output.extend(("$$", text[cursor + 2 : end], "$$"))
            stats.legacy_display_pairs += 1
            cursor = end + 2
            continue
        output.append(text[cursor])
        cursor += 1
    return "".join(output), stats


def convert_legacy_math(text: str) -> tuple[str, TransformStats]:
    output: list[str] = []
    total = TransformStats()
    for protected, chunk in split_fenced_chunks(text):
        if protected:
            output.append(chunk)
            continue
        converted, stats = convert_legacy_math_plain(chunk)
        output.append(converted)
        total.add(stats)
    return "".join(output), total


def _fragment_tokens(masked: str) -> list[int]:
    return [int(value) for value in re.findall(re.escape(TOKEN_OPEN) + r"(\d+)" + re.escape(TOKEN_CLOSE), masked)]


def _has_math(masked_segment: str, fragments: Sequence[Fragment]) -> bool:
    return any(fragments[index].kind in {"inline_math", "display_math"} for index in _fragment_tokens(masked_segment))


def _content_sentinel(masked_segment: str, fragments: Sequence[Fragment]) -> tuple[bool, str]:
    restored = restore_fragments(masked_segment, fragments)
    structural = bool(
        re.search(r"(?<!#)#{1,6}\s+", masked_segment)
        or re.search(r"(?:^|\s)---(?:\s|$)", masked_segment)
        or re.search(r"\|\s*:?-{2,}", masked_segment)
    )
    has_math = _has_math(masked_segment, fragments)
    if structural:
        return True, "high"
    if has_math and len(restored) >= 120:
        return True, "low"
    return False, ""


HEADING_BODY_CUE = re.compile(
    r"[ \t]+(?=(?:若|设|当|这里|其中|通过|遇到|见到|欲证|令|本题|题目|题型|曲线|"
    r"由于|因为|为了|说明|即如果|可先|应先|先|核心|目标|公式内容|使用条件|"
    r"标准答案|正确入口|这次|求导|两边|又因为|则有|从而|特别地|例如|常用于|表示))"
)


def _heading_title_split(content: str, fragments: Sequence[Fragment]) -> tuple[str, str]:
    boundaries: list[int] = []
    newline = content.find("\n")
    if newline >= 0:
        boundaries.append(newline)
    pipe = content.find("|")
    if pipe >= 0:
        boundaries.append(pipe)
    for index, fragment in enumerate(fragments):
        if fragment.kind != "display_math":
            continue
        token_position = content.find(f"{TOKEN_OPEN}{index}{TOKEN_CLOSE}")
        if token_position >= 0:
            boundaries.append(token_position)
    for pattern in (
        re.compile(r"[ \t]+[-*][ \t]+(?=\S)"),
        re.compile(r"[ \t]+(?=(?:\d+[.)、]|[①②③④⑤⑥⑦⑧⑨⑩])[ \t]+)"),
        HEADING_BODY_CUE,
    ):
        match = pattern.search(content)
        if match and match.start() > 1:
            boundaries.append(match.start())
    if boundaries:
        boundary = min(boundaries)
        return content[:boundary].strip(), content[boundary:].strip()
    stripped = content.strip()
    if len(restore_fragments(stripped, fragments)) <= 120:
        return stripped, ""
    sentence = re.search(r"[。！？][ \t]+", stripped)
    if sentence and sentence.end() <= 120:
        return stripped[: sentence.end()].strip(), stripped[sentence.end() :].strip()
    return "", stripped


def _render_flattened_headings(masked: str, fragments: Sequence[Fragment], stats: TransformStats) -> str:
    heading_pattern = re.compile(r"(?<!#)(#{1,6})\s+")
    matches = list(heading_pattern.finditer(masked))
    if not matches:
        return masked
    output: list[str] = [masked[: matches[0].start()]]
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(masked)
        content = masked[match.end() : end]
        title, body = _heading_title_split(content, fragments)
        if title:
            level = min(6, 3 + len(match.group(1)))
            output.append("\n\n" + "#" * level + " " + title)
            if body:
                output.append("\n\n" + body)
        else:
            output.append("\n\n" + body)
        stats.heading_markers_structured += 1
    return "".join(output)


def _reflow_flattened_lists(masked: str, stats: TransformStats) -> str:
    output: list[str] = []
    token_prefix = re.escape(TOKEN_OPEN)
    # Preserve empty structural lines. splitlines() drops the empty line that
    # separates a paragraph from `---`, which makes CommonMark/Obsidian parse
    # the rule as a Setext H2 underline instead of a horizontal rule.
    for line in masked.split("\n"):
        if line.lstrip().startswith("#"):
            output.append(line)
            continue
        bullet_pattern = re.compile(r"[ \t]+([-*])[ \t]+(?=\S)")
        bullet_count = len(bullet_pattern.findall(line))
        line = bullet_pattern.sub(lambda match: "\n" + match.group(1) + " ", line)
        tight_bullet = re.compile(r"(?<=[)）])-[ \t]+(?=" + token_prefix + r")")
        tight_count = len(tight_bullet.findall(line))
        line = tight_bullet.sub("\n- ", line)
        ordered_pattern = re.compile(
            r"[ \t]+(?=(?:\d+[.)、]|[①②③④⑤⑥⑦⑧⑨⑩])[ \t]+)"
        )
        ordered_count = len(ordered_pattern.findall(line))
        line = ordered_pattern.sub("\n", line)
        stats.list_markers_reflowed += bullet_count + tight_count + ordered_count
        output.extend(line.split("\n"))
    return "\n".join(output)


def structure_flattened_source(text: str, stats: TransformStats) -> str:
    masked, fragments = protect_fragments(text, include_math=True)
    separator_pattern = re.compile(r"\s+---\s+")
    separator_count = len(separator_pattern.findall(masked))
    masked = separator_pattern.sub("\n\n---\n\n", masked)
    table_row_pattern = re.compile(r"\|[ \t]+\|")
    table_row_count = len(table_row_pattern.findall(masked))
    masked = table_row_pattern.sub("|\n|", masked)
    masked = _render_flattened_headings(masked, fragments, stats)
    masked = _reflow_flattened_lists(masked, stats)
    stats.separators_reflowed += separator_count
    stats.table_rows_reflowed += table_row_count
    restored = restore_fragments(masked, fragments)
    lines = [line.rstrip() for line in restored.splitlines()]
    compact: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if compact and not blank:
                compact.append("")
            blank = True
        else:
            compact.append(line.strip())
            blank = False
    while compact and not compact[-1]:
        compact.pop()
    spaced: list[str] = []
    for line in compact:
        if line.strip() == "---":
            if spaced and spaced[-1] != "":
                spaced.append("")
            spaced.append("---")
            spaced.append("")
        else:
            if line == "" and spaced and spaced[-1] == "":
                continue
            spaced.append(line)
    while spaced and not spaced[-1]:
        spaced.pop()
    return "\n".join(spaced)


def format_parent_line(line: str, stats: TransformStats) -> str:
    match = re.match(r"^([ \t]*)- 父级路径：(.*?)(\r?\n)?$", line, re.S)
    if not match:
        return line
    indent, rest, newline = match.group(1), match.group(2), match.group(3) or ""
    masked, fragments = protect_fragments(rest, include_math=True)
    if not any(fragment.kind in {"inline_math", "display_math"} for fragment in fragments):
        return line
    segments = masked.split(" > ")
    if len(segments) < 4:
        return line
    content_index = -1
    confidence = ""
    for index, segment in enumerate(segments):
        sentinel, level = _content_sentinel(segment, fragments)
        if sentinel and index >= 3:
            content_index = index
            confidence = level
            break
    if content_index < 0:
        return line
    path_segments = [restore_fragments(segment, fragments).strip() for segment in segments[:content_index]]
    content_segments = [restore_fragments(segment, fragments).strip() for segment in segments[content_index:]]
    content = structure_flattened_source("\n\n".join(content_segments), stats)
    result = (
        f"{indent}### 父级路径\n\n"
        f"{indent}{' → '.join(path_segments)}\n\n"
        f"{indent}### 上级知识条目\n\n"
        f"{content}"
    )
    stats.parent_lines_structured += 1
    if confidence == "high":
        stats.parent_lines_high_confidence += 1
    else:
        stats.parent_lines_low_confidence += 1
    return result + newline


def format_parent_lines(text: str, stats: TransformStats) -> str:
    return "".join(format_parent_line(line, stats) for line in text.splitlines(keepends=True))


def _same_line_display_count(line: str) -> int:
    _masked, fragments = protect_fragments(line, include_math=True)
    return sum(fragment.kind == "display_math" for fragment in fragments)


def structure_nonparent_flattened_lines(text: str, stats: TransformStats) -> str:
    output: list[str] = []
    for line in text.splitlines(keepends=True):
        newline = "\n" if line.endswith("\n") else ""
        core = line[:-1] if newline else line
        if core.endswith("\r"):
            core = core[:-1]
            newline = "\r\n" if newline else "\r"
        prefix, content = _quote_prefix(core)
        display_count = _same_line_display_count(content)
        structural = bool(re.search(r"(?<!#)#{1,6}\s+", content) or re.search(r"\s+---\s+", content))
        if display_count >= 1 and structural and not content.lstrip().startswith("- 父级路径："):
            transformed_content = structure_flattened_source(content, stats)
            if transformed_content != content:
                stats.flattened_lines_structured += 1
            if prefix:
                blank_prefix = _blank_for_prefix(prefix)
                transformed = "\n".join(
                    prefix + transformed_line if transformed_line else blank_prefix
                    for transformed_line in transformed_content.splitlines()
                )
            else:
                transformed = transformed_content
            output.append(transformed + newline)
        else:
            output.append(line)
    return "".join(output)


def _display_delimiter_positions(text: str) -> list[int]:
    positions: list[int] = []
    cursor = 0
    while cursor < len(text):
        if text.startswith("![[", cursor) or text.startswith("[[", cursor):
            end = text.find("]]", cursor + 2)
            if end >= 0:
                cursor = end + 2
                continue
        if text.startswith("https://", cursor) or text.startswith("http://", cursor):
            match = re.match(r"https?://[^\s<>]+", text[cursor:])
            if match:
                cursor += len(match.group(0))
                continue
        if text[cursor] == BACKTICK:
            run = 1
            while cursor + run < len(text) and text[cursor + run] == BACKTICK:
                run += 1
            marker = BACKTICK * run
            end = text.find(marker, cursor + run)
            if end >= 0:
                cursor = end + run
                continue
        if text.startswith("$$", cursor) and not is_escaped(text, cursor):
            positions.append(cursor)
            cursor += 2
            continue
        if text[cursor] == "$" and not is_escaped(text, cursor):
            end = find_unescaped(text, "$", cursor + 1, stop_at_newline=True)
            if end >= 0 and not text.startswith("$$", end):
                cursor = end + 1
                continue
        cursor += 1
    return positions


def _quote_prefix(line: str) -> tuple[str, str]:
    match = re.match(r"^([ \t]*(?:(?:>[ \t]?)+)?)(.*)$", line, re.S)
    if not match:
        return "", line
    return match.group(1), match.group(2)


def _blank_for_prefix(prefix: str) -> str:
    if ">" not in prefix:
        return ""
    last = prefix.rfind(">")
    return prefix[: last + 1].rstrip()


def _line_core(line: str) -> str:
    return line[:-2] if line.endswith("\r\n") else line[:-1] if line.endswith(("\n", "\r")) else line


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def _protected_fence_lines(lines: Sequence[str]) -> list[bool]:
    protected: list[bool] = []
    in_fence = False
    fence_char = ""
    fence_length = 0
    for line in lines:
        match = _fence_match(line)
        protected.append(in_fence or match is not None)
        if match:
            marker = match.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                in_fence = False
                fence_char = ""
                fence_length = 0
    return protected


def _is_blank_at_quote_depth(line: str, expected: str) -> bool:
    return _line_core(line).strip() == expected.strip()


def horizontal_rule_spacing_errors(text: str) -> list[tuple[int, str, str]]:
    lines = text.splitlines(keepends=True)
    protected = _protected_fence_lines(lines)
    errors: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        if protected[index]:
            continue
        prefix, content = _quote_prefix(_line_core(line))
        if content.strip() != "---":
            continue
        expected = _blank_for_prefix(prefix)
        if index == 0 or not _is_blank_at_quote_depth(lines[index - 1], expected):
            errors.append((index + 1, "before", _line_core(line)))
        # At EOF there is no following paragraph to separate, so a trailing
        # blank line is unnecessary and would fail `git diff --check`.
        if index + 1 < len(lines) and not _is_blank_at_quote_depth(lines[index + 1], expected):
            errors.append((index + 1, "after", _line_core(line)))
    return errors


def normalize_horizontal_rule_spacing(text: str, stats: TransformStats) -> str:
    lines = text.splitlines(keepends=True)
    if not lines:
        return text
    protected = _protected_fence_lines(lines)
    output: list[str] = []
    default_newline = "\r\n" if "\r\n" in text else "\n"
    for index, line in enumerate(lines):
        if protected[index]:
            output.append(line)
            continue
        prefix, content = _quote_prefix(_line_core(line))
        if content.strip() != "---":
            output.append(line)
            continue
        expected = _blank_for_prefix(prefix)
        newline = _line_ending(line) or default_newline
        if not output or not _is_blank_at_quote_depth(output[-1], expected):
            output.append(expected + newline)
            stats.horizontal_rule_blank_lines_added += 1
        output.append(line if _line_ending(line) else line + newline)
        next_exists = index + 1 < len(lines)
        next_is_valid = next_exists and _is_blank_at_quote_depth(lines[index + 1], expected)
        if next_exists and not next_is_valid:
            output.append(expected + newline)
            stats.horizontal_rule_blank_lines_added += 1
    return "".join(output)


def normalize_display_layout(text: str, stats: TransformStats) -> str:
    output: list[str] = []
    in_display = False
    for protected, chunk in split_fenced_chunks(text):
        if protected:
            output.append(chunk)
            continue
        for original_line in chunk.splitlines(keepends=True):
            newline = "\n" if original_line.endswith("\n") else ""
            line = original_line[:-1] if newline else original_line
            if line.endswith("\r"):
                line = line[:-1]
                newline = "\r\n" if newline else "\r"
            prefix, content = _quote_prefix(line)
            positions = _display_delimiter_positions(content)
            if not positions:
                output.append(original_line)
                continue
            if len(positions) == 1 and not content[: positions[0]].strip() and not content[positions[0] + 2 :].strip():
                output.append(original_line)
                in_display = not in_display
                continue
            pieces: list[str] = []
            cursor = 0
            state = in_display
            for position in positions:
                segment = content[cursor:position]
                if segment.strip():
                    pieces.append(prefix + segment.strip())
                if not state and pieces and pieces[-1] != _blank_for_prefix(prefix):
                    pieces.append(_blank_for_prefix(prefix))
                pieces.append(prefix + "$$")
                state = not state
                stats.display_delimiters_reflowed += 1
                if not state:
                    pieces.append(_blank_for_prefix(prefix))
                cursor = position + 2
            tail = content[cursor:]
            if tail.strip():
                pieces.append(prefix + tail.strip())
            compact: list[str] = []
            for piece in pieces:
                if piece == "" and compact and compact[-1] == "":
                    continue
                if piece == _blank_for_prefix(prefix) and compact and compact[-1] == piece:
                    continue
                compact.append(piece)
            while compact and compact[-1] == _blank_for_prefix(prefix) and not tail.strip():
                compact.pop()
            output.append(newline.join(compact) + newline)
            in_display = state
    if in_display:
        raise MigrationError("unclosed modern display math after layout normalization")
    return "".join(output)


def collect_modern_math(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    formulas: list[tuple[str, str]] = []
    errors: list[str] = []
    for protected, chunk in split_fenced_chunks(text):
        if protected:
            continue
        cursor = 0
        while cursor < len(chunk):
            consumed = _consume_protected(chunk, cursor, include_math=False)
            if consumed:
                cursor = consumed[0]
                continue
            if chunk.startswith("$$", cursor) and not is_escaped(chunk, cursor):
                end = find_unescaped(chunk, "$$", cursor + 2)
                if end < 0:
                    errors.append(f"unclosed display at offset {cursor}")
                    break
                formulas.append(("display", chunk[cursor + 2 : end]))
                cursor = end + 2
                continue
            if chunk[cursor] == "$" and not is_escaped(chunk, cursor):
                end = find_unescaped(chunk, "$", cursor + 1, stop_at_newline=True)
                if end < 0:
                    errors.append(f"unclosed inline at offset {cursor}")
                    cursor += 1
                    continue
                if chunk.startswith("$$", end):
                    cursor += 1
                    continue
                formulas.append(("inline", chunk[cursor + 1 : end]))
                cursor = end + 1
                continue
            cursor += 1
    return formulas, errors


def normalize_formula_payload(kind: str, payload: str) -> tuple[str, str]:
    lines = []
    for line in payload.splitlines() or [payload]:
        lines.append(re.sub(r"^[ \t]*>[ \t]?", "", line))
    return kind, re.sub(r"\s+", " ", "\n".join(lines)).strip()


def formula_signature(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    formulas, errors = collect_modern_math(text)
    return [normalize_formula_payload(kind, payload) for kind, payload in formulas], errors


def protected_mask(text: str, include_math: bool = True) -> str:
    output: list[str] = []
    for protected, chunk in split_fenced_chunks(text):
        if protected:
            output.append("".join("\n" if char == "\n" else " " for char in chunk))
            continue
        masked, _fragments = protect_fragments(chunk, include_math=include_math)
        masked = re.sub(
            re.escape(TOKEN_OPEN) + r"\d+" + re.escape(TOKEN_CLOSE),
            lambda match: " " * len(match.group(0)),
            masked,
        )
        output.append(masked)
    return "".join(output)


def legacy_tokens_outside_protected(text: str) -> list[str]:
    masked = protected_mask(text, include_math=True)
    return re.findall(r"(?<!\\)\\(?:[()[\]])", masked)


def double_escaped_inline_tokens(text: str) -> list[str]:
    masked = protected_mask(text, include_math=True)
    return re.findall(r"(?<!\\)\\\\[()]", masked)


def protected_legacy_occurrences(text: str) -> list[dict[str, object]]:
    occurrences: list[dict[str, object]] = []
    single_pattern = re.compile(r"(?<!\\)\\(?:[()[\]])")
    double_inline_pattern = re.compile(r"(?<!\\)\\\\[()]")
    for fenced, chunk in split_fenced_chunks(text):
        if fenced:
            tokens = single_pattern.findall(chunk) + double_inline_pattern.findall(chunk)
            if tokens:
                occurrences.append(
                    {
                        "kind": "fenced_code",
                        "token_count": len(tokens),
                        "fragment_sha256": sha256_bytes(chunk.encode("utf-8")),
                    }
                )
            continue
        _masked, fragments = protect_fragments(chunk, include_math=True)
        for fragment in fragments:
            tokens = single_pattern.findall(fragment.raw) + double_inline_pattern.findall(fragment.raw)
            if not tokens:
                continue
            occurrences.append(
                {
                    "kind": fragment.kind,
                    "token_count": len(tokens),
                    "fragment_sha256": sha256_bytes(fragment.raw.encode("utf-8")),
                }
            )
    return occurrences


def bare_latex_outside_math(text: str) -> list[str]:
    masked = protected_mask(text, include_math=True)
    return re.findall(r"(?<!\\)\\[A-Za-z]+", masked)


def nonexclusive_display_delimiter_lines(text: str) -> list[tuple[int, str]]:
    invalid: list[tuple[int, str]] = []
    line_number = 0
    for protected, chunk in split_fenced_chunks(text):
        for line in chunk.splitlines():
            line_number += 1
            if protected:
                continue
            _prefix, content = _quote_prefix(line)
            positions = _display_delimiter_positions(content)
            if not positions:
                continue
            if len(positions) != 1 or content[: positions[0]].strip() or content[positions[0] + 2 :].strip():
                invalid.append((line_number, line))
    return invalid


def token_signature(text: str) -> dict[str, list[str]]:
    return {
        "wikilinks": re.findall(r"!?\[\[[^\]\n]+\]\]", text),
        "callouts": re.findall(r"(?m)^[ \t]*>[ \t]*\[![^\]\n]+\][+-]?", text),
        "urls": re.findall(r"https?://[^\s<>]+", text),
        "inline_code": re.findall(re.escape(BACKTICK) + r"+[^\n]*?" + re.escape(BACKTICK) + r"+", text),
    }


def canonical_content_stream(text: str) -> str:
    text = re.sub(r"(?m)^[ \t]*### (?:父级路径|上级知识条目)[ \t]*\r?\n", "", text)
    text = re.sub(r"(?m)^([ \t]*)- 父级路径：", r"\1", text)
    text = text.replace("→", ">")
    text = text.replace(r"\(", "").replace(r"\)", "").replace(r"\[", "").replace(r"\]", "")
    text = text.replace("$$", "").replace("$", "")
    text = re.sub(r"(?<!#)#{1,6}[ \t]+", "", text)
    text = text.replace("---", "")
    text = text.replace(">", "")
    return re.sub(r"\s+", "", text)


def transform_raw(relpath: str, raw: bytes) -> tuple[bytes, dict[str, object]]:
    frontmatter, body_bytes = split_frontmatter(raw)
    newline = "\r\n" if b"\r\n" in body_bytes else "\n"
    body = body_bytes.decode("utf-8")
    normalized_body = body.replace("\r\n", "\n")
    repaired_body, repairs = apply_explicit_repairs(relpath, normalized_body)
    baseline_converted, _baseline_stats = convert_legacy_math(repaired_body)
    baseline_formula, baseline_errors = formula_signature(baseline_converted)
    if baseline_errors:
        raise MigrationError("; ".join(baseline_errors))
    baseline_tokens = token_signature(repaired_body)
    baseline_stream = canonical_content_stream(repaired_body)
    converted, stats = convert_legacy_math(repaired_body)
    stats.explicit_repairs = len(repairs)
    converted = format_parent_lines(converted, stats)
    converted = structure_nonparent_flattened_lines(converted, stats)
    converted = normalize_display_layout(converted, stats)
    converted = normalize_horizontal_rule_spacing(converted, stats)
    modern_formula, modern_errors = formula_signature(converted)
    if modern_errors:
        raise MigrationError("; ".join(modern_errors))
    if modern_formula != baseline_formula:
        raise MigrationError(f"formula payload/order drift: before={len(baseline_formula)} after={len(modern_formula)}")
    if token_signature(converted) != baseline_tokens:
        raise MigrationError("wikilink/callout/url/inline-code signature drift")
    if canonical_content_stream(converted) != baseline_stream:
        raise MigrationError("non-structural content stream drift")
    legacy = legacy_tokens_outside_protected(converted)
    if legacy:
        raise MigrationError(f"legacy delimiters remain outside protected spans: {legacy[:5]}")
    double_inline = double_escaped_inline_tokens(converted)
    if double_inline:
        raise MigrationError(f"double-escaped inline delimiters remain: {double_inline[:5]}")
    bare = bare_latex_outside_math(converted)
    if bare:
        raise MigrationError(f"bare LaTeX remains outside math: {bare[:5]}")
    nonexclusive = nonexclusive_display_delimiter_lines(converted)
    if nonexclusive:
        raise MigrationError(f"display delimiter is not on its own line: {nonexclusive[:3]}")
    rule_spacing = horizontal_rule_spacing_errors(converted)
    if rule_spacing:
        raise MigrationError(f"horizontal rule lacks same-depth blank line: {rule_spacing[:5]}")
    final_body = converted if newline == "\n" else converted.replace("\n", newline)
    candidate = frontmatter + final_body.encode("utf-8")
    candidate_frontmatter, _candidate_body = split_frontmatter(candidate)
    if candidate_frontmatter != frontmatter:
        raise MigrationError("frontmatter bytes changed")
    return candidate, {
        "stats": dataclasses.asdict(stats),
        "repairs": repairs,
        "frontmatter_sha256": sha256_bytes(frontmatter),
        "body_pre_sha256": sha256_bytes(body_bytes),
        "body_post_sha256": sha256_bytes(final_body.encode()),
        "formula_count": len(modern_formula),
        "token_counts": {key: len(value) for key, value in baseline_tokens.items()},
    }


def load_frozen_hashes(run_root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in (run_root / "file-hashes-preapply.tsv").read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        digest, relpath = line.split("  ", 1)
        result[relpath] = digest
    return result


def load_target_list(run_root: Path) -> list[str]:
    paths = [line.strip() for line in (run_root / "file-list-preapply.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(paths) != len(set(paths)):
        raise MigrationError("frozen target list contains duplicates")
    return paths


def validate_target_scope(paths: Sequence[str]) -> None:
    for relpath in paths:
        path = Path(relpath)
        if path.suffix != ".md" or path.parent.name not in SUBJECTS or path.parent.parent != VISUAL_ROOT:
            raise MigrationError(f"out-of-scope frozen target: {relpath}")


def git_index_sha(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "--cached", "--binary"],
        cwd=project_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return sha256_bytes(result.stdout)


def git_head(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def discover_live_targets(project_root: Path) -> list[str]:
    result: list[str] = []
    for subject in SUBJECTS:
        subject_root = project_root / VISUAL_ROOT / subject
        if not subject_root.exists():
            continue
        for path in sorted(subject_root.glob("*.md")):
            result.append(path.relative_to(project_root).as_posix())
    return sorted(result)


def _command_plan_locked(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    run_arg = Path(args.run_root)
    run_root = (project_root / run_arg).resolve() if not run_arg.is_absolute() else run_arg
    if (run_root / "apply-wal.json").exists() or (run_root / "apply-receipt.jsonl").exists():
        raise MigrationError("refusing to replace a plan that already has apply state; use a new run root")
    targets = load_target_list(run_root)
    validate_target_scope(targets)
    if sorted(targets) != discover_live_targets(project_root):
        raise MigrationError("live target set differs from frozen target set")
    frozen_hashes = load_frozen_hashes(run_root)
    if set(frozen_hashes) != set(targets):
        raise MigrationError("frozen hash set differs from frozen target list")
    candidate_root = run_root / "candidates"
    candidate_root.mkdir(parents=True, exist_ok=True)
    exact, stems = build_vault_index(project_root)
    rows: list[dict[str, object]] = []
    exceptions: list[dict[str, object]] = []
    preexisting_unresolved: list[dict[str, object]] = []
    frontmatter_exceptions: list[dict[str, object]] = []
    protected_legacy_exceptions: list[dict[str, object]] = []
    aggregate = Counter()
    for relpath in targets:
        path = project_root / relpath
        raw = path.read_bytes()
        current_sha = sha256_bytes(raw)
        row: dict[str, object] = {
            "path": relpath,
            "pre_sha256": current_sha,
            "frozen_sha256": frozen_hashes[relpath],
            "mode": stat.S_IMODE(path.stat().st_mode),
        }
        if current_sha != frozen_hashes[relpath]:
            row.update(status="exception", error="current SHA differs from frozen preimage")
            exceptions.append(row)
            rows.append(row)
            continue
        try:
            candidate, evidence = transform_raw(relpath, raw)
            pre_frontmatter, pre_body = split_frontmatter(raw)
            _post_frontmatter, post_body = split_frontmatter(candidate)
            pre_missing = unresolved_links(pre_body.decode("utf-8"), exact, stems)
            post_missing = unresolved_links(post_body.decode("utf-8"), exact, stems)
            if Counter(pre_missing) != Counter(post_missing):
                raise MigrationError(
                    f"unresolved link target set changed: before={pre_missing[:5]} after={post_missing[:5]}"
                )
            evidence["preexisting_unresolved_links"] = pre_missing
            if pre_missing:
                preexisting_unresolved.append({"path": relpath, "targets": pre_missing})
            frontmatter_legacy = re.findall(
                r"(?<!\\)\\(?:[()[\]])",
                pre_frontmatter.decode("utf-8", errors="replace"),
            )
            if frontmatter_legacy:
                frontmatter_exceptions.append(
                    {
                        "path": relpath,
                        "legacy_token_count": len(frontmatter_legacy),
                        "reason": "YAML is frozen and intentionally excluded from body conversion",
                    }
                )
            protected_legacy = protected_legacy_occurrences(post_body.decode("utf-8"))
            if protected_legacy:
                protected_legacy_exceptions.append(
                    {"path": relpath, "occurrences": protected_legacy}
                )
            post_sha = sha256_bytes(candidate)
            changed = candidate != raw
            row.update(status="changed" if changed else "noop", post_sha256=post_sha, changed=changed, evidence=evidence)
            if changed:
                candidate_path = candidate_root / relpath
                candidate_path.parent.mkdir(parents=True, exist_ok=True)
                candidate_path.write_bytes(candidate)
                row["candidate"] = candidate_path.relative_to(run_root).as_posix()
            for key, value in evidence["stats"].items():
                aggregate[key] += int(value)
        except Exception as error:
            row.update(status="exception", error=f"{type(error).__name__}: {error}")
            exceptions.append(row)
        rows.append(row)
    jsonl_write(run_root / "plan.jsonl", rows)
    json_dump(run_root / "preexisting-unresolved-links.json", preexisting_unresolved)
    json_dump(run_root / "frontmatter-exceptions.json", frontmatter_exceptions)
    json_dump(run_root / "protected-legacy-exceptions.json", protected_legacy_exceptions)
    json_dump(
        run_root / "out-of-scope-source-truncations.json",
        {
            "count": len(KNOWN_OUT_OF_SCOPE_TRUNCATIONS),
            "paths": list(KNOWN_OUT_OF_SCOPE_TRUNCATIONS),
            "reason": "These existing prose truncations do not leave math unclosed and are outside this formatting migration.",
        },
    )
    summary = {
        "schema": "visual-obsidian-math-plan-v1",
        "project_root": str(project_root),
        "target_count": len(targets),
        "changed_count": sum(row["status"] == "changed" for row in rows),
        "noop_count": sum(row["status"] == "noop" for row in rows),
        "exception_count": len(exceptions),
        "preexisting_unresolved_link_file_count": len(preexisting_unresolved),
        "preexisting_unresolved_link_occurrence_count": sum(
            len(item["targets"]) for item in preexisting_unresolved
        ),
        "frontmatter_exception_count": len(frontmatter_exceptions),
        "protected_legacy_exception_file_count": len(protected_legacy_exceptions),
        "protected_legacy_token_count": sum(
            sum(int(entry["token_count"]) for entry in item["occurrences"])
            for item in protected_legacy_exceptions
        ),
        "out_of_scope_source_truncation_count": len(KNOWN_OUT_OF_SCOPE_TRUNCATIONS),
        "aggregate_stats": dict(sorted(aggregate.items())),
        "git_index_sha256": git_index_sha(project_root),
        "git_head": git_head(project_root),
        "script_sha256": sha256_bytes(Path(__file__).resolve().read_bytes()),
        "frozen_hash_manifest_sha256": sha256_bytes((run_root / "file-hashes-preapply.tsv").read_bytes()),
        "plan_sha256": sha256_bytes((run_root / "plan.jsonl").read_bytes()),
    }
    json_dump(run_root / "plan-summary.json", summary)
    json_dump(run_root / "plan-exceptions.json", exceptions)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not exceptions else 2


def command_plan(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    run_arg = Path(args.run_root)
    run_root = (project_root / run_arg).resolve() if not run_arg.is_absolute() else run_arg
    with single_writer_lock(run_root):
        return _command_plan_locked(args)


def atomic_write(
    path: Path,
    data: bytes,
    mode: int,
    *,
    expected_sha256: str | None = None,
    expected_mode: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.codex-", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        if expected_sha256 is not None:
            observed = path.read_bytes()
            observed_mode = stat.S_IMODE(path.stat().st_mode)
            if sha256_bytes(observed) != expected_sha256:
                raise MigrationError(f"target changed immediately before replace: {path}")
            if expected_mode is not None and observed_mode != expected_mode:
                raise MigrationError(f"target mode changed immediately before replace: {path}")
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_json_write(path: Path, value: object, mode: int = 0o600) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    atomic_write(path, payload, mode)


@contextlib.contextmanager
def single_writer_lock(run_root: Path) -> Iterator[None]:
    lock_path = run_root / "single-writer.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise MigrationError(f"another migration writer holds {lock_path}") from error
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _command_apply_locked(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    run_arg = Path(args.run_root)
    run_root = (project_root / run_arg).resolve() if not run_arg.is_absolute() else run_arg
    summary = json.loads((run_root / "plan-summary.json").read_text(encoding="utf-8"))
    if summary["exception_count"]:
        raise MigrationError("refusing apply: plan contains exceptions")
    if sha256_bytes(Path(__file__).resolve().read_bytes()) != summary["script_sha256"]:
        raise MigrationError("migration script changed after planning")
    if sha256_bytes((run_root / "plan.jsonl").read_bytes()) != summary["plan_sha256"]:
        raise MigrationError("plan JSONL hash changed after planning")
    if git_index_sha(project_root) != summary["git_index_sha256"]:
        raise MigrationError("Git index changed after planning")
    if git_head(project_root) != summary["git_head"]:
        raise MigrationError("Git HEAD changed after planning")
    rows = jsonl_read(run_root / "plan.jsonl")
    validate_target_scope([str(row["path"]) for row in rows])
    if sorted(str(row["path"]) for row in rows) != discover_live_targets(project_root):
        raise MigrationError("live target set changed after planning")
    changed_rows = [row for row in rows if row["status"] == "changed"]
    wal_path = run_root / "apply-wal.json"
    if wal_path.exists():
        wal = json.loads(wal_path.read_text(encoding="utf-8"))
        if wal.get("plan_sha256") != summary["plan_sha256"]:
            raise MigrationError("existing apply WAL belongs to a different plan")
    else:
        wal = {
            "schema": "visual-obsidian-math-apply-wal-v1",
            "plan_sha256": summary["plan_sha256"],
            "entries": [
                {
                    "path": row["path"],
                    "pre_sha256": row["pre_sha256"],
                    "post_sha256": row["post_sha256"],
                    "mode": row["mode"],
                    "candidate": row["candidate"],
                    "status": "pending",
                }
                for row in changed_rows
            ],
        }
        atomic_json_write(wal_path, wal)
    wal_entries = {str(entry["path"]): entry for entry in wal["entries"]}
    if set(wal_entries) != {str(row["path"]) for row in changed_rows}:
        raise MigrationError("apply WAL path set differs from changed plan path set")
    expected_wal = {
        str(row["path"]): {
            "pre_sha256": row["pre_sha256"],
            "post_sha256": row["post_sha256"],
            "mode": row["mode"],
            "candidate": row["candidate"],
        }
        for row in changed_rows
    }
    for relpath, entry in wal_entries.items():
        for key, expected in expected_wal[relpath].items():
            if entry.get(key) != expected:
                raise MigrationError(f"apply WAL field {key} is not bound to plan: {relpath}")

    # Full preflight occurs before the first new target write. A pending entry
    # already at its postimage is a recoverable crash between replace and WAL
    # status update.
    for row in rows:
        relpath = str(row["path"])
        current_path = project_root / relpath
        current = current_path.read_bytes()
        current_sha = sha256_bytes(current)
        current_mode = stat.S_IMODE(current_path.stat().st_mode)
        if current_mode != int(row["mode"]):
            raise MigrationError(f"target mode changed after planning: {relpath}")
        if row["status"] == "changed":
            entry = wal_entries[relpath]
            candidate_path = run_root / str(row["candidate"])
            candidate = candidate_path.read_bytes()
            if sha256_bytes(candidate) != row["post_sha256"]:
                raise MigrationError(f"candidate hash mismatch during full preflight: {relpath}")
            if current_sha == row["post_sha256"]:
                entry["status"] = "applied"
                entry["recovered_from_postimage"] = True
            elif current_sha == row["pre_sha256"] and entry["status"] == "pending":
                deterministic, _evidence = transform_raw(relpath, current)
                if deterministic != candidate:
                    raise MigrationError(f"candidate is not deterministic during full preflight: {relpath}")
            elif current_sha == row["pre_sha256"] and entry["status"] == "applied":
                raise MigrationError(f"WAL says applied but file is back at preimage: {relpath}")
            else:
                raise MigrationError(f"target changed after planning: {relpath}")
        else:
            if current_sha != row["pre_sha256"]:
                raise MigrationError(f"noop target changed after planning: {relpath}")
            deterministic, _evidence = transform_raw(relpath, current)
            if deterministic != current:
                raise MigrationError(f"planned noop is no longer deterministic: {relpath}")
    atomic_json_write(wal_path, wal)

    for row in changed_rows:
        relpath = str(row["path"])
        entry = wal_entries[relpath]
        if entry["status"] == "applied":
            continue
        path = project_root / relpath
        current = path.read_bytes()
        if sha256_bytes(current) != row["pre_sha256"]:
            raise MigrationError(f"optimistic lock failed before write: {relpath}")
        candidate_path = run_root / str(row["candidate"])
        candidate = candidate_path.read_bytes()
        if sha256_bytes(candidate) != row["post_sha256"]:
            raise MigrationError(f"candidate hash mismatch: {relpath}")
        deterministic, _evidence = transform_raw(relpath, current)
        if deterministic != candidate:
            raise MigrationError(f"candidate is not deterministic from current preimage: {relpath}")
        # Re-read content and mode inside atomic_write after the postimage temp
        # file is durable and immediately before os.replace.
        atomic_write(
            path,
            candidate,
            int(row["mode"]),
            expected_sha256=str(row["pre_sha256"]),
            expected_mode=int(row["mode"]),
        )
        if sha256_bytes(path.read_bytes()) != row["post_sha256"]:
            raise MigrationError(f"post-write verification failed: {relpath}")
        entry["status"] = "applied"
        entry["observed_post_sha256"] = row["post_sha256"]
        atomic_json_write(wal_path, wal)
    receipts = [dict(entry) for entry in wal["entries"] if entry["status"] == "applied"]
    jsonl_write(run_root / "apply-receipt.jsonl", receipts)
    apply_summary = {
        "schema": "visual-obsidian-math-apply-v1",
        "applied_count": len(receipts),
        "receipt_sha256": sha256_bytes((run_root / "apply-receipt.jsonl").read_bytes()) if receipts else sha256_bytes(b""),
    }
    json_dump(run_root / "apply-summary.json", apply_summary)
    print(json.dumps(apply_summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def command_apply(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    run_arg = Path(args.run_root)
    run_root = (project_root / run_arg).resolve() if not run_arg.is_absolute() else run_arg
    with single_writer_lock(run_root):
        return _command_apply_locked(args)


def build_vault_index(project_root: Path) -> tuple[set[str], set[str]]:
    exact: set[str] = set()
    stems: set[str] = set()
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(project_root)
        if relative.parts and relative.parts[0] in {".git", ".codex_tmp"}:
            continue
        relpath = relative.as_posix()
        exact.add(relpath)
        if path.suffix == ".md":
            exact.add(path.with_suffix("").relative_to(project_root).as_posix())
            stems.add(path.stem)
    return exact, stems


def unresolved_links(text: str, exact: set[str], stems: set[str]) -> list[str]:
    missing: list[str] = []
    for raw_link in re.findall(r"!?\[\[([^\]\n]+)\]\]", text):
        target = raw_link.split("|", 1)[0].split("#", 1)[0].strip()
        if not target:
            continue
        normalized = target.lstrip("/")
        if normalized in exact or normalized.removesuffix(".md") in exact:
            continue
        if Path(normalized).name.removesuffix(".md") in stems:
            continue
        missing.append(target)
    return missing


def command_verify(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    run_arg = Path(args.run_root)
    run_root = (project_root / run_arg).resolve() if not run_arg.is_absolute() else run_arg
    plan_rows = jsonl_read(run_root / "plan.jsonl")
    plan_by_path = {str(row["path"]): row for row in plan_rows}
    targets = load_target_list(run_root)
    exact, stems = build_vault_index(project_root)
    errors: list[dict[str, object]] = []
    preexisting_unresolved: list[dict[str, object]] = []
    protected_legacy: list[dict[str, object]] = []
    totals = Counter()
    for relpath in targets:
        row = plan_by_path[relpath]
        path = project_root / relpath
        raw = path.read_bytes()
        expected_sha = str(row["post_sha256"])
        observed_sha = sha256_bytes(raw)
        file_errors: list[str] = []
        if observed_sha != expected_sha:
            file_errors.append(f"postimage SHA mismatch: {observed_sha} != {expected_sha}")
        frozen = run_root / "preimage" / relpath
        frozen_frontmatter, _frozen_body = split_frontmatter(frozen.read_bytes())
        current_frontmatter, body_bytes = split_frontmatter(raw)
        if current_frontmatter != frozen_frontmatter:
            file_errors.append("frontmatter bytes differ from frozen preimage")
        body = body_bytes.decode("utf-8")
        if legacy_tokens_outside_protected(body):
            file_errors.append("legacy delimiters remain outside protected spans")
        if double_escaped_inline_tokens(body):
            file_errors.append("double-escaped inline delimiters remain")
        formulas, math_errors = formula_signature(body)
        if math_errors:
            file_errors.extend(math_errors)
        if bare_latex_outside_math(body):
            file_errors.append("bare LaTeX remains outside math")
        nonexclusive = nonexclusive_display_delimiter_lines(body)
        if nonexclusive:
            file_errors.append(f"display delimiters not on exclusive lines: {nonexclusive[:3]}")
        rule_spacing = horizontal_rule_spacing_errors(body)
        if rule_spacing:
            file_errors.append(f"horizontal rules lack same-depth blank lines: {rule_spacing[:5]}")
        frozen_missing = unresolved_links(_frozen_body.decode("utf-8"), exact, stems)
        current_missing = unresolved_links(body, exact, stems)
        if Counter(frozen_missing) != Counter(current_missing):
            file_errors.append(
                f"unresolved link target set changed: before={frozen_missing[:5]} after={current_missing[:5]}"
            )
        elif current_missing:
            preexisting_unresolved.append({"path": relpath, "targets": current_missing})
        current_protected_legacy = protected_legacy_occurrences(body)
        frozen_protected_legacy = protected_legacy_occurrences(_frozen_body.decode("utf-8"))
        if current_protected_legacy != frozen_protected_legacy:
            file_errors.append("protected legacy delimiter signature changed")
        elif current_protected_legacy:
            protected_legacy.append(
                {"path": relpath, "occurrences": current_protected_legacy}
            )
        try:
            rerun, _evidence = transform_raw(relpath, raw)
            if rerun != raw:
                file_errors.append("second transform is not a byte-for-byte no-op")
        except Exception as error:
            file_errors.append(f"idempotency transform failed: {type(error).__name__}: {error}")
        totals["formula_count"] += len(formulas)
        totals["files_checked"] += 1
        if file_errors:
            errors.append({"path": relpath, "errors": file_errors})
    report = {
        "schema": "visual-obsidian-math-verify-v1",
        "target_count": len(targets),
        "error_count": len(errors),
        "totals": dict(totals),
        "errors": errors,
        "preexisting_unresolved_links": preexisting_unresolved,
        "protected_legacy_exceptions": protected_legacy,
    }
    json_dump(run_root / "verify-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not errors else 3


def _command_rollback_locked(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    run_arg = Path(args.run_root)
    run_root = (project_root / run_arg).resolve() if not run_arg.is_absolute() else run_arg
    summary = json.loads((run_root / "plan-summary.json").read_text(encoding="utf-8"))
    if sha256_bytes((run_root / "plan.jsonl").read_bytes()) != summary["plan_sha256"]:
        raise MigrationError("plan JSONL hash changed before rollback")
    plan_rows = jsonl_read(run_root / "plan.jsonl")
    validate_target_scope([str(row["path"]) for row in plan_rows])
    changed_by_path = {
        str(row["path"]): row for row in plan_rows if row["status"] == "changed"
    }
    wal_path = run_root / "apply-wal.json"
    if wal_path.exists():
        wal = json.loads(wal_path.read_text(encoding="utf-8"))
        if wal.get("plan_sha256") != summary["plan_sha256"]:
            raise MigrationError("apply WAL belongs to a different plan")
        receipts = wal["entries"]
    else:
        receipts = jsonl_read(run_root / "apply-receipt.jsonl")
    if {str(receipt["path"]) for receipt in receipts} != set(changed_by_path):
        raise MigrationError("rollback receipt/WAL path set differs from changed plan")
    for receipt in receipts:
        relpath = str(receipt["path"])
        row = changed_by_path[relpath]
        for key in ("pre_sha256", "post_sha256", "mode", "candidate"):
            if receipt.get(key) != row.get(key):
                raise MigrationError(f"rollback receipt/WAL field {key} differs from plan: {relpath}")
    results: list[dict[str, object]] = []
    conflicts: list[str] = []
    for receipt in reversed(receipts):
        relpath = str(receipt["path"])
        path = project_root / relpath
        current_sha = sha256_bytes(path.read_bytes())
        if current_sha == receipt["pre_sha256"]:
            results.append({"path": relpath, "status": "already_preimage"})
            continue
        if current_sha != receipt["post_sha256"]:
            conflicts.append(relpath)
            results.append({"path": relpath, "status": "conflict", "current_sha256": current_sha})
            continue
        current_mode = stat.S_IMODE(path.stat().st_mode)
        if current_mode != int(receipt["mode"]):
            conflicts.append(relpath)
            results.append(
                {
                    "path": relpath,
                    "status": "conflict",
                    "reason": "mode changed after apply",
                    "current_mode": current_mode,
                }
            )
            continue
        preimage_path = run_root / "preimage" / relpath
        preimage = preimage_path.read_bytes()
        if sha256_bytes(preimage) != receipt["pre_sha256"]:
            raise MigrationError(f"frozen rollback preimage hash mismatch: {relpath}")
        atomic_write(
            path,
            preimage,
            int(receipt["mode"]),
            expected_sha256=str(receipt["post_sha256"]),
            expected_mode=int(receipt["mode"]),
        )
        results.append({"path": relpath, "status": "rolled_back"})
    report = {
        "rolled_back": sum(row["status"] == "rolled_back" for row in results),
        "already_preimage": sum(row["status"] == "already_preimage" for row in results),
        "conflicts": conflicts,
        "results": results,
    }
    json_dump(run_root / "rollback-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not conflicts else 4


def command_rollback(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    run_arg = Path(args.run_root)
    run_root = (project_root / run_arg).resolve() if not run_arg.is_absolute() else run_arg
    with single_writer_lock(run_root):
        return _command_rollback_locked(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--run-root", default=str(DEFAULT_RUN_ROOT))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan")
    subparsers.add_parser("apply")
    subparsers.add_parser("verify")
    subparsers.add_parser("rollback")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = {
        "plan": command_plan,
        "apply": command_apply,
        "verify": command_verify,
        "rollback": command_rollback,
    }[args.command]
    try:
        return command(args)
    except MigrationError as error:
        print(json.dumps({"error": str(error), "command": args.command}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
