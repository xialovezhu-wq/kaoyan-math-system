#!/usr/bin/env python3
"""Incremental byte/line index for one append-only Codex rollout."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


INDEX_SCHEMA = 1
GUARD_BYTES = 4096


class SessionIndexError(ValueError):
    """The rollout cannot be read through a verified incremental index."""


def _message(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if (
        payload.get("type") != "message"
        or payload.get("role") not in ("user", "assistant")
        or payload.get("phase") in ("analysis", "reasoning")
        or payload.get("channel") in ("analysis", "reasoning")
    ):
        return None
    return payload


def _visible(message: dict[str, Any]) -> bool:
    return message.get("recipient") in (None, "all")


def _preview(message: dict[str, Any]) -> tuple[str, list[Any]]:
    blocks = message.get("content")
    if not isinstance(blocks, list):
        return "", []
    text = "".join(
        block.get("text", "")
        for block in blocks
        if isinstance(block, dict)
        and block.get("type") in ("input_text", "output_text", "text")
        and isinstance(block.get("text", ""), str)
    )
    return text[:90], [block.get("type") if isinstance(block, dict) else None for block in blocks]


def _guard(handle, start: int, length: int) -> str:
    handle.seek(start)
    return hashlib.sha256(handle.read(length)).hexdigest()


class SessionIndex:
    """Maintain and query a derived index without rereading an unchanged prefix."""

    def __init__(self, rollout: Path, cache_root: Path, session_id: str):
        self.rollout = Path(rollout).expanduser().resolve(strict=True)
        if not self.rollout.is_file() or self.rollout.is_symlink():
            raise SessionIndexError("Rollout must be an existing regular non-symlink file")
        self.session_id = session_id
        cache_root = Path(cache_root)
        cache_root.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(str(self.rollout).encode("utf-8")).hexdigest()
        self.index_path = cache_root / f"{key}.sqlite3"
        self._ensure()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.index_path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                line_no INTEGER PRIMARY KEY,
                byte_start INTEGER NOT NULL,
                byte_end INTEGER NOT NULL,
                role TEXT NOT NULL,
                visible INTEGER NOT NULL,
                recipient TEXT,
                preview TEXT NOT NULL,
                block_types TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS messages_visible_tail
                ON messages(visible, line_no DESC);
            """
        )
        return connection

    def _read_connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.index_path.resolve().as_uri() + "?mode=ro", uri=True)

    @staticmethod
    def _meta(connection: sqlite3.Connection) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in connection.execute("SELECT key,value FROM meta"):
            result[key] = json.loads(value)
        return result

    @staticmethod
    def _set_meta(connection: sqlite3.Connection, values: dict[str, Any]) -> None:
        connection.executemany(
            "INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)",
            [(key, json.dumps(value, ensure_ascii=False, separators=(",", ":"))) for key, value in values.items()],
        )

    def _ensure(self) -> None:
        before = self.rollout.stat()
        with self.rollout.open("rb") as source, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            meta = self._meta(connection)
            if meta:
                if meta.get("index_schema") != INDEX_SCHEMA:
                    raise SessionIndexError("Derived rollout index schema changed; remove the cache and retry")
                if meta.get("source_path") != str(self.rollout):
                    raise SessionIndexError("Derived rollout index source identity mismatch")
                indexed_size = meta.get("indexed_size")
                line_count = meta.get("line_count")
                if not isinstance(indexed_size, int) or not isinstance(line_count, int):
                    raise SessionIndexError("Derived rollout index metadata is invalid")
                reset = (
                    (meta.get("source_dev"), meta.get("source_ino")) != (before.st_dev, before.st_ino)
                    or before.st_size < indexed_size
                )
                if not reset:
                    head_length = min(GUARD_BYTES, indexed_size)
                    tail_start = max(0, indexed_size - GUARD_BYTES)
                    reset = (
                        meta.get("head_sha256") != _guard(source, 0, head_length)
                        or meta.get("tail_sha256") != _guard(source, tail_start, indexed_size - tail_start)
                    )
                if reset:
                    connection.execute("DELETE FROM messages")
                    connection.execute("DELETE FROM meta")
                    indexed_size = 0
                    line_count = 0
                    session_ids = []
                else:
                    session_ids = meta.get("session_ids", [])
                    if not isinstance(session_ids, list):
                        raise SessionIndexError("Derived rollout session metadata is invalid")
            else:
                indexed_size = 0
                line_count = 0
                session_ids = []

            source.seek(indexed_size)
            rows: list[tuple[Any, ...]] = []
            complete_size = indexed_size
            current_line = line_count
            while True:
                byte_start = source.tell()
                raw = source.readline()
                if not raw:
                    break
                if not raw.endswith(b"\n"):
                    break
                current_line += 1
                try:
                    row = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise SessionIndexError(f"Rollout line {current_line} is not valid UTF-8 JSON") from exc
                if not isinstance(row, dict):
                    raise SessionIndexError(f"Rollout line {current_line} is not a JSON object")
                if row.get("type") == "session_meta":
                    payload = row.get("payload")
                    if not isinstance(payload, dict):
                        raise SessionIndexError(f"Rollout line {current_line} has invalid session metadata")
                    session_ids.append(payload.get("id"))
                message = _message(row.get("payload")) if row.get("type") == "response_item" else None
                if message is not None:
                    preview, block_types = _preview(message)
                    recipient = message.get("recipient")
                    rows.append((
                        current_line,
                        byte_start,
                        source.tell(),
                        message["role"],
                        int(_visible(message)),
                        recipient if isinstance(recipient, str) else None,
                        preview,
                        json.dumps(block_types, ensure_ascii=False, separators=(",", ":")),
                    ))
                complete_size = source.tell()

            after = self.rollout.stat()
            if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino) or after.st_size < complete_size:
                raise SessionIndexError("Rollout identity changed while extending its index")
            if session_ids != [self.session_id]:
                raise SessionIndexError("Rollout session identity must match exactly one session_meta")
            if rows:
                connection.executemany(
                    "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)",
                    rows,
                )
            head_length = min(GUARD_BYTES, complete_size)
            tail_start = max(0, complete_size - GUARD_BYTES)
            self._set_meta(connection, {
                "index_schema": INDEX_SCHEMA,
                "source_path": str(self.rollout),
                "source_dev": before.st_dev,
                "source_ino": before.st_ino,
                "indexed_size": complete_size,
                "line_count": current_line,
                "session_ids": session_ids,
                "head_sha256": _guard(source, 0, head_length),
                "tail_sha256": _guard(source, tail_start, complete_size - tail_start),
            })
            self.indexed_size = complete_size
            self.line_count = current_line

    def message(self, line_no: int) -> dict[str, Any] | None:
        with self._read_connect() as connection:
            row = connection.execute(
                "SELECT line_no,byte_start,byte_end,role,visible,recipient,preview,block_types "
                "FROM messages WHERE line_no=?",
                (line_no,),
            ).fetchone()
        if row is None:
            return None
        return {
            "line": row[0], "byte_start": row[1], "byte_end": row[2],
            "role": row[3], "visible": bool(row[4]), "recipient": row[5],
            "preview": row[6], "blocks": json.loads(row[7]),
        }

    def latest_visible_user_line(self) -> int | None:
        with self._read_connect() as connection:
            row = connection.execute(
                "SELECT line_no FROM messages WHERE visible=1 AND role='user' ORDER BY line_no DESC LIMIT 1"
            ).fetchone()
        return row[0] if row else None

    def messages(self, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        with self._read_connect() as connection:
            rows = connection.execute(
                "SELECT line_no,role,preview,block_types FROM messages "
                "WHERE visible=1 ORDER BY line_no DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"line": row[0], "role": row[1], "preview": row[2], "blocks": json.loads(row[3])}
            for row in reversed(rows)
        ]

    def read_range(self, start_line: int, end_line: int) -> tuple[list[dict[str, Any]], bytes]:
        """Read exact complete JSONL bytes between two indexed message lines."""
        start = self.message(start_line)
        end = self.message(end_line)
        if start is None or end is None or start_line > end_line:
            raise SessionIndexError("Range boundaries must be indexed user/assistant message lines")
        length = end["byte_end"] - start["byte_start"]
        with self.rollout.open("rb") as source:
            source.seek(start["byte_start"])
            raw = source.read(length)
        if len(raw) != length or not raw.endswith(b"\n"):
            raise SessionIndexError("Rollout changed while reading the selected byte range")
        encoded_lines = raw.splitlines(keepends=True)
        if len(encoded_lines) != end_line - start_line + 1:
            raise SessionIndexError("Selected byte range no longer matches indexed physical lines")
        rows: list[dict[str, Any]] = []
        for line_no, encoded in enumerate(encoded_lines, start_line):
            try:
                row = json.loads(encoded)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SessionIndexError(f"Rollout line {line_no} is not valid UTF-8 JSON") from exc
            if not isinstance(row, dict):
                raise SessionIndexError(f"Rollout line {line_no} is not a JSON object")
            rows.append(row)
        return rows, raw


def open_session(rollout: Path, cache_root: Path, session_id: str) -> SessionIndex:
    """Open, validate and incrementally extend one rollout index."""
    return SessionIndex(rollout, cache_root, session_id)
