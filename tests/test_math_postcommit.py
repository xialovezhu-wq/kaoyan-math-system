from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "数学一回滚复习系统/scripts"))
sys.path.insert(0, str(ROOT / "错题知识网络/scripts"))
import math_postcommit
import math_learning_state
import test_scheduler_review_flow as flow
import test_quick_intake as intake


class MathPostcommitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.rollback = self.repo / "数学一回滚复习系统"
        self.cards = self.repo / "错题知识网络/错题卡"
        self.rollback.mkdir()
        self.cards.mkdir(parents=True)
        self.card = self.cards / "GS-900_fixture.md"
        self.card.write_text("---\nid: GS-900\nknowledge:\n  - 链式法则\nwrong_history:\n  - 2026-06-01 初次错误\nwrong_point: 混用两个变量\n---\n")
        self.units = self.rollback / "复习单元.json"
        self.units.write_text(json.dumps([{"复习单元ID": "MATH1-GS-WQ-GS900", "关联错题ID": "GS-900", "掌握度": 3, "下次复习日期": "2026-09-09"}]))
        self.event = {"event_id": "SCORE-fixture", "unit_id": "MATH1-GS-WQ-GS900", "delivered_card_id": "GS-900", "date": "2026-09-07", "score": 3, "attempt_type": "delayed"}
        self.log = self.rollback / "复习记录.jsonl"
        self.log.write_text(json.dumps(self.event) + "\n")

    def test_publication_failure_preserves_fact_and_fresh_local_state(self) -> None:
        before = self.log.read_bytes(), self.units.read_bytes(), self.card.read_bytes()
        with mock.patch.object(math_postcommit, "request_publication", side_effect=RuntimeError("simulated network failure")):
            result = math_postcommit.run_after_commit(self.repo, self.event["event_id"], publish=True)
        self.assertEqual("refreshed", result["local_refresh"]["status"])
        self.assertEqual("PENDING", result["publication"]["status"])
        self.assertEqual(before, (self.log.read_bytes(), self.units.read_bytes(), self.card.read_bytes()))
        current = math_learning_state.load_state(self.repo, "GS-900")
        self.assertEqual("SCORE-fixture", current["review_events"][-1]["event_id"])

    def test_same_event_recovers_publication_without_repeating_score(self) -> None:
        import math_memory_backends
        import math_memory_pending
        event_id = 'SCORE-' + 'a' * 24
        self.log.write_text(json.dumps({**self.event, 'event_id': event_id}) + '\n')
        source_before = (self.log.read_bytes(), self.units.read_bytes(), self.card.read_bytes())
        request = mock.Mock(side_effect=[{"status": "PENDING"}, {"status": "PUBLISHED", "source_commit": "a" * 40}])
        with mock.patch.object(math_postcommit, 'retrieval_required', return_value=True), \
                mock.patch.object(math_memory_backends, 'refresh_selected', side_effect=[
                    {'status': 'pending', 'reason': 'private fixture /Users/example/never-export'},
                    {'status': 'ready'}]), \
                mock.patch.object(math_memory_pending, 'refresh_pending', side_effect=[
                    {'status': 'pending', 'reason': 'optional fixture'}, {'status': 'noop'}]):
            first = math_postcommit.run_after_commit(self.repo, event_id, requester=request, publish=True)
            second = math_postcommit.run_after_commit(self.repo, event_id, requester=request, publish=True)
        self.assertEqual("local_updated_cloud_pending", first["status"])
        self.assertEqual("completed", second["status"])
        self.assertEqual(first["local_refresh"]["versions"], second["local_refresh"]["versions"])
        self.assertEqual(1, len(self.log.read_text().splitlines()))
        self.assertEqual(2, request.call_count)
        self.assertEqual(source_before, (self.log.read_bytes(), self.units.read_bytes(), self.card.read_bytes()))
        handoff = first['maintenance_summary']
        self.assertEqual(event_id, handoff['event_id'])
        self.assertEqual('committed', handoff['formal']['status'])
        self.assertEqual('pending', handoff['required_status'])
        self.assertIn('retrieval_backend', handoff['required_components'])
        self.assertIn('pending_memory', handoff['optional_components'])
        self.assertEqual('pending', handoff['components']['pending_memory']['status'])
        self.assertEqual('pending', handoff['publication']['status'])
        self.assertFalse(handoff['recovery']['formal_writer_replay'])
        self.assertNotIn('/Users/', json.dumps(handoff))
        self.assertEqual('published', second['maintenance_summary']['publication']['status'])
        self.assertEqual('ready', second['maintenance_summary']['required_status'])
        self.assertEqual(first['publication_event_id'], second['publication_event_id'])
        self.assertEqual('pending', second['prior_phase_failures'][0]['phases']['retrieval_backend']['status'])
        self.assertEqual('not_requested', math_postcommit.summarize_handoff(
            {**second, 'publication': {'status': 'NOT_REQUESTED'}}, second['native_generation'])['publication']['status'])
        self.assertEqual('stale', math_postcommit.summarize_handoff(second, 'f' * 64)['components']['concept_index']['status'])

    def test_refresh_only_and_versioned_successor_keep_business_fact(self):
        requester = mock.Mock(return_value={"status": "PUBLISHED"})
        first = math_postcommit.run_after_commit(self.repo, self.event["event_id"], requester=requester, publish=True)
        noop = math_postcommit.run_after_commit(self.repo, self.event["event_id"], requester=requester, publish=True)
        self.assertEqual(first["publication_event_id"], noop["publication_event_id"])
        self.card.write_text(self.card.read_text().replace("混用两个变量", "核对了变量且保留原始纠正"))
        refreshed = math_postcommit.run_after_commit(self.repo, self.event["event_id"], requester=requester, refresh_only=True)
        self.assertEqual(2, requester.call_count)
        self.assertEqual("NOT_REQUESTED", refreshed["publication"]["status"])
        final = math_postcommit.run_after_commit(self.repo, self.event["event_id"], requester=requester, publish=True)
        self.assertNotEqual(first["publication_event_id"], final["publication_event_id"])
        self.assertEqual(self.event["event_id"], final["event_id"])
        self.assertEqual(1, len(self.log.read_text().splitlines()))
        self.assertEqual(final["publication_event_id"], requester.call_args.kwargs["event_id"])

    def test_isolated_default_never_imports_production_publisher(self) -> None:
        requester = mock.Mock(side_effect=AssertionError("local refresh must not publish"))
        with mock.patch.object(math_postcommit, "request_publication", requester):
            result = math_postcommit.run_after_commit(self.repo, self.event["event_id"])
        self.assertEqual("completed_local", result["status"])
        self.assertEqual("NOT_REQUESTED", result["publication"]["status"])
        requester.assert_not_called()

    def test_isolated_explicit_publication_never_imports_production_publisher(self) -> None:
        with mock.patch.object(importlib.util, "spec_from_file_location", side_effect=AssertionError("production publisher must not load")):
            result = math_postcommit.run_after_commit(self.repo, self.event["event_id"], publish=True)
        self.assertEqual("ISOLATED_NO_PUBLICATION", result["publication"]["status"])

    def test_new_review_invalidates_cache_without_changing_card(self) -> None:
        math_learning_state.refresh_states(self.repo, ["GS-900"])
        before = math_learning_state.load_state(self.repo, "GS-900")
        card_hash = hashlib.sha256(self.card.read_bytes()).hexdigest()
        with self.log.open("a") as handle:
            handle.write(json.dumps({**self.event, "event_id": "SCORE-later", "date": "2026-09-08", "score": 5}) + "\n")
        after = math_learning_state.load_state(self.repo, "GS-900")
        self.assertNotEqual(before["source_version"], after["source_version"])
        self.assertEqual(card_hash, after["formal_card_sha256"])
        self.assertEqual(["SCORE-fixture", "SCORE-later"], [e["event_id"] for e in after["review_events"]])

    def test_unknown_event_cannot_create_postcommit_work(self) -> None:
        with self.assertRaisesRegex(ValueError, "not_unique"):
            math_postcommit.run_after_commit(self.repo, "SCORE-absent")
        self.assertFalse((self.rollback / "正式提交后续").exists())

    def test_concept_sync_follows_formal_scale_and_recovers_without_fact_replay(self) -> None:
        first = math_postcommit.run_after_commit(self.repo, self.event["event_id"], refresh_only=True)
        self.assertIn(first["concept_index"]["status"], ("ready", "noop"))
        found = math_postcommit.math_concept_index.resolve_concepts(self.repo, ["链式法则"], "after_attempt")
        self.assertEqual("available", found["status"])
        before = self.log.read_bytes()
        with mock.patch.object(math_postcommit.math_concept_index, "build_index", side_effect=RuntimeError("index interrupted")), \
             mock.patch.object(math_postcommit, "request_publication") as publish:
            failed = math_postcommit.run_after_commit(self.repo, self.event["event_id"])
        self.assertEqual("local_refresh_pending", failed["status"])
        publish.assert_not_called()
        self.assertEqual(before, self.log.read_bytes())
        recovered = math_postcommit.run_after_commit(self.repo, self.event["event_id"], refresh_only=True)
        self.assertEqual(first["concept_index"]["version"], recovered["concept_index"]["version"])
        self.assertEqual(before, self.log.read_bytes())

        (self.cards / "GS-901_fixture.md").write_text(
            "---\nid: GS-901\nknowledge:\n  - 链式法则\nwrong_history:\n  - 2026-09-08 新题复合层级漏项\n---\n")
        closeout = {"event_id": "CLOSE-new", "event_type": "closeout", "formal_results": [{"formal_id": "GS-901"}]}
        (self.rollback / "快速入库事件.jsonl").write_text(json.dumps(closeout) + "\n")
        with mock.patch.object(math_postcommit.math_concept_index, "build_index", side_effect=RuntimeError("formal index interrupted")):
            interrupted = math_postcommit.run_after_commit(self.repo, "CLOSE-new", refresh_only=True)
        self.assertEqual("local_refresh_pending", interrupted["status"])
        stale = math_postcommit.math_concept_index.resolve_concepts(self.repo, ["链式法则"], "after_attempt")
        self.assertEqual("stale", stale["status"])
        after = math_postcommit.run_after_commit(self.repo, "CLOSE-new", refresh_only=True)
        self.assertNotEqual(first["concept_index"]["version"], after["concept_index"]["version"])
        found = math_postcommit.math_concept_index.resolve_concepts(self.repo, ["链式法则"], "after_attempt")
        self.assertEqual(2, found["coverage"]["expected_count"])
        self.assertEqual(2, found["coverage"]["matched_formal_count"])

    def test_proxy_refreshes_anchor_schedule_and_delivered_history_separately(self) -> None:
        other = self.cards / "GS-901_fixture.md"
        other.write_text("---\nid: GS-901\nknowledge:\n  - 链式法则\n---\n")
        self.log.write_text(json.dumps({**self.event, "delivered_card_id": "GS-901"}) + "\n")
        result = math_postcommit.run_after_commit(self.repo, self.event["event_id"])
        self.assertEqual(["GS-900", "GS-901"], result["formal_ids"])
        anchor = math_learning_state.load_state(self.repo, "GS-900")
        delivered = math_learning_state.load_state(self.repo, "GS-901")
        self.assertEqual([], anchor["review_events"])
        self.assertEqual(3, anchor["scheduling"]["掌握度"])
        self.assertEqual("SCORE-fixture", delivered["review_events"][0]["event_id"])
        self.assertIsNone(delivered["scheduling"])

    def test_singleton_concepts_do_not_hide_available_related_history(self) -> None:
        self.card.write_text("---\nid: GS-900\nknowledge:\n  - 单独一\n  - 单独二\n  - 链式法则\n---\n")
        (self.cards / "GS-901_fixture.md").write_text("---\nid: GS-901\nknowledge:\n  - 链式法则\nwrong_point: 未区分两个变量\n---\n")
        directory = self.repo / "错题知识网络/wiki/topics/knowledge_clusters"
        directory.mkdir(parents=True)
        for index, label in enumerate(("单独一", "单独二", "链式法则"), 1):
            text = f"---\nwiki_id: MATHWIKI-KNOWLEDGE-{index:03d}\ntitle: {label}\n---\n| GS-900 | current |\n"
            if label == "链式法则":
                text += "| GS-901 | related |\n"
            (directory / f"MATHWIKI-KNOWLEDGE-{index:03d}_{label}.md").write_text(text)
        result = math_learning_state.personal_context(self.repo, "GS-900", "after_attempt")
        self.assertEqual(1, result["related_read_count"])
        self.assertEqual("GS-901", result["related"][0]["formal_id"])
        self.assertEqual("literal_shared_knowledge_not_proof_of_same_error", result["related"][0]["match_kind"])

    def test_method_unit_link_is_not_a_second_wrong_card_schedule_or_attempt(self) -> None:
        units = json.loads(self.units.read_text())
        units.append({"复习单元ID": "METHOD-fixture", "关联错题ID": "GS-900", "类型": "方法模板", "掌握度": 5})
        self.units.write_text(json.dumps(units))
        with self.log.open("a") as handle:
            handle.write(json.dumps({"event_id": "SCORE-method", "unit_id": "METHOD-fixture", "date": "2026-09-08", "score": 5}) + "\n")
        state = math_learning_state.load_state(self.repo, "GS-900")
        self.assertEqual("MATH1-GS-WQ-GS900", state["scheduling"]["复习单元ID"])
        self.assertEqual(["SCORE-fixture"], [x["event_id"] for x in state["review_events"]])
        self.assertEqual("METHOD-fixture", state["related_review_units"][0]["复习单元ID"])
        self.assertEqual("SCORE-method", state["related_unit_reviews"][0]["event_id"])
        self.assertIsNone(state.get("scheduling_conflict"))


