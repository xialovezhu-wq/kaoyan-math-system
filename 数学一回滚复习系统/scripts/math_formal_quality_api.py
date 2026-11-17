"""Bounded OpenAI calls and resumable, subject-local request receipts."""

from array import array
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "错题知识网络/scripts"))
import math_runtime_paths

MODEL = {"embeddings": "text-embedding-3-large", "decisions": "gpt-6-luna"}
DIMENSIONS = 1536
MAX_ITEMS = 32
MAX_BYTES = 60_000
MAX_ATTEMPTS = 3
TRANSIENT = {408, 409, 429, 499, 500, 502, 503, 504}
BRIDGE = math_runtime_paths.bridge_root()
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,160}")


class QualityError(ValueError):
    pass


def require(value, code):
    if not value:
        raise QualityError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return sha(canonical(value))


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value, *, immutable=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = canonical(value)
    if path.exists():
        require(not path.is_symlink(), "quality_symlink")
        if path.read_bytes() == raw:
            return
        require(not immutable, "quality_immutable_receipt_conflict")
    fd, tmp = tempfile.mkstemp(prefix=".quality-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(tmp).unlink(missing_ok=True)


def now():
    return datetime.now(timezone.utc).isoformat()


def vector_hex(values):
    require(isinstance(values, list) and len(values) == DIMENSIONS and
            all(type(x) in (int, float) and math.isfinite(x) for x in values)
            and any(values), "quality_invalid_vector")
    data = array("f", values)
    if sys.byteorder != "little":
        data.byteswap()
    return data.tobytes().hex()


def vector(value):
    data = array("f")
    try:
        data.frombytes(bytes.fromhex(value))
    except (TypeError, ValueError) as exc:
        raise QualityError("quality_invalid_stored_vector") from exc
    if sys.byteorder != "little":
        data.byteswap()
    require(len(data) == DIMENSIONS and all(math.isfinite(x) for x in data)
            and any(data), "quality_invalid_stored_vector")
    return data


def transport():
    sys.path.insert(0, str(BRIDGE))
    try:
        from study_openai import request
        return request
    finally:
        sys.path.remove(str(BRIDGE))


def payload_for(endpoint, rows, evidence):
    model = MODEL[endpoint]
    if endpoint == "embeddings":
        return {"model": model, "dimensions": DIMENSIONS, "encoding_format": "float",
                "input": list(rows.values())}
    return {"model": model, "input": evidence,
            "questions": [{"name": key, "type": "predicate", "instructions": value}
                          for key, value in rows.items()]}


def input_hash(endpoint, text, evidence):
    return digest([endpoint, MODEL[endpoint], DIMENSIONS if endpoint == "embeddings" else None,
                   evidence, text])


def valid_model(endpoint, value):
    model = MODEL[endpoint]
    return isinstance(value, str) and re.fullmatch(re.escape(model) + r"(?:-\d{4}-\d{2}-\d{2})?", value)


def valid_id(value):
    return isinstance(value, str) and SAFE_ID.fullmatch(value)


def response_items(endpoint, response, rows):
    require(isinstance(response, dict) and valid_model(endpoint, response.get("model"))
            and valid_id(response.get("_request_id")) and isinstance(response.get("usage"), dict),
            "quality_unverified_provider_response")
    entries = response.get("data" if endpoint == "embeddings" else "answers")
    require(isinstance(entries, list), "quality_missing_provider_rows")
    seen, accepted = set(), {}
    keys = list(rows)
    for entry in entries:
        require(isinstance(entry, dict), "quality_invalid_response_row")
        if endpoint == "embeddings":
            ordinal = entry.get("index")
            require(type(ordinal) is int and 0 <= ordinal < len(keys), "quality_invalid_embedding_ordinal")
            key = keys[ordinal]
        else:
            key = entry.get("name")
        require(isinstance(key, str) and key in rows and key not in seen, "quality_response_scope_mismatch")
        seen.add(key)
        if endpoint == "embeddings":
            try:
                accepted[key] = vector_hex(entry.get("embedding"))
            except (QualityError, ValueError, OverflowError, TypeError):
                continue
        elif (entry.get("type") == "predicate" and type(entry.get("probability")) in (int, float)
              and 0 <= entry["probability"] <= 1):
            accepted[key] = entry["probability"]
    return accepted


class Journal:
    def __init__(self, workspace, run_id, *, request=None, seconds=900):
        self.folder = Path(workspace) / "requests"
        self.run_id = run_id
        self.mode = "fixture" if request is not None else "live"
        self.request = request if request is not None else transport()
        self.deadline = time.monotonic() + seconds

    def _receipt(self, purpose, endpoint, path):
        row = read(path)
        require((row["schema"], row["run_id"], row["purpose"], row["endpoint"], row["mode"],
                 row["client_request_id"], row["model_requested"], row["dimensions"]) ==
                ("math-quality-request-v1", self.run_id, purpose, endpoint, self.mode, path.stem,
                 MODEL[endpoint], DIMENSIONS if endpoint == "embeddings" else None),
                "quality_request_receipt_binding")
        return row

    def _use(self, row, key):
        return {"request": row["client_request_id"], "input_sha256": row["unit_input_sha256"][key],
                "result_sha256": digest(row["results"][key])}

    def verify(self, purpose, endpoint, key, use, expected):
        require(valid_id(purpose) and valid_id(use["request"]), "quality_invalid_request_locator")
        row = self._receipt(purpose, endpoint, self.folder / purpose / (use["request"] + ".json"))
        require(row["status"] in {"OK", "PARTIAL"} and valid_id(row.get("request_id"))
                and valid_model(endpoint, row.get("model_returned"))
                and isinstance(row.get("usage"), dict)
                and re.fullmatch(r"[0-9a-f]{64}", row.get("response_sha256", ""))
                and key in row["results"] and self._use(row, key) == use
                and use["input_sha256"] == expected, "quality_request_proof_drift")
        value = row["results"][key]
        if endpoint == "embeddings":
            vector(value)
        else:
            require(type(value) in (int, float) and 0 <= value <= 1, "quality_invalid_stored_decision")
        return value

    def stage(self, purpose, endpoint, rows, *, evidence=None):
        require(valid_id(purpose) and endpoint in MODEL
                and all(valid_id(key) and isinstance(text, str) and 0 < len(text.encode()) <= 7000
                        for key, text in rows.items()), "quality_request_scope_invalid")
        if not rows:
            return {}
        directory = self.folder / purpose
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        expected = {key: input_hash(endpoint, value, evidence) for key, value in rows.items()}
        with (directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            found, unknown = {}, set()
            for path in sorted(directory.glob("qmath-*.json")):
                receipt = self._receipt(purpose, endpoint, path)
                for key, hash_value in receipt["unit_input_sha256"].items():
                    if expected.get(key) != hash_value:
                        continue
                    if receipt["status"] == "OUTCOME_UNKNOWN":
                        unknown.add(key)
                    elif key in receipt.get("results", {}):
                        use = self._use(receipt, key)
                        self.verify(purpose, endpoint, key, use, expected[key])
                        found[key] = use
            require(not (unknown - found.keys()), "quality_request_outcome_unknown")
            batch = {}
            for key, text in rows.items():
                if key in found:
                    continue
                trial = {**batch, key: text}
                if batch and (len(trial) > MAX_ITEMS or len(canonical(payload_for(endpoint, trial, evidence))) > MAX_BYTES):
                    found.update(self._send(directory, purpose, endpoint, batch, evidence, expected))
                    batch = {}
                batch[key] = text
            if batch:
                found.update(self._send(directory, purpose, endpoint, batch, evidence, expected))
            return found

    def _send(self, directory, purpose, endpoint, batch, evidence, expected):
        pending = dict(batch)
        found = {}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            remaining = self.deadline - time.monotonic()
            require(remaining >= 1, "quality_request_deadline")
            payload = payload_for(endpoint, pending, evidence)
            require(len(canonical(payload)) <= MAX_BYTES, "quality_request_payload_too_large")
            key = "qmath-" + uuid4().hex
            path = directory / (key + ".json")
            row = {"schema": "math-quality-request-v1", "run_id": self.run_id, "purpose": purpose,
                   "mode": self.mode, "endpoint": endpoint, "client_request_id": key,
                   "unit_input_sha256": {k: expected[k] for k in pending},
                   "input_sha256": digest(payload), "model_requested": MODEL[endpoint],
                   "dimensions": payload.get("dimensions"), "status": "OUTCOME_UNKNOWN",
                   "attempt": attempt, "started_at": now()}
            write(path, row)
            delay = float(attempt)
            try:
                response = self.request(endpoint, payload, timeout=min(45, remaining), client_request_id=key)
            except Exception as exc:
                code = getattr(exc, "code", "STUDY_API_UNAVAILABLE")
                status = re.fullmatch(r"STUDY_API_HTTP_(\d{3})", code)
                provider_code = getattr(exc, "error_code", None)
                row.update(status="FAILED" if status or code != "STUDY_API_UNAVAILABLE" else "OUTCOME_UNKNOWN",
                           error=code, provider_error=provider_code, request_id=getattr(exc, "request_id", None),
                           finished_at=now())
                write(path, row)
                if (not status or int(status[1]) not in TRANSIENT
                        or provider_code in {"insufficient_quota", "billing_hard_limit_reached"}):
                    raise QualityError("quality_request_" + code.lower()) from None
                try:
                    delay = max(delay, float(getattr(exc, "retry_after", None)))
                except (TypeError, ValueError):
                    pass
            else:
                row.update(response_sha256=digest(response), request_id=response.get("_request_id"),
                           model_returned=response.get("model"), usage=response.get("usage"), finished_at=now())
                try:
                    result = response_items(endpoint, response, pending)
                except QualityError as exc:
                    row.update(status="FAILED", error=str(exc))
                    write(path, row)
                    raise
                row.update(status="OK" if len(result) == len(pending) else "PARTIAL",
                           results=result, missing=sorted(pending.keys() - result.keys()))
                write(path, row)
                for name in result:
                    found[name] = self._use(row, name)
                    del pending[name]
                if not pending:
                    return found
            if attempt == MAX_ATTEMPTS or delay > 30 or time.monotonic() + delay + 1 > self.deadline:
                break
            time.sleep(delay)
        raise QualityError(f"quality_request_pending:{purpose}:{len(pending)}")
