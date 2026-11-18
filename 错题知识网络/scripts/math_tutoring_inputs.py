"""Project the current read into teaching roles without reopening learning records."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3

from math_teaching_scope import part_scope, summary_role


VISUAL_ENTRY = "错题知识网络/scripts/math_teaching_visual.py"
ELIGIBLE_STEP_STATES = {"current", "source_changed", "partial_after_correction",
                        "correction_dependency_unknown"}


def exact_observation(repo, result, key, operation):
    """Ask the guarded index for a same-question observation, not a card summary."""
    from math_memory_evidence import locate

    formal = (result.get("identity") or {}).get("formal_id")
    version = result.get("source_version")
    if not formal or not version:
        return {"status": "not_bound_to_formal_question"}
    # The existing locator checks an explicit subquestion in annotations; a
    # mere concept/date match in a multi-part question still needs inspection.
    parts, excluded = part_scope(operation)
    if not parts and excluded:
        return {"status": "requested_subquestion_unresolved"}
    if len(parts) > 1:
        return {"status": "multiple_subquestions_require_separate_scope"}
    sub = next(iter(parts), None)
    scope = {"status": "resolved", "exact_identity": True, "formal_ids": [formal],
             "personal_requested": True, "subquestion": sub}
    try:
        found = locate(repo, [key], scope=scope, view=result["view"], expected_version=version,
                       teaching_annotation=True, max_bytes=7500, limit=2)
    except (OSError, TypeError, ValueError, sqlite3.Error):
        return {"status": "unavailable"}
    # A tie on the latest date has no recency winner; no raw records or quote
    # content are copied into this reply. Annotation is not the user's words.
    rows = found.get("records", [])
    if not rows:
        return {"status": found["status"]}
    newest = rows[0]
    if len(rows) > 1 and newest.get("study_date") == rows[1].get("study_date"):
        return {"status": "same_day_order_unverified"}
    if found.get("status") != "available":
        return {"status": found["status"]}
    sources = newest.get("source_handles", [])
    locators = [{f: source.get(f) for f in ("path", "sha256")} for source in sources[:1]]
    observations = []
    for atom in newest.get("observations", []):
        if sub and atom.get("subquestion_binding") != "explicit":
            continue
        row = {k: atom[k] for k in ("outcome", "accepted_annotation", "hint_precedes_user", "subquestion_binding")
               if k in atom}
        for field in ("user_sequences", "hint_sequences"):
            row[field] = sorted(set(atom.get(field, [])))
        observations.append(row)
    if not observations:
        return {"status": "subquestion_not_verified" if sub else "no_bounded_observation"}
    return {"status": "available", "role": "past_exact_question_observation",
            "formal_id": formal, "study_date": newest.get("study_date"),
            "annotation_status": "view_restricted" if result["view"] != "direct" else
            "available" if any(atom.get("accepted_annotation") for atom in observations[:2]) else "omitted",
            "sources": locators, "observations": observations[:2]}


def teaching_inputs(result, max_bytes, *, repo=None, operation=None, known_version=None, add_exact=True):
    """References point into the bytes actually returned, never omitted evidence."""
    if result.get("status") in {"unchanged", "budget_too_small"}:
        return result
    protected = result.get("view") not in {"after_attempt", "direct"}
    temporal = (result.get("memory_context") or {}).get("temporal") or {}
    decision = {"current_work_first": True, "visual_entry": VISUAL_ENTRY,
                "visual_scope": "given_only" if protected else "current_authorized_geometry",
                "points": {}}
    retrieval = (result.get("memory_context") or {}).get("retrieval") or {}
    exact_key = None
    domain_ok = result.get("status") in {"available", "source_based"} and not any(
        temporal.get(field) for field in ("valid_at", "known_at"))
    for index, row in enumerate(result.get("records", []) if not protected and domain_ok else ()):
        key = row.get("concept_key")
        if not key:
            continue
        matched = row.get("retrieval_scope") or {}
        reference_only = (row.get("reference_only") or row.get("object_role") or
                          row.get("personal_evidence_eligible") is False or
                          retrieval.get("reference_only") or matched.get("role") == "candidate_reference")
        row_status = row.get("status")
        point = {"binding": "reference_only" if reference_only else
                 "confirm_current_object_operation_and_conditions",
                 "profile_status": row_status}
        decision["points"][key] = point
        if reference_only or row_status == "historical_personal_view":
            continue
        if (index == 0 and row_status in {"semantic_current", "semantic_stale", "evidence_digest_only"}
                and not matched.get("requires_scope_check")
                and (result.get("resolution") or {}).get("status") in (None, "partial_exact")
                and re.fullmatch(r"MATH-CONCEPT-[0-9a-f]{24}", key)):
            exact_key = key
        prefix = f"/records/{index}/"
        # Even a current concept summary can describe another question or an
        # earlier step. A matching point never proves a current attempt.
        role = row.get("summary_role") or summary_role(row.get("short_summary"))
        if role == "scoped_result_withheld":
            point["personal_history_status"] = role
        elif role == "reference_only_no_attributed_attempt":
            point["personal_history_status"] = "no_attributed_attempt_in_summary"
        elif role == "other_questions_named_in_concept_history":
            point["other_question_history"] = prefix + "short_summary"
        elif row_status == "semantic_current" and row.get("short_summary"):
            point["concept_prior"] = prefix + "short_summary"
            if row.get("next_check"):
                point["candidate_check"] = prefix + "next_check"
            if row.get("solution_connections"):
                point["conditional_solution_connections"] = prefix + "solution_connections"
        if row.get("teaching_preferences") and row.get("teaching_preferences_status") in {"current", "partial"}:
            point["scoped_preferences"] = prefix + "teaching_preferences"
            for j, preference in enumerate(row["teaching_preferences"]):
                focus = preference.get("focus")
                ref = prefix + f"teaching_preferences/{j}"
                if focus in {"explanation", "both"}:
                    point.setdefault("explanation_preferences", []).append(ref)
                if focus in {"method", "both"}:
                    point.setdefault("solution_preferences", []).append(ref)
        if row.get("step_evidence_status") not in ELIGIBLE_STEP_STATES:
            continue
        roles = {}
        for j, atom in enumerate(row.get("step_evidence", [])):
            state = atom.get("state")
            if state == "independent_performed":
                role = "independent_operation" if atom.get("coverage") == "full_operation" else "independent_fragment"
            elif state == "corrected_after_hint":
                role = "hint_assisted"
            else:
                role = "does_not_establish_independent_execution"
            roles.setdefault(role, []).append(prefix + f"step_evidence/{j}")
        if roles:
            point["past_step_evidence"] = roles

    def encoded(obj):
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def compact_before_omitting(value):
        # The existing exam brief is a derived index of fields present in the
        # response. If the same fields are here, pointers suffice; preserve all
        # method conditions, frequency, observations and actual profile bodies.
        def brief_refs(row, prefix=""):
            fields = ("problem_solving", "teaching_preferences", "step_evidence", "next_check")
            return [prefix + key for key in fields if row.get(key)]

        def compact(row, refs):
            if row.get("status") == "semantic_stale":
                # Stale prose is not an eligible prior. Its status remains
                # visible; removing it cannot turn it into a newer judgment.
                row = {k: v for k, v in row.items() if k not in {"short_summary", "next_check", "progress"}}
                refs = [ref for ref in refs if ref != "next_check"]
            if isinstance(row.get("exam_brief"), dict) and refs:
                brief = {"field_refs": refs}
                if len(encoded(brief)) < len(encoded(row["exam_brief"])):
                    return {**row, "exam_brief": brief}
            return row

        memory = value.get("memory_context")
        if isinstance(memory, dict):
            # The role/index maps only repeat paths to the actual evidence in
            # this very response. Keep conflict, freshness and history records.
            value = {**value, "memory_context": {k: v for k, v in memory.items() if k not in {"roles", "levels"}}}
        rows = value.get("records", [])
        top = brief_refs(value)
        if not top and any(row.get("problem_solving") for row in rows):
            top = ["records[].problem_solving"]
        value = compact(value, top)
        return {**value, "records": [compact(row, brief_refs(row) or
                                       (["response.problem_solving"] if value.get("problem_solving") else []))
                                     for row in rows]}

    recipe = None
    if add_exact and domain_ok and not protected and repo is not None and operation:
        from math_teaching_visual import suggest_study_recipe
        recipe = suggest_study_recipe(repo, operation, result["view"])
    value = {**result, "teaching_inputs": decision}
    if len(encoded(value)) > max_bytes and domain_ok and not protected:
        value = compact_before_omitting(value)
    if len(encoded(value)) <= max_bytes:
        exact_prior_omitted = False
        if (add_exact and repo is not None and exact_key and result.get("status") == "available"
                and (result.get("identity") or {}).get("formal_id")):
            point = decision["points"][exact_key]
            prior = exact_observation(repo, result, exact_key, operation)
            point["exact_question_prior"] = prior
            if len(encoded(value)) > max_bytes:
                value = compact_before_omitting(value)
            needed = len(encoded(value))
            if (needed > max_bytes and prior.get("status") == "available"
                    and (value.get("problem_solving") or {}).get("detail_status") == "first_action_and_conditions_only"):
                # Keep the exact observation before a textbook preview that
                # the current question can explicitly request later.
                value.pop("problem_solving")
                needed = len(encoded(value))
            if needed > max_bytes and prior.get("status") == "available" and result["view"] == "after_attempt":
                # The enclosing response already binds the formal ID, and
                # observation positions/notes stay on their immutable source.
                # Preserve the outcome and hint ordering at small budgets.
                point["exact_question_prior"] = {
                    "status": "available", "detail": "history_only",
                    "study_date": prior["study_date"], "annotation_status": "view_restricted",
                    "observations": [{k: atom[k] for k in ("outcome", "hint_precedes_user", "subquestion_binding")
                                      if k in atom} for atom in prior["observations"]],
                }
                if len(encoded(value)) <= max_bytes:
                    needed = 0
            if needed > max_bytes:
                exact_prior_omitted = True
                point["exact_question_prior"] = {"status": "budget_omitted", "required_min_bytes": needed}
                if len(encoded(value)) > max_bytes:
                    point["exact_question_prior"].pop("required_min_bytes")
                    if len(encoded(value)) > max_bytes:
                        point.pop("exact_question_prior")
        if recipe:
            decision["study_recipe"] = recipe
            if len(encoded(value)) > max_bytes:
                value = compact_before_omitting(value)
            if len(encoded(value)) > max_bytes:
                decision.pop("study_recipe")
        if add_exact and not protected and not temporal.get("valid_at") and not temporal.get("known_at"):
            decision["ipad_3d"] = "--tutor-presentation three_d"
            if len(encoded(value)) > max_bytes:
                decision.pop("ipad_3d")
        if isinstance(result.get("version"), str):
            version = hashlib.sha256(encoded(["math-teaching-roles-v1", result["version"], decision])).hexdigest()
            if len(encoded({**value, "version": version})) <= max_bytes:
                value["version"] = version
                recap = (result.get("recap") or {}).get("status")
                if (known_version == version and not exact_prior_omitted
                        and recap in {None, "available", "no_match", "protected"}
                        and not any(p.get("exact_question_prior", {}).get("status") in
                                    {"budget_omitted", "budget_too_small", "unavailable", "stale"}
                                    for p in decision["points"].values())):
                    from math_teaching_delivery import has_delivery_gap
                    if not has_delivery_gap(value):
                        return {"status": "unchanged", "version": version, "view": result["view"], "records": [],
                                "source_version": result.get("source_version"), "identity": result.get("identity")}
        return value
    # The extra pointers never evict the methods, conditions or evidence itself.
    status = {**result, "teaching_inputs_status": "budget_omitted",
              "teaching_inputs_required_min_bytes": len(encoded(value))}
    if recipe:
        # A checked synthetic asset can fit even when all the teaching roles
        # cannot. Preserve the budget warning and the original evidence.
        small = {k: decision[k] for k in ("visual_entry", "visual_scope")}
        small["study_recipe"] = recipe
        reduced = {**status, "teaching_inputs": small}
        if isinstance(result.get("version"), str):
            reduced["version"] = hashlib.sha256(encoded(["math-study-recipe-v1", result["version"], small])).hexdigest()
        if len(encoded(reduced)) <= max_bytes:
            return reduced
    return status if len(encoded(status)) <= max_bytes else result
