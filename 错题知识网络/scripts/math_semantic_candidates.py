"""Local, read-only math candidate inputs and advisory Decisions labels.

Reuses the existing formal-quality transport/receipts. Nothing here can write a
formal card, infer learner mastery, or transmit unreviewed conversation bytes.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import unicodedata

NORMALIZATION = "math-candidate-conditions-v1"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def normalized_text(s):
    # Keep math tokens, negation, signs, and implication direction. NFKC,
    # character n-grams, or stripping operators is not an equivalence check.
    return "\n".join(unicodedata.normalize("NFC", x).strip() for x in s.splitlines() if x.strip())


def formula_inputs(root, keys, *, limit_per_key=2):
    """Only current, authorized formula bodies with their full conditions."""
    import math_concept_index as index
    import math_formula_cards as cards
    root = Path(root).resolve()
    result = {}
    try:
        current = cards.pointer(root)
        if not current or not (root / index.INDEX).is_file():
            return result
        with closing(sqlite3.connect((root / index.INDEX).as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("BEGIN")
            version = json.loads(db.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
            if (current.get("native_bindings") or {}).get("bound_profile_version") != version:
                return result
            for key in dict.fromkeys(keys):
                inputs = []
                for ref in cards.profile_refs(root, db, key, "direct", current=current)[:limit_per_key]:
                    found = cards.lookup(root, ref["id"], view="direct", current_pointer=current, full=True)
                    if found["status"] != "ready":
                        continue
                    card = found["card"]
                    # These phrases are mathematical reference evidence only.
                    # They do not include an exam application or actual learner turns.
                    conditions = ["；".join(x[k] for k in ("latex", "label") if x.get(k))
                                  for x in card["assumptions_latex"]]
                    statement = [x.get("latex") or x["text"] for x in card["statement_sequence"]]
                    text = normalized_text("\n".join([
                        card["title"], "适用条件：" + "；".join(conditions), *statement,
                        *(["边界：" + "；".join(card["guard_note"])] if card["guard_note"] else []),
                    ]))
                    sources = card["source_refs"]
                    stable = [[r["path"], r["sha256"], r.get("pdf_page") or r.get("pdf_pages")] for r in sources]
                    inputs.append({
                        "text": text, "concept_key": key, "stable_id": card["card_id"],
                        "role": "formula" if card["kind"] == "basic_formula" else "conclusion",
                        "source_refs": sources, "input_identity": digest([NORMALIZATION, stable, text]),
                    })
                result[key] = inputs
        return result if cards.pointer(root) == current else {}
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        # Formula projection is optional input to the existing exact/lexical/
        # indexed mathematical corpus. Its absence never proves equivalence.
        return {}


def same_capture_group(source, turns):
    """Local locator for the selected, already checked role/sequence evidence."""
    from math_concept_sources import selected_turn_locators
    refs = selected_turn_locators(turns)
    conversation = source.get("conversation") or {}
    return {"manifest_sha256": source["manifest_sha256"], "conversation": conversation,
            "selected_turns": refs, "coverage": "selected_original_capture_only" if refs else "no_selected_turns",
            "learning_authority": "no_new_outcome"}


def advisory(probabilities, matched):
    """Typed suggestions; only the owning author may adopt or reject."""
    p = probabilities
    if not matched:
        return {"relation": "insufficient_evidence", "reason": "no_verified_candidate", "requires_parent_review": True}
    condition_difference = p.get("condition_difference")
    if condition_difference is not None and condition_difference >= .70 and p.get("assignment", 0) >= .60:
        relation = "different_conditions"
        reason = "decisions_found_condition_or_direction_difference"
    elif (condition_difference is not None and condition_difference <= .30 and p.get("duplicate", 0) >= .80
          and p.get("assignment", 0) >= .70 and p.get("conflict", 1) <= .25):
        relation = "same_conclusion"
        reason = "decisions_supported_same_roles_conditions_and_direction"
    elif p.get("assignment", 1) <= .30 and p.get("support", 1) <= .35:
        relation = "form_only"
        reason = "candidate_ranked_but_mathematical_role_not_supported"
    else:
        relation = "insufficient_evidence"
        reason = "condition_equivalence_not_established"
    return {"relation": relation, "reason": reason, "requires_parent_review": True}


def unique_rows(rows):
    """Deduplicate identical mathematical source fragments, never text alone."""
    seen, result = set(), []
    for row in rows:
        key = digest([row["role"], normalized_text(row["text"]),
                      sorted((ref["path"], ref["sha256"], str(ref.get("pdf_page") or ref.get("pdf_pages")))
                             for ref in row["source_refs"])])
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result