class ScorerPostcommitBoundaryTests(unittest.TestCase):
    def test_closeout_hook_is_outside_both_locks_and_runs_on_noop(self) -> None:
        fixture = intake.QuickIntakeTests("test_08_closeout_requires_all_layers_and_is_idempotent")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        score = fixture.append_score_event()
        capture = fixture.invoke_record(fixture.payload(score_event_id=score))
        payload = fixture.closeout_payload(capture["event_id"])
        calls = []

        def hook(repo, event_id):
            self.assertEqual(fixture.base, repo)
            for path in (intake.quick_intake.FORMAL_LOCK_PATH, intake.quick_intake.LOCK_PATH):
                descriptor = os.open(path, os.O_RDWR)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
            calls.append(event_id)
            return {"publication": {"status": "ISOLATED_NO_PUBLICATION"}}

        with mock.patch.object(math_postcommit, "run_after_commit", side_effect=hook):
            first = fixture.invoke_close(payload)
            before = fixture.events_path.read_bytes()
            second = fixture.invoke_close(payload)
        self.assertEqual("recorded", first["status"])
        self.assertEqual("noop", second["status"])
        self.assertEqual(before, fixture.events_path.read_bytes())
        self.assertEqual([first["closeout_id"], first["closeout_id"]], calls)

    def test_hook_is_outside_score_lock_and_runs_on_noop(self) -> None:
        fixture = flow.SchedulerReviewFlowTests("test_repeated_score_attempt_advances_once")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        unit = flow.review_unit("GS-908", next_date="2026-07-17", recent_recurrence="2026-07-16", targeted=True)
        fixture.write_card("GS-908", method_gap=fixture.confirmed_gap())
        fixture.write_units([unit])
        calls = []

        def hook(repo, event_id):
            self.assertEqual(fixture.base, repo)
            descriptor = os.open(fixture.rollback / ".延迟复习评分.lock", os.O_RDWR)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
            calls.append(event_id)
            return {"publication": {"status": "ISOLATED_NO_PUBLICATION"}}

        with mock.patch.object(math_postcommit, "run_after_commit", side_effect=hook):
            fixture.invoke_score(unit["复习单元ID"], 4, day="2026-07-17")
            fixture.invoke_score(unit["复习单元ID"], 4, day="2026-07-17")
        self.assertEqual(2, len(calls))
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(1, len(fixture.jsonl(fixture.review_log_path)))
        self.assertEqual(1, len(fixture.read_units()[0]["评分事件历史"]))


    def test_publisher_loads_sibling_dependency_without_leaking_import_path(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name)
        sibling = self.repo / "fixture_publication_dependency.py"
        sibling.write_text("VALUE = 'PUBLISHED'\n")
        publisher = self.repo / "fixture_publisher.py"
        publisher.write_text("import fixture_publication_dependency\ndef request_publication(**kwargs):\n    return {'status': fixture_publication_dependency.VALUE}\n")
        before_path = list(sys.path)
        with mock.patch.object(math_postcommit, "PUBLICATION_SCRIPT", publisher), mock.patch.object(math_postcommit, "PRODUCTION_ROOT", self.repo), mock.patch.dict(sys.modules):
            sys.modules.pop("_math_shared_study_publication", None)
            result = math_postcommit.request_publication(subject="math", event_id="fixture", repo_root=self.repo)
            self.assertEqual("PUBLISHED", result["status"])
        self.assertEqual(before_path, sys.path)


if __name__ == "__main__":
    unittest.main()
