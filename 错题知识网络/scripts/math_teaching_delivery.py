"""Audit the final bounded teaching response without fetching or writing evidence."""

import hashlib
import json
import sys
from time import perf_counter_ns


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _budget_gap(row):
    return (row.get("status") in ("budget_omitted", "budget_too_small")
            or bool(row.get("required_min_bytes")))


def has_delivery_gap(result):
    """A version match must not turn an incomplete read into a full cache hit."""
    if (result.get("status") not in ("available", "source_based")
            or _budget_gap(result) or result.get("truncated") or result.get("memory_omitted")
            or result.get("unknown") or result.get("ambiguous")
            or result.get("teaching_inputs_status") == "budget_omitted"):
        return True
    for row in result.get("records", []):
        if (row.get("status") in ("semantic_stale", "source_changed", "method_stale")
                or row.get("step_evidence_status") in ("budget_omitted", "source_changed")
                or _budget_gap(row)):
            return True
    memory = result.get("memory_context") or {}
    if (_budget_gap(memory) or memory.get("required_full_bytes")
            or memory.get("current_materials_omitted")):
        return True
    for key in ("personal_judgments", "personal_records", "pending_evidence", "historical_evidence",
                "utterance_lookup"):
        layer = memory.get(key) or {}
        if (_budget_gap(layer) or layer.get("status") in ("partial", "stale", "unavailable")
                or any(layer.get(field) for field in (
                    "omitted_count", "omitted_records", "omitted_turns",
                    "claims_omitted", "conflicts_omitted", "history_gaps", "record_scan_truncated"))):
            return True
    recap = result.get("recap") or {}
    return _budget_gap(recap) or recap.get("status") in ("partial", "stale", "unavailable")


def _delivered(result, requested_view):
    """Pointers into stdout only. Never promote a candidate or a conflict to fact."""
    if requested_view == "protected" or result.get("view", requested_view) == "protected":
        return {}
    groups = {}

    def present(row, prefix, fields):
        if not isinstance(row, dict):
            return
        for field in fields:
            part = row.get(field)
            if not part:
                continue
            target = f"{prefix}/{field}"
            groups.setdefault(field, []).extend(
                [f"{target}/{i}" for i in range(len(part))] if isinstance(part, list) else [target])

    present(result, "", ("problem_solving", "exam_frequency", "choice_fill_guidance"))
    present(result.get("recap"), "/recap", ("basic_formulas", "secondary_conclusions", "solution_methods"))
    for i, row in enumerate(result.get("records", [])):
        prefix = f"/records/{i}"
        present(row, prefix, ("problem_solving", "step_reference", "conclusion_reference", "step_evidence",
                              "teaching_preferences", "solution_connections"))
        if row.get("status") == "semantic_current":
            present(row, prefix, ("short_summary", "next_check"))
    memory = result.get("memory_context") or {}
    for key, fields in (
        ("personal_judgments", ("claims", "conflicts")),
        ("personal_records", ("records",)),
        ("historical_evidence", ("points",)),
        ("pending_evidence", ("records",)),
    ):
        layer = memory.get(key)
        if isinstance(layer, dict):
            prefix = "/memory_context/" + key
            # Record groups have a common field name; their pointers preserve the role.
            present(layer, prefix, fields)
    points = (result.get("teaching_inputs") or {}).get("points", {})
    for key, point in points.items():
        if (point.get("exact_question_prior") or {}).get("status") == "available":
            key = key.replace("~", "~0").replace("/", "~1")
            present(point, f"/teaching_inputs/points/{key}", ("exact_question_prior",))
    return groups


def emit_audit(result, *, args, began_ns, exit_status):
    """Keep stdout as the teaching JSON and print metadata separately to stderr."""
    body = encode(result)
    payload = body.encode("utf-8")
    fields = ("concepts", "formal_id", "source_question_id", "query", "operation",
              "fallback_concepts", "valid_at", "known_at", "for_teaching", "include_recap",
              "recap_concepts", "include_pending", "known_version", "point_records",
              "pending_capture_id", "pending_sequences", "pending_hint_sequences", "pending_spans",
              "pending_whole_capture", "structured_math", "confirmed_concept", "selection_receipt",
              "selection_basis", "selection_abstain", "backend_config")
    scope = {key: getattr(args, key, None) for key in fields}
    if scope["backend_config"] is not None:
        scope["backend_config"] = str(scope["backend_config"])
    receipt = {
        "schema": "math-teaching-delivery-v1",
        "view": args.view,
        "scope_sha256": hashlib.sha256(
            encode([args.view, args.max_bytes, scope]).encode("utf-8")).hexdigest(),
        "status": result.get("status"),
        "source_version": result.get("source_version"),
        "version": result.get("version"),
        "exit_status": exit_status,
        "max_bytes": args.max_bytes,
        "stdout_utf8_bytes": len(payload),
        "stdout_sha256": hashlib.sha256(payload).hexdigest(),
        "within_budget": len(payload) <= args.max_bytes,
        "query_ms": round((perf_counter_ns() - began_ns) / 1_000_000, 3),
        "body_state": "cached_body_not_returned" if result.get("status") == "unchanged" else
                      "full_delivery_not_established" if has_delivery_gap(result) else "delivered",
        "delivered_json_pointers": _delivered(result, args.view),
    }
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(payload + b"\n")
    else:
        print(body)
    print(encode(receipt), file=sys.stderr)
