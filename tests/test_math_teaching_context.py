from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "错题知识网络" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import math_teaching_context as teaching  # noqa: E402
import training_evidence  # noqa: E402


def value_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class MathTeachingContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        self.cards = self.repo / "错题知识网络" / "错题卡"
        self.cards.mkdir(parents=True)
        self.formal_id = "GS-900"
        self.capture_id = "MFI-CAP-111111111111111111111111"
        self.freeze_id = "MFI-FREEZE-222222222222222222222222"
        self.card_path = self.cards / "GS-900_fixture.md"
        self.write_card()
        self.context = self.make_context()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_card(self, *, action_gap_type: str = "B3-METHOD") -> None:
        self.card_path.write_text(
            """---
id: GS-900
title: fixture
wrong_point: "没有先区分积分曲面与投影区域，直接把两者混用。"
knowledge:
  - 曲面积分
answer: "this endpoint stays only in the formal card"
method_gap:
  enabled: true
  evidence_origin: user_confirmed
  knowledge_gap_or_method_gap: 方法入口
  method_trigger: "看到曲面积分时先确认积分对象。"
  expected_method: "区分对象后选择表示。"
  expected_first_action: "先标出积分曲面和投影区域。"
  missed_action: "没有先标出积分曲面和投影区域，直接开始计算。"
  action_gap_type: %s
  related_method_card_id: H18-008
  confidence: high
  need_user_confirmation: false
---

# Fixture
"""
            % action_gap_type,
            encoding="utf-8",
        )

    def card_evidence(self) -> dict:
        meta = teaching.parse_formal_card_frontmatter(self.card_path)
        return training_evidence.extract_error_evidence(meta, self.formal_id)

    def make_context(self, *, first_break_text: str = "历史上没有先区分两个对象。") -> dict:
        evidence = self.card_evidence()
        capture_bindings = [
            {
                "capture_event_id": self.capture_id,
                "capture_content_hash": "1" * 64,
                "amendment_event_ids": ["MFI-AMD-333333333333333333333333"],
                "effective_evidence_hash": "2" * 64,
                "effective_target_hash": "3" * 64,
            }
        ]
        capture_version = teaching.capture_evidence_source_version(
            self.formal_id,
            self.freeze_id,
            capture_bindings,
        )
        return {
            "schema_version": teaching.CONTEXT_SCHEMA,
            "formal_id": self.formal_id,
            "artifact_date": "2026-08-29",
            "study_dates": ["2026-08-29"],
            "precedence": dict(teaching.PRECEDENCE),
            "source_bindings": {
                "formal_card_path": self.card_path.relative_to(self.repo).as_posix(),
                "formal_card_sha256": teaching.sha256_file(self.card_path),
                "formal_evidence_id": evidence["evidence_id"],
                "formal_evidence_source_version": evidence["source_version"],
                "freeze_id": self.freeze_id,
                "capture_event_ids": [self.capture_id],
                "capture_bindings": capture_bindings,
                "capture_evidence_source_version": capture_version,
                "package_bindings": [
                    {
                        "capture_event_id": self.capture_id,
                        "package_id": "MATHPKG-fixture",
                        "package_sha256": "4" * 64,
                    }
                ],
            },
            "prior": {
                "evidence_scope": "prior_only",
                "action_gap_type": "B3-METHOD",
                "evidence_origin": "user_confirmed",
                "needs_confirmation": False,
                "first_break": {
                    "kind": "object_role",
                    "text": first_break_text,
                    "evidence_origin": "user_confirmed",
                    "source_capture_id": self.capture_id,
                },
                "independent_correct_steps": [
                    {
                        "text": "曾独立识别被积函数。",
                        "evidence_origin": "user_observed",
                        "source_capture_id": self.capture_id,
                    }
                ],
                "hint_dependency": {
                    "level": "l2",
                    "text": "历史上需要一次对象角色提醒。",
                    "evidence_origin": "user_observed",
                    "source_capture_id": self.capture_id,
                },
                "effective_representation": [
                    {
                        "kind": "object_table",
                        "text": "极短对象表曾帮助恢复主路线。",
                        "evidence_origin": "user_observed",
                        "source_capture_id": self.capture_id,
                    }
                ],
                "unresolved": [
                    {
                        "text": "仍需检查是否能独立选择投影对象。",
                        "evidence_origin": "user_observed",
                        "source_capture_id": self.capture_id,
                    }
                ],
                "c_followup": {
                    "eligible": True,
                    "after_current_question_only": True,
                    "reason": "B3 只进入后续辨型复习。",
                },
            },
        }

    def test_materialize_is_content_addressed_idempotent_and_pointer_last(self) -> None:
        first = teaching.materialize_context(self.repo, self.context)
        second = teaching.materialize_context(self.repo, self.context)

        self.assertEqual("created", first["status"])
        self.assertEqual("already_current", second["status"])
        self.assertEqual(first["context_path"], second["context_path"])
        self.assertEqual(first["context_sha256"], second["context_sha256"])
        self.assertEqual(first["pointer_sha256"], second["pointer_sha256"])
        version = self.repo / first["context_path"]
        pointer = self.repo / first["pointer_path"]
        self.assertEqual(first["context_sha256"], hashlib.sha256(version.read_bytes()).hexdigest())
        self.assertEqual(first["pointer_sha256"], hashlib.sha256(pointer.read_bytes()).hexdigest())
        self.assertEqual(
            teaching.canonical_file_bytes(json.loads(version.read_text(encoding="utf-8"))),
            version.read_bytes(),
        )
        stored_text = version.read_text(encoding="utf-8").casefold()
        self.assertNotIn("this endpoint", stored_text)
        self.assertNotIn('"answer"', stored_text)
        self.assertNotIn("created_at", stored_text)

    def test_capture_evidence_version_uses_only_frozen_core_and_sorted_capture_ids(self) -> None:
        first = {
            "capture_event_id": "MFI-CAP-b",
            "capture_content_hash": "1" * 64,
            "amendment_event_ids": [],
            "effective_evidence_hash": "2" * 64,
            "effective_target_hash": "3" * 64,
            "package_id": "ignored-by-formula",
        }
        second = {
            "capture_event_id": "MFI-CAP-a",
            "capture_content_hash": "4" * 64,
            "amendment_event_ids": ["MFI-AMD-a"],
            "effective_evidence_hash": "5" * 64,
            "effective_target_hash": "6" * 64,
        }
        expected_payload = {
            "freeze_id": self.freeze_id,
            "formal_id": self.formal_id,
            "capture_bindings": [
                {key: second[key] for key in (
                    "capture_event_id",
                    "capture_content_hash",
                    "amendment_event_ids",
                    "effective_evidence_hash",
                    "effective_target_hash",
                )},
                {key: first[key] for key in (
                    "capture_event_id",
                    "capture_content_hash",
                    "amendment_event_ids",
                    "effective_evidence_hash",
                    "effective_target_hash",
                )},
            ],
        }
        self.assertEqual(
            value_hash(expected_payload),
            teaching.capture_evidence_source_version(
                self.formal_id,
                self.freeze_id,
                [first, second],
            ),
        )

    def test_protected_view_redacts_exact_history_and_full_views_keep_prior_only(self) -> None:
        teaching.materialize_context(self.repo, self.context)
        protected = teaching.resolve_context(self.repo, self.formal_id, "protected")
        after = teaching.resolve_context(self.repo, self.formal_id, "after_attempt")
        direct = teaching.resolve_context(self.repo, self.formal_id, "direct")

        self.assertEqual("available", protected["status"])
        self.assertFalse(protected["current_question_evidence"]["history_may_override"])
        self.assertEqual("prior_only", protected["prior"]["evidence_scope"])
        self.assertNotIn("first_break", protected["prior"])
        self.assertNotIn("independent_correct_steps", protected["prior"])
        self.assertNotIn("unresolved", protected["prior"])
        self.assertNotIn("text", protected["prior"]["hint_dependency"])
        self.assertNotIn("source_bindings", protected)
        self.assertEqual(self.context["prior"]["first_break"]["text"], after["prior"]["first_break"]["text"])
        self.assertEqual(after["prior"], direct["prior"])
        self.assertTrue(after["prior"]["c_followup"]["after_current_question_only"])

    def test_version_rejects_forbidden_fields_and_endpoint_text_before_writing(self) -> None:
        with_forbidden_key = json.loads(json.dumps(self.context))
        with_forbidden_key["prior"]["answer"] = "A"
        with self.assertRaisesRegex(teaching.TeachingContextError, "answer_unsafe_content"):
            teaching.materialize_context(self.repo, with_forbidden_key)

        with_forbidden_text = json.loads(json.dumps(self.context))
        with_forbidden_text["prior"]["first_break"]["text"] = "正确答案是 A"
        with self.assertRaisesRegex(teaching.TeachingContextError, "answer_unsafe_content"):
            teaching.materialize_context(self.repo, with_forbidden_text)

        self.assertFalse((self.repo / "错题知识网络" / "教学投影").exists())

    def test_final_card_and_formal_evidence_are_reauthenticated(self) -> None:
        wrong_hash = json.loads(json.dumps(self.context))
        wrong_hash["source_bindings"]["formal_card_sha256"] = "f" * 64
        with self.assertRaisesRegex(teaching.TeachingContextError, "formal_card_hash_mismatch"):
            teaching.materialize_context(self.repo, wrong_hash)

        wrong_evidence = json.loads(json.dumps(self.context))
        wrong_evidence["source_bindings"]["formal_evidence_source_version"] = "e" * 64
        with self.assertRaisesRegex(teaching.TeachingContextError, "formal_evidence_drift"):
            teaching.materialize_context(self.repo, wrong_evidence)

        wrong_capture = json.loads(json.dumps(self.context))
        wrong_capture["source_bindings"]["capture_evidence_source_version"] = "d" * 64
        with self.assertRaisesRegex(teaching.TeachingContextError, "capture_evidence_version_mismatch"):
            teaching.materialize_context(self.repo, wrong_capture)

    def test_card_drift_makes_resolver_fail_soft_without_fallback_scan(self) -> None:
        teaching.materialize_context(self.repo, self.context)
        self.card_path.write_text(
            self.card_path.read_text(encoding="utf-8") + "\nexternal drift\n",
            encoding="utf-8",
        )
        with mock.patch.object(Path, "rglob", side_effect=AssertionError("must not scan")):
            resolved = teaching.resolve_context(self.repo, self.formal_id, "protected")
        verified = teaching.verify_context(self.repo, self.formal_id)

        self.assertEqual("available_current_state", resolved["status"])
        self.assertEqual({}, resolved["prior"])
        self.assertEqual("available", resolved["personal_context"]["status"])
        self.assertEqual(
            hashlib.sha256(self.card_path.read_bytes()).hexdigest(),
            resolved["personal_context"]["current"]["formal_card_sha256"],
        )
        self.assertNotIn("this endpoint", json.dumps(resolved, ensure_ascii=False))
        self.assertEqual("formal_card_hash_mismatch", resolved["reason_code"])
        self.assertFalse(resolved["current_question_evidence"]["history_may_override"])
        self.assertEqual("invalid", verified["status"])
        self.assertEqual("formal_card_hash_mismatch", verified["reason_code"])

    def test_exact_formal_id_resolver_ignores_another_projection(self) -> None:
        teaching.materialize_context(self.repo, self.context)
        other = self.repo / "错题知识网络" / "教学投影" / "GS-999"
        other.mkdir(parents=True)
        (other / "current.json").write_text("not json", encoding="utf-8")

        result = teaching.resolve_context(self.repo, self.formal_id, "protected")

        self.assertEqual("available", result["status"])
        missing = teaching.resolve_context(self.repo, "GS-901", "protected")
        self.assertEqual("unavailable", missing["status"])
        self.assertEqual("pointer_missing", missing["reason_code"])

    def test_current_only_keeps_live_evidence_and_does_not_load_related_cards(self) -> None:
        directory = self.repo / "错题知识网络" / "wiki" / "topics" / "knowledge_clusters"
        directory.mkdir(parents=True)
        (directory / "MATHWIKI-KNOWLEDGE-001_曲面积分.md").write_text(
            "---\nwiki_id: MATHWIKI-KNOWLEDGE-001\ntitle: 曲面积分\n---\n| GS-901 | related |\n")
        (self.cards / "GS-901_fixture.md").write_text(
            "---\nid: GS-901\nknowledge:\n  - 曲面积分\n---\n")
        teaching.materialize_context(self.repo, self.context)
        original = teaching.math_learning_state.load_state
        with mock.patch.object(teaching.math_learning_state, "load_state", wraps=original) as reads:
            result = teaching.resolve_context(self.repo, self.formal_id, "after_attempt", related_limit=0)
        personal = result["personal_context"]
        self.assertEqual("available", personal["status"])
        self.assertTrue(personal["current"]["source_version"])
        self.assertEqual([], personal["related"])
        self.assertEqual(0, personal["related_candidate_count"])
        self.assertTrue(all(call.args[1] == self.formal_id for call in reads.call_args_list))
        self.assertFalse(personal["history_may_override_current"])
        with self.assertRaises(teaching.TeachingContextError):
            teaching.resolve_context(self.repo, self.formal_id, related_limit=-1)

    def test_new_question_cli_uses_concept_key_without_formal_id(self) -> None:
        import math_concept_index
        import math_learning_profiles
        math_concept_index.build_index(self.repo)
        with mock.patch.object(teaching, "resolve_context", side_effect=AssertionError("must not require a current card")), \
             mock.patch.object(math_concept_index, "resolve_concepts", side_effect=AssertionError("default must not read full evidence")), \
             mock.patch.object(math_learning_profiles, "resolve", wraps=math_learning_profiles.resolve) as query, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            code = teaching.main(["--repo", str(self.repo), "resolve", "--concept", "曲面积分",
                                  "--view", "after_attempt", "--max-bytes", "10000"])
        value = json.loads(output.getvalue())
        self.assertEqual(0, code)
        self.assertEqual(1, query.call_count)
        self.assertEqual("available", value["status"])
        self.assertEqual(math_concept_index.concept_key("曲面积分"), value["records"][0]["concept_key"])
        self.assertEqual("evidence_digest_only", value["records"][0]["status"])
        self.assertTrue(value["records"][0]["short_summary"])
        self.assertTrue(value["records"][0]["next_check"])
        self.assertIsNone(value["identity"])
        self.assertLessEqual(len(math_concept_index.canonical(value).encode()), 10000)
        with mock.patch.object(math_concept_index, "resolve_concepts", side_effect=AssertionError("reuse must not read full evidence")), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            code = teaching.main(["--repo", str(self.repo), "resolve", "--concept", "曲面积分",
                                  "--view", "after_attempt", "--max-bytes", "10000",
                                  "--known-version", value["version"]])
        reused = json.loads(output.getvalue())
        self.assertEqual(0, code)
        self.assertEqual("unchanged", reused["status"])
        self.assertEqual([], reused["records"])
        self.assertEqual(value["version"], reused["version"])
        # Full-evidence pagination keeps its separate index-version contract.
        with mock.patch.object(math_learning_profiles, "resolve", side_effect=AssertionError("explicit history must not use profiles")), \
             mock.patch.object(math_concept_index, "resolve_concepts", wraps=math_concept_index.resolve_concepts) as query, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            code = teaching.main(["--repo", str(self.repo), "resolve", "--concept", "曲面积分",
                                  "--full-evidence", "--expected-version", "incorrect-version"])
        self.assertEqual(0, code)
        self.assertEqual(1, query.call_count)
        self.assertEqual("stale_page", json.loads(output.getvalue())["status"])

    def test_temporal_delivery_retains_nested_gaps_on_same_version(self):
        import math_concept_index as native
        import math_learning_profiles as profiles
        import math_memory_context as memory
        from math_teaching_delivery import has_delivery_gap

        self.build_concept_fixtures([])
        key = native.concept_key("曲面积分")
        point = {"concept_key": key, "status": "partial", "history_complete": False,
                 "event_count": 4, "events_omitted": 3, "history_gaps_total": 1,
                 "history_gaps": [{"reason": "source_unavailable"}],
                 "events": [{"event_id": "EVENT-1", "source_ref_count": 3, "source_refs_omitted": 1}]}
        history = {"status": "available", "points": [point], "source_version": memory._index_version(self.repo)}
        args = ["--repo", str(self.repo), "resolve", "--concept", key, "--view", "after_attempt",
                "--valid-at", "2026-10-01", "--audit-context", "--for-teaching", "--max-bytes", "4500"]

        def bounded_profile(*_args, **_options):
            # Keep unrelated current material out of the synthetic history-only case.
            return {"status": "available", "view": "after_attempt", "version": "native-query",
                    "source_version": history["source_version"], "records": [
                        {"concept_key": key, "concept_name": "曲面积分", "status": "evidence_digest_only"}]}

        def read(*extra):
            with mock.patch.object(profiles, "resolve", side_effect=bounded_profile), \
                 contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as audit:
                self.assertEqual(0, teaching.main([*args, *extra]))
            return json.loads(output.getvalue()), json.loads(audit.getvalue())

        with mock.patch.object(memory, "_historical_evidence", return_value=history):
            first, audit = read()
            retry, _ = read("--known-version", first["version"])
            self.assertEqual(first, retry)
            self.assertEqual("full_delivery_not_established", audit["body_state"])
            observed = audit["historical_evidence"]
            self.assertEqual("partial_delivery", observed["status"])
            self.assertEqual(4, observed["selection"]["indexed_events_in_scope"])
            self.assertEqual(3, observed["selection"]["events_omitted"])
            self.assertEqual(1, observed["delivery"]["events"])
            self.assertEqual({"events_omitted", "history_source_unverified", "history_incomplete", "source_refs_omitted"},
                             set(observed["gap_reasons"]))
            self.assertEqual(["/memory_context/historical_evidence/points/0/events/0"],
                             audit["delivered_json_pointers"]["events"])
            self.assertEqual("not_established", audit["answer_reference_binding"])
            self.assertNotIn("EVENT-1", json.dumps(audit))

        point.update(status="available", event_count=1, events_omitted=0, history_gaps_total=0,
                     history_gaps=[], history_complete=True)
        point["events"][0].pop("source_refs_omitted")
        with mock.patch.object(memory, "_historical_evidence", return_value=history):
            first, audit = read()
            self.assertFalse(has_delivery_gap(first))
            self.assertEqual("complete_delivery", audit["historical_evidence"]["status"])
            retry, _ = read("--known-version", first["version"])
            self.assertEqual("unchanged", retry["status"])
        for status in ("protected", "not_requested"):
            # No absent/out-of-scope denominator is inferred from withheld data.
            scoped = {**first, "memory_context": {"historical_evidence": {"status": status, "points": []}}}
            self.assertFalse(has_delivery_gap(scoped))

    def write_claim_fixture(self, claims, recorded_at):
        import math_concept_index as native
        import math_memory_lifecycle as memory

        key = native.concept_key("曲面积分")
        path = self.repo / memory.SEMANTIC / (key + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            previous = path.read_text()
            history = path.parent / "历史版本" / key
            history.mkdir(parents=True, exist_ok=True)
            (history / (json.loads(previous)["content_sha256"] + ".json")).write_text(previous)
        profile = {"concept_key": key, "claims": claims, "memory_recorded_at": recorded_at}
        path.write_text(memory.canonical({**profile, "content_sha256": memory.digest(profile)}))
        return key

    def memory_claim_fixture(self):
        original_source = self.repo / "prior-observation.json"
        quote = "我先检查这个条件。"
        original_source.write_text(json.dumps({"turns": [{"role": "user", "sequence": 1, "text": quote}]}))
        claim = {"claim_id": "prior", "content": "原有的确认判断。", "scope": "在原有条件下",
                 "basis": "user_observed", "status": "active", "valid_from": "2026-09-01",
                 "source_refs": [{"path": original_source.name, "sha256": teaching.sha256_file(original_source),
                                  "quote": quote, "role": "user", "sequence": 1}], "observation_refs": []}
        source = self.repo / "new-evidence.txt"
        source.write_text("Replacement evidence fixture")
        return claim, {**claim, "claim_id": "replacement", "content": "后续判断。", "valid_from": "2026-10-01",
                       "basis": "source_verified", "supersedes": ["prior"],
                       "source_refs": [{"path": source.name, "sha256": teaching.sha256_file(source)}]}

    def test_candidates_and_conflicts_cannot_replace_a_confirmed_claim(self):
        import math_memory_lifecycle as memory

        prior, successor = self.memory_claim_fixture()
        variants = ({"basis": "assistant_inferred", "status": "candidate"},
                    {"status": "candidate", "source_refs": [{"path": "unavailable.txt", "sha256": "0" * 64}]},
                    {"status": "conflicted"}, {"status": "active", "conflicts_with": ["prior"]})
        for i, change in enumerate(variants, 2):
            key = self.write_claim_fixture([prior, {**successor, **change}], f"2026-10-0{i}T08:00:00+08:00")
            for day in (None, "2026-10-15"):
                with self.subTest(change=change, valid_at=day):
                    result = memory.resolve_memory_claims(self.repo, [key], valid_at=day, view="direct")
                    self.assertEqual("active", next(c["status"] for c in result["claims"] if c["claim_id"] == "prior"))
                    if change["status"] == "candidate":
                        self.assertEqual("candidate", next(c["status"] for c in result["claims"] if c["claim_id"] == "replacement"))

    def test_verified_replacement_survives_archiving_and_drift_does_not_revive_the_prior(self):
        import math_memory_lifecycle as memory

        prior, successor = self.memory_claim_fixture()
        successor["valid_to"] = "2026-10-04"
        key = self.write_claim_fixture([prior], "2026-09-02T08:00:00+08:00")
        self.write_claim_fixture([prior, successor], "2026-10-02T08:00:00+08:00")
        self.write_claim_fixture([prior], "2026-10-05T08:00:00+08:00")

        def read(**times):
            result = memory.resolve_memory_claims(self.repo, [key], view="direct", **times)
            return {c["claim_id"]: c["status"] for c in result["claims"]}, result["history_gaps"]

        self.assertEqual({"prior": "superseded"}, read()[0])
        self.assertEqual({}, read(valid_at="2026-10-15")[0])
        self.assertEqual({"prior": "active"}, read(valid_at="2026-09-30")[0])
        self.assertEqual({"prior": "active"}, read(valid_at="2026-10-15", known_at="2026-10-01")[0])
        (self.repo / "new-evidence.txt").write_text("Changed after acceptance")
        for dates in ({}, {"valid_at": "2026-10-15"}):
            self.assertEqual(({"prior": "conflicted"}, [
                {"concept_key": key, "claim_id": "prior", "reason": "supersession_unverified"}]), read(**dates))
        self.write_claim_fixture([{**prior, "status": "retracted"}], "2026-10-06T08:00:00+08:00")
        self.assertEqual({"prior": "retracted"}, read()[0])
        self.assertEqual({"prior": "retracted"}, read(valid_at="2026-10-15")[0])

    def concept_event_fixture(self, *, kind="concept_review", count=40):
        import math_concept_index as native
        key = native.concept_key("曲面积分")
        rows = [{"observation_id": f"OBS-{i}", "concept_key": key,
                 "question_ref": f"new-source-{i}", "outcome": "wrong",
                 "error_detail": f"第{i}题把积分曲面误当平面投影，未检查弧长或面积因子。",
                 "user_turn_indices": [0], "hint_turn_indices": [],
                 "related_formal_ids": []} for i in range(count)]
        rows[-1].update(outcome="corrected_after_hint", error_detail="提示后区分曲面与投影。",
                        user_turn_indices=[2], hint_turn_indices=[1])
        if kind == "formal_concept_observation":
            for row in rows:
                row.update(capture_event_id="FIXTURE-CAP", concept_label="曲面积分",
                           user_evidence=[{"sequence": 1, "quote": "我把积分曲面当投影。"}],
                           hint_evidence=[{"sequence": 2, "quote": "先区分几何对象。"}]
                           if row["outcome"] == "corrected_after_hint" else [])
                row.pop("user_turn_indices")
                row.pop("hint_turn_indices")
        return {"record_id": f"FIXTURE-{kind}", "formal_id": "GS-901" if kind.startswith("formal") else None,
                "kind": kind, "concept_key": key, "labels": ["曲面积分"],
                "source_refs": [{"path": self.card_path.relative_to(self.repo).as_posix(),
                                 "sha256": teaching.sha256_file(self.card_path)}],
                "association": "explicit_concept_observation", "not_proof_of_same_error": True,
                "retrieval_priority": {"explicit_personal_or_actual_delivery": True,
                                       "latest_explicit_learning_date": "2026-09-08"},
                "summary": {"session_id": "fixture", "event_id": f"FIXTURE-{kind}",
                            "study_date": "2026-09-08", "wrong_session_count": 1,
                            "related_formal_ids": [], "observation_count": len(rows), "observations": rows},
                "history": {"conversation": [{"role": "user", "text": "我把曲面当投影。"},
                                              {"role": "assistant", "text": "先区分几何对象。"},
                                              {"role": "user", "text": "提示后我知道要检查面积因子。"}],
                            "unrelated_full_session": "SECRET-ENDPOINT" * 1000}}

    def build_concept_fixtures(self, records):
        import math_concept_index as native
        import math_concept_review
        with mock.patch.object(math_concept_review, "collect_records", return_value=records):
            native.build_index(self.repo)

    def test_long_session_does_not_block_bounded_teaching_evidence(self):
        import math_concept_index as native
        import math_learning_profiles as profiles
        self.build_concept_fixtures([self.concept_event_fixture()])
        ordinary = native.resolve_concepts(self.repo, ["曲面积分"], "after_attempt", 10000)
        self.assertEqual("budget_too_small", ordinary["status"])
        with mock.patch.object(native, "build_index", side_effect=AssertionError("no rebuild")), \
             mock.patch.object(Path, "rglob", side_effect=AssertionError("no scan")), \
             mock.patch.object(native, "resolve_concepts", side_effect=AssertionError("no full history fallback")), \
             mock.patch.object(profiles, "resolve", wraps=profiles.resolve) as query:
            result = teaching.resolve_teaching_concepts(self.repo, ["曲面积分"], "after_attempt")
        self.assertEqual(1, query.call_count)
        self.assertEqual("available", result["status"])
        self.assertLessEqual(len(native.canonical(result).encode()), 10000)
        self.assertEqual(1, result["returned"])
        profile = result["records"][0]
        self.assertEqual(native.concept_key("曲面积分"), profile["concept_key"])
        self.assertEqual("evidence_digest_only", profile["status"])
        self.assertIn("40 条明确绑定本知识点", profile["short_summary"])
        self.assertNotIn("summary", profile)
        self.assertNotIn("history", profile)
        self.assertNotIn("SECRET-ENDPOINT", json.dumps(result))

    def test_explicit_bounded_evidence_projection_preserves_observation_anchors(self):
        import math_concept_index as native
        self.build_concept_fixtures([self.concept_event_fixture()])
        # The legacy projection is still independently useful for an explicit
        # evidence inspection, but is no longer the default teaching route.
        result = native.resolve_concepts(
            self.repo, ["曲面积分"], "after_attempt", 10000,
            record_projection=teaching.teaching_record_projection,
        )
        self.assertEqual("available", result["status"])
        self.assertLessEqual(len(native.canonical(result).encode()), 10000)
        event = result["records"][0]
        summary = event["summary"]
        self.assertEqual(40, summary["observation_total"])
        self.assertEqual(37, summary["observations_omitted"])
        rows = summary["observations"]
        self.assertEqual([39, 38, 0], [row["source_observation_index"] for row in rows])
        self.assertEqual("corrected_after_hint", rows[0]["outcome"])
        self.assertEqual("先区分几何对象。", rows[0]["hint_evidence"][0]["quote"])
        self.assertIn("第38题", rows[1]["error_detail"])
        self.assertNotIn("SECRET-ENDPOINT", json.dumps(result))

    def test_new_question_sees_cross_question_formal_and_review_observations(self):
        import math_learning_profiles as profiles
        records = [self.concept_event_fixture(count=2),
                   self.concept_event_fixture(kind="formal_concept_observation", count=2)]
        self.build_concept_fixtures(records)
        with mock.patch.object(teaching, "resolve_context", side_effect=AssertionError("no current formal ID")):
            result = teaching.resolve_teaching_concepts(self.repo, [records[0]["concept_key"]], "after_attempt")
        self.assertEqual("available", result["status"])
        self.assertIsNone(result["identity"])
        self.assertEqual(1, result["returned"])
        self.assertIn("4 条明确绑定本知识点", result["records"][0]["short_summary"])
        self.assertIn("outcome=corrected_after_hint", result["records"][0]["short_summary"])
        self.assertIn("hint_dependency=assisted", result["records"][0]["short_summary"])
        self.assertNotIn("提示后区分曲面与投影", result["records"][0]["short_summary"])
        self.assertNotIn("SECRET-ENDPOINT", json.dumps(result))
        # Raw record kinds, source observations and attribution belong to the
        # explicit evidence route; the default returns one prepared profile.
        with mock.patch.object(profiles, "resolve", side_effect=AssertionError("explicit history must not use profiles")), \
             mock.patch.object(teaching, "resolve_context", side_effect=AssertionError("no current formal ID")), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            code = teaching.main(["--repo", str(self.repo), "resolve", "--concept", records[0]["concept_key"],
                                  "--full-evidence", "--view", "after_attempt", "--max-bytes", "100000"])
        evidence = json.loads(output.getvalue())
        self.assertEqual(0, code)
        self.assertEqual("available", evidence["status"])
        self.assertFalse(evidence["truncated"])
        kinds = {row["kind"] for row in evidence["records"]}
        self.assertTrue({"concept_review", "formal_concept_observation"} <= kinds)
        formal = next(row for row in evidence["records"] if row["kind"] == "formal_concept_observation")
        self.assertEqual("GS-901", formal["formal_id"])
        self.assertTrue(any("提示后区分曲面与投影" in obs["error_detail"]
                            for obs in formal["summary"]["observations"]))
        self.assertEqual(1, formal["summary"]["observations"][0]["user_evidence"][0]["sequence"])
        self.assertIn("current_attempt_is_authoritative", evidence["evidence_policy"])
        self.assertTrue(formal["not_proof_of_same_error"])

    def test_protected_concept_query_never_reintroduces_observations_or_hint_text(self):
        self.build_concept_fixtures([self.concept_event_fixture()])
        result = teaching.resolve_teaching_concepts(self.repo, ["曲面积分"], "protected")
        text = json.dumps(result, ensure_ascii=False)
        for secret in ("先区分几何对象", "SECRET-ENDPOINT", "误当平面投影", "GS-900_fixture.md"):
            self.assertNotIn(secret, text)
        self.assertTrue(all("summary" not in row for row in result["records"]))

    def test_long_evidence_is_explicit_omission_not_misleading_prefix(self):
        claim = "看起来会做，" * 100 + "但这不表示独立掌握。"
        projected = teaching._teaching_atom(claim)
        self.assertTrue(projected["omitted"])
        self.assertEqual(teaching.sha256_value(claim), projected["sha256"])
        self.assertNotIn("text", projected)

    def test_tiny_budget_does_not_trigger_retry_or_unbounded_fallback(self):
        import math_concept_index as native
        import math_learning_profiles as profiles
        self.build_concept_fixtures([self.concept_event_fixture()])
        with mock.patch.object(profiles, "resolve", wraps=profiles.resolve) as query, \
             mock.patch.object(native, "resolve_concepts", side_effect=AssertionError("no full history fallback")), \
             mock.patch.object(native, "build_index", side_effect=AssertionError("no rebuild")):
            result = teaching.resolve_teaching_concepts(self.repo, ["曲面积分"], "after_attempt", 100)
        self.assertEqual(1, query.call_count)
        self.assertEqual("budget_too_small", result["status"])
        self.assertEqual([], result["records"])

    def test_later_review_invalidates_frozen_prior_without_revealing_answer(self) -> None:
        teaching.materialize_context(self.repo, self.context)
        rollback = self.repo / "数学一回滚复习系统"
        rollback.mkdir(exist_ok=True)
        event = {"event_id": "SCORE-later", "delivered_card_id": self.formal_id,
                 "date": "2026-09-07", "score": 5, "attempt_type": "review_document_check",
                 "review_outcome": {"user_answer_text": "protected endpoint PRIVATE_ANSWER_SENTINEL", "correction_text": "final answer PRIVATE_ANSWER_SENTINEL", "independent_correct": True}}
        (rollback / "复习记录.jsonl").write_text(json.dumps(event) + "\n")
        result = teaching.resolve_context(self.repo, self.formal_id, "protected")
        self.assertEqual("available_current_state", result["status"])
        self.assertEqual("learning_state_changed", result["reason_code"])
        self.assertEqual({}, result["prior"])
        self.assertEqual("SCORE-later", result["personal_context"]["current"]["review_events"][-1]["event_id"])
        # Numeric fragments may legitimately occur in timestamps or hashes.
        self.assertNotIn("PRIVATE_ANSWER_SENTINEL", json.dumps(result))

    def test_optional_related_decode_and_read_failures_preserve_current_and_other_related(self) -> None:
        directory = self.repo / "错题知识网络/wiki/topics/knowledge_clusters"
        directory.mkdir(parents=True)
        (directory / "MATHWIKI-KNOWLEDGE-001_曲面积分.md").write_text(
            "---\nwiki_id: MATHWIKI-KNOWLEDGE-001\ntitle: 曲面积分\n---\n"
            "| GS-903 | broken |\n| GS-902 | unreadable |\n| GS-901 | valid |\n")
        (self.cards / "GS-903_bad.md").write_bytes(b"\xff")
        for identity in ("GS-901", "GS-902"):
            (self.cards / (identity + "_fixture.md")).write_text(
                "---\nid: " + identity + "\nknowledge:\n  - 曲面积分\n---\n")
        teaching.materialize_context(self.repo, self.context)
        original = Path.read_bytes

        def read(path):
            if path.name == "GS-902_fixture.md":
                raise PermissionError("fixture optional card unreadable")
            return original(path)

        with mock.patch.object(Path, "read_bytes", read):
            result = teaching.resolve_context(self.repo, self.formal_id, "protected")
        personal = result["personal_context"]
        self.assertEqual("available", result["status"])
        self.assertEqual("available", personal["status"])
        self.assertEqual("partial", personal["related_status"])
        self.assertEqual(self.formal_id, personal["current"]["formal_id"])
        self.assertEqual(["GS-901"], [row["formal_id"] for row in personal["related"]])
        self.assertEqual({"GS-902", "GS-903"}, {row["formal_id"] for row in personal["unavailable_related"]})
        self.assertTrue(result["prior"])
        self.assertEqual("current_bound", result["historical_prior_status"])

    def test_verified_prior_cannot_mask_unavailable_current_state(self) -> None:
        teaching.materialize_context(self.repo, self.context)
        with mock.patch.object(teaching.math_learning_state, "personal_context", side_effect=OSError("current read failed")):
            result = teaching.resolve_context(self.repo, self.formal_id, "protected")
        self.assertEqual("unavailable", result["status"])
        self.assertEqual({}, result["prior"])
        self.assertEqual("discarded_current_state_unavailable", result["historical_prior_status"])

    def test_prior_is_discarded_when_verified_binding_differs_from_returned_current(self) -> None:
        teaching.materialize_context(self.repo, self.context)
        personal = teaching.math_learning_state.personal_context(self.repo, self.formal_id)
        personal["current"]["source_version"] = "0" * 64
        with mock.patch.object(teaching.math_learning_state, "personal_context", return_value=personal):
            result = teaching.resolve_context(self.repo, self.formal_id, "protected")
        self.assertEqual("available_current_state", result["status"])
        self.assertEqual({}, result["prior"])
        self.assertEqual("discarded_learning_state_changed", result["historical_prior_status"])

    def test_large_history_is_bounded_preserves_anchors_and_exact_source_without_writes(self) -> None:
        learning = teaching.math_learning_state
        rollback = self.repo / "数学一回滚复习系统"
        rollback.mkdir()
        log = rollback / "复习记录.jsonl"
        events = [{"event_id": "SCORE-" + str(i), "delivered_card_id": self.formal_id,
                   "date": "2026-09-07", "score": 3, "review_outcome": {}}
                  for i in range(2000)]
        events[31]["review_outcome"] = {"correction_text": "最新纠正 SECRET9876", "independent_correct": False}
        events[47]["review_outcome"] = {"hint_dependency": "l3", "independent_correct": False}
        # Physical line numbers must not trust a similarly named payload field.
        events[31]["ledger_position"] = 99999
        log.write_text("\n" + "\n".join(json.dumps(e) for e in events) + "\n")
        before = log.read_bytes(), self.card_path.read_bytes()
        full = learning.load_state(self.repo, self.formal_id)
        for view in ("protected", "after_attempt", "direct"):
            with self.subTest(view=view):
                state = learning.view_state(full, view)
                rows = state["review_events"]
                by_id = {row["event_id"]: row for row in rows}
                window = state["review_history_window"]
                self.assertLessEqual(len(rows), learning.MAX_TEACHING_EVENTS)
                self.assertLessEqual(len(learning.canonical(rows)), learning.MAX_TEACHING_REVIEW_BYTES)
                self.assertEqual(2000, window["total_count"])
                self.assertTrue(window["truncated"])
                self.assertEqual({"SCORE-0", "SCORE-31", "SCORE-47", "SCORE-1999"} - set(by_id), set())
                self.assertEqual("l3", by_id["SCORE-47"]["hint_dependency"])
                self.assertFalse(by_id["SCORE-47"]["independent_correct"])
                original = json.loads(log.read_text().splitlines()[by_id["SCORE-31"]["source_line"] - 1])
                self.assertEqual("SCORE-31", original["event_id"])
                self.assertEqual("数学一回滚复习系统/复习记录.jsonl", window["source_path"])
                self.assertEqual(full["source_version"], state["source_version"])
                if view == "direct":
                    self.assertEqual("最新纠正 SECRET9876", by_id["SCORE-31"]["correction_text"])
                else:
                    self.assertNotIn("SECRET9876", json.dumps(state))
        self.assertEqual(before, (log.read_bytes(), self.card_path.read_bytes()))
        self.assertEqual(2000, len(full["review_events"]))
        # A fixture-only refresh still materializes the complete canonical state.
        learning.refresh_states(self.repo, [self.formal_id])
        projection = json.loads(learning.state_path(self.repo, self.formal_id).read_text())
        self.assertEqual(2000, len(projection["review_events"]))
        self.assertEqual(full["source_version"], projection["source_version"])

    def test_oversized_event_and_formal_text_use_marked_bounded_excerpts(self) -> None:
        learning = teaching.math_learning_state
        rollback = self.repo / "数学一回滚复习系统"
        rollback.mkdir()
        event = {"event_id": "SCORE-large", "delivered_card_id": self.formal_id,
                 "review_outcome": {"correction_text": "纠正内容" * 20000, "hint_dependency": "l4"}}
        (rollback / "复习记录.jsonl").write_text(json.dumps(event) + "\n")
        self.card_path.write_text(self.card_path.read_text().replace(
            'wrong_point: "没有先区分积分曲面与投影区域，直接把两者混用。"',
            'wrong_point: "' + "错误证据" * 20000 + '"'))
        state = learning.view_state(learning.load_state(self.repo, self.formal_id), "direct")
        row = state["review_events"][0]
        self.assertLessEqual(len(learning.canonical(row)), learning.MAX_TEACHING_EVENT_BYTES)
        self.assertTrue(row["content_truncated"])
        self.assertIn("correction_text", row["truncated_fields"])
        self.assertEqual("l4", row["hint_dependency"])
        self.assertEqual(1, row["source_line"])
        self.assertTrue(state["formal_history_window"]["truncated"])
        self.assertLessEqual(len(learning.canonical(state["formal_history"])), learning.MAX_TEACHING_FORMAL_BYTES)

    def test_formal_history_keeps_initial_and_latest_evidence_with_exact_indices(self) -> None:
        learning = teaching.math_learning_state
        full = learning.load_state(self.repo, self.formal_id)
        for field in ("wrong_history", "mastery_history"):
            full["formal_history"][field] = ["first evidence"] + ["long evidence" * 1000] * 100 + ["latest correction"]
        state = learning.view_state(full, "direct")
        for field in ("wrong_history", "mastery_history"):
            self.assertEqual("first evidence", state["formal_history"][field][0])
            self.assertEqual("latest correction", state["formal_history"][field][-1])
            window = state["formal_history_window"]["event_windows"][field]
            self.assertEqual(102, window["total_count"])
            self.assertEqual(0, window["source_indices"][0])
            self.assertEqual(101, window["source_indices"][-1])
            self.assertTrue(window["truncated"])
        self.assertLessEqual(len(learning.canonical(state["formal_history"])), learning.MAX_TEACHING_FORMAL_BYTES)
        self.assertEqual(102, len(full["formal_history"]["wrong_history"]))

    def test_current_and_three_related_have_bounded_complete_teaching_output(self) -> None:
        learning = teaching.math_learning_state
        directory = self.repo / "错题知识网络/wiki/topics/knowledge_clusters"
        directory.mkdir(parents=True)
        (directory / "MATHWIKI-KNOWLEDGE-001_曲面积分.md").write_text(
            "---\nwiki_id: MATHWIKI-KNOWLEDGE-001\ntitle: 曲面积分\n---\n"
            + "".join("| GS-" + str(i) + " | related |\n" for i in (901, 902, 903)))
        for i in (901, 902, 903):
            (self.cards / ("GS-" + str(i) + "_fixture.md")).write_text(
                self.card_path.read_text().replace("id: GS-900", "id: GS-" + str(i)))
        rollback = self.repo / "数学一回滚复习系统"
        rollback.mkdir()
        events = [{"event_id": "SCORE-" + str(i) + "-" + str(j), "delivered_card_id": "GS-" + str(i),
                   "review_outcome": {"correction_text": "correction" * 3000, "hint_dependency": "l3"}}
                  for i in (900, 901, 902, 903) for j in range(50)]
        log = rollback / "复习记录.jsonl"
        log.write_text("\n".join(json.dumps(event) for event in events) + "\n")
        before = log.read_bytes()
        result = learning.personal_context(self.repo, self.formal_id, "direct")
        self.assertEqual(3, result["related_read_count"])
        self.assertLessEqual(len(learning.canonical(result)), result["teaching_view_limits"]["byte_limit"])
        for state in [result["current"]] + result["related"]:
            # Related adds one short match_kind label outside the state budget.
            state = {k: v for k, v in state.items() if k != "match_kind"}
            self.assertLessEqual(len(learning.canonical(state)), learning.MAX_TEACHING_STATE_BYTES)
            self.assertTrue(state["review_history_window"]["truncated"])
            self.assertEqual("SCORE-" + state["formal_id"][3:] + "-49", state["review_events"][-1]["event_id"])
            self.assertEqual("l3", state["review_events"][-1]["hint_dependency"])
        self.assertEqual(before, log.read_bytes())

    def test_oversized_optional_metadata_cannot_expand_teaching_state(self) -> None:
        learning = teaching.math_learning_state
        full = learning.load_state(self.repo, self.formal_id)
        full["related_review_units"] = [{"note": "x" * 10000}] * 100
        state = learning.view_state(full, "direct")
        self.assertLessEqual(len(learning.canonical(state)), learning.MAX_TEACHING_STATE_BYTES)
        self.assertIn("related_review_units", state["teaching_view_limits"]["metadata_truncated_fields"])
        self.assertEqual(self.formal_id, state["formal_id"])
        self.assertEqual(full["source_version"], state["source_version"])

    def test_pointer_is_not_replaced_when_last_atomic_write_fails(self) -> None:
        first = teaching.materialize_context(self.repo, self.context)
        pointer = self.repo / first["pointer_path"]
        original_pointer = pointer.read_bytes()
        changed = self.make_context(first_break_text="历史首断点已被新的真实作答修订。")
        real_atomic_write = teaching._atomic_write

        def fail_pointer(path: Path, payload: bytes) -> None:
            if path.name == "current.json":
                raise OSError("simulated pointer failure")
            real_atomic_write(path, payload)

        with mock.patch.object(teaching, "_atomic_write", side_effect=fail_pointer):
            with self.assertRaisesRegex(OSError, "simulated pointer failure"):
                teaching.materialize_context(self.repo, changed)

        self.assertEqual(original_pointer, pointer.read_bytes())
        still_current = teaching.resolve_context(self.repo, self.formal_id, "after_attempt")
        self.assertEqual(
            self.context["prior"]["first_break"]["text"],
            still_current["prior"]["first_break"]["text"],
        )

    def test_cli_materialize_resolve_and_verify(self) -> None:
        import math_concept_index
        input_path = self.repo / "context-input.json"
        input_path.write_text(json.dumps(self.context, ensure_ascii=False), encoding="utf-8")

        # Materializing an exact-card historical slice does not build the
        # prepared concept profiles used by ordinary teaching.
        math_concept_index.build_index(self.repo)

        outputs: list[dict] = []
        for argv in (
            ["--repo", str(self.repo), "materialize", "--input", str(input_path)],
            ["--repo", str(self.repo), "resolve", "--formal-id", self.formal_id, "--view", "protected"],
            ["--repo", str(self.repo), "resolve", "--formal-id", self.formal_id, "--view", "protected", "--full-evidence"],
            ["--repo", str(self.repo), "verify", "--formal-id", self.formal_id],
        ):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                self.assertEqual(0, teaching.main(argv))
            outputs.append(json.loads(buffer.getvalue()))

        self.assertEqual(teaching.RECEIPT_SCHEMA, outputs[0]["schema_version"])
        self.assertEqual("available", outputs[1]["status"])
        self.assertEqual(self.formal_id, outputs[1]["identity"]["formal_id"])
        self.assertEqual(math_concept_index.concept_key("曲面积分"), outputs[1]["records"][0]["concept_key"])
        self.assertNotIn("prior", outputs[1])
        self.assertEqual("available", outputs[2]["status"])
        self.assertEqual(teaching.VIEW_SCHEMA, outputs[2]["schema_version"])
        self.assertEqual("prior_only", outputs[2]["prior"]["evidence_scope"])
        self.assertEqual("current_bound", outputs[2]["historical_prior_status"])
        self.assertEqual("valid", outputs[3]["status"])
        for result in outputs[1:3]:
            self.assertNotIn("this endpoint", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
