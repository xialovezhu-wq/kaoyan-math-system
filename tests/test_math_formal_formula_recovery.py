"""Exercise a native closeout and its formula retry with a fake model service."""

import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import math_concept_index as index
import math_formal_observations as observations
import math_formal_quality as quality
import math_formal_quality_api as provider
import math_formula_cards as cards
import math_postcommit as postcommit
import math_recap as recap
import quick_intake as intake


PROJECT = Path(__file__).resolve().parents[1]
STUDY_DAY = "2026-01-01"
FORMAL_ID = "GS-98760"
CONCEPT = "实数平方的非负性"
ATTEMPT = "fixture:formal-formula"
RAW_USER = "FIXTURE_RAW_USER_TURN"
RAW_ASSISTANT = "FIXTURE_RAW_ASSISTANT_TURN"


class FormalFormulaRecoveryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.work = self.root / "quality-work"
        self.work.mkdir()
        rollback = self.root / "数学一回滚复习系统"
        network = self.root / "错题知识网络"
        self.formal = network / "错题卡" / f"{FORMAL_ID}_fixture.md"
        self.wiki = network / "wiki"
        self.generated = network / "生成"
        self.events = rollback / "快速入库事件.jsonl"
        self.units = rollback / "复习单元.json"
        self.score_log = rollback / "复习记录.jsonl"
        self.write_text(self.score_log, "")
        quality.write(self.units, [])
        self.write_text(self.formal, f"""---
id: {FORMAL_ID}
title: 合成题卡
subject: 高等数学
status: 待复做
knowledge:
  - "{CONCEPT}"
---

## 题目摘要
合成练习。
""")
        for relative in (cards.RENDERER, "错题知识网络/scripts/math_formula_cards.py",
                         "错题知识网络/schema/formula_card_v1.json"):
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROJECT / relative, self.root / relative)

        runtime = patch.multiple(
            intake, ROOT=rollback, REPO_ROOT=self.root, EVENTS_PATH=self.events,
            LOCK_PATH=rollback / ".快速入库事件.lock", FORMAL_LOCK_PATH=rollback / ".正式层写入.lock",
            SOURCE_STAGING_ROOT=rollback / "快速入库来源", SOURCE_LOCK_PATH=rollback / ".快速入库来源.lock",
            REVIEW_LOG_PATH=self.score_log, UNITS_PATH=self.units, CARDS_DIR=self.formal.parent,
            WRONGNET_SNAPSHOT_PATH=self.generated / "wrong_questions.json", WIKI_ROOT=self.wiki,
        )
        runtime.start()
        self.addCleanup(runtime.stop)
        for module, name in ((provider, "transport"), (postcommit, "request_publication")):
            blocked = patch.object(module, name, side_effect=AssertionError(f"unexpected external call: {name}"))
            blocked.start()
            self.addCleanup(blocked.stop)
        self.requests = []
        self.install_reference_topic()

    @staticmethod
    def write_text(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def ref(self, path):
        return {"path": path.relative_to(self.root).as_posix(), "sha256": cards.sha(path.read_bytes())}

    def invoke(self, command, key, payload):
        request = self.work / f"{command.__name__}.json"
        quality.write(request, payload)
        stream = io.StringIO()
        with redirect_stdout(stream):
            command(argparse.Namespace(**{key: str(request)}))
        return json.loads(stream.getvalue())

    def install_reference_topic(self):
        self.reference = self.root / "synthetic-reference.txt"
        self.write_text(self.reference, "绝对值给出实数到原点的距离。")
        quality.write(self.root / recap.BASE / "topics/fixture.json", {
            "schema": recap.TOPIC_SCHEMA, "topic_id": "MRC-fixture",
            "title": "实数距离", "subject": "高等数学", "chapter": "实数",
            "concept_keys": ["实数距离"], "entries": [{
                "entry_id": "MRC-fixture-distance", "section": "secondary_conclusions",
                "name": "实数距离", "content": "$$\n|x|\\ge 0\n$$",
                "conditions": ["x 是实数"], "source_refs": [self.ref(self.reference)],
                "review": {"status": "verified", "basis": "synthetic fixture", "reviewed_at": STUDY_DAY},
            }],
        })
        recap.build(self.root)

    def freeze_capture(self):
        staged = self.invoke(intake.cmd_stage_source, "payload_file", {
            "schema_version": intake.SOURCE_STAGE_SCHEMA_V2, "package_key": ATTEMPT,
            "study_date": STUDY_DAY, "timezone": "Asia/Shanghai",
            "source": {"source_locator": ATTEMPT, "capture_identity": ATTEMPT, "session_id": "fixture-session"},
            "conversation": [{"role": "user", "text": RAW_USER},
                             {"role": "assistant", "text": RAW_ASSISTANT}],
            "artifacts": [], "missing_fields": [],
        })
        capture = self.invoke(intake.cmd_record, "payload_file", {
            "schema_version": intake.CAPTURE_SCHEMA_V3, "attempt_id": ATTEMPT,
            "study_date": STUDY_DAY, "requested_action": "record_recurrence", "score_event_id": None,
            "target": {"kind": "formal_card", "formal_id": FORMAL_ID,
                       "source_locator": None, "source_hash_before": None},
            "thread_ref": "fixture-thread",
            "conversation_package": {k: staged[k] for k in ("manifest_path", "manifest_hash", "package_sha256")},
        })
        cid = capture["event_id"]
        result = self.invoke(intake.cmd_freeze, "payload_file", {
            "schema_version": intake.FREEZE_SCHEMA, "study_date": STUDY_DAY, "scope": "all_pending_for_date",
            "capture_event_ids": [cid], "target_resolutions": [{
                "formal_id": FORMAL_ID, "capture_event_ids": [cid], "identity_mode": "existing_formal",
                "source_binding": None,
            }],
        })
        freeze = intake.replay(intake.load_jsonl(self.events))["freezes"][result["freeze_id"]]
        return cid, freeze

    def install_candidate_catalog(self):
        version = index.build_index(self.root)["version"]
        key = index.concept_key(CONCEPT)
        folder = self.root / "错题知识网络/个人知识点索引/memory-backends"
        discovery, reference = folder / "discovery.json", folder / "reference.json"
        quality.write(discovery, {"source_version": version, "documents": [{
            "id": key, "title": CONCEPT, "text": "比较实数平方的符号",
        }]})
        quality.write(reference, {"source_version": version,
                                 "content_policy": "mathematical_reference_no_learner_evidence",
                                 "documents": [{"concept_key": key, "fragments": [{
                                     "id": "fixture-square", "kind": "formula", "text": "实数平方非负",
                                     "source_refs": [self.ref(self.reference)],
                                 }]}]})
        quality.write(folder / "config.json", {
            "backends": {"native": {"corpus_path": str(discovery), "corpus_sha256": self.ref(discovery)["sha256"]}},
            "reference_semantic": {"mathematical_reference_path": str(reference),
                                   "mathematical_reference_sha256": self.ref(reference)["sha256"]},
        })

    def fake_request(self, endpoint, payload, **kwargs):
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(RAW_USER, serialized)
        self.assertNotIn(RAW_ASSISTANT, serialized)
        self.assertNotIn(str(self.root), serialized)
        self.requests.append(endpoint)
        response = {"model": payload["model"], "_request_id": f"fixture-{len(self.requests)}", "usage": {}}
        if endpoint == "embeddings":
            response["data"] = [{"index": i, "embedding": [1.0] * provider.DIMENSIONS}
                                for i in range(len(payload["input"]))]
        else:
            self.assertEqual("decisions", endpoint)
            response["answers"] = [{"name": row["name"], "type": "predicate", "probability": .94}
                                   for row in payload["questions"]]
        return response

    def prepare_proof(self, cid, freeze, declared_observations, prior):
        candidates = quality.begin(intake, self.work, {
            "schema": "math-formal-quality-scope-v1", "redacted": True, "freeze_id": freeze["event_id"],
            "units": [{"capture_id": cid, "mechanism": CONCEPT, "objects": "实数",
                       "conditions": "变量在实数域内", "goal": "判断平方的符号", "exact_labels": [CONCEPT],
                       "turns": [{"sequence": 1, "text": "检查平方的符号"},
                                 {"sequence": 2, "text": "先确认变量取实数"}], "attachments": {}}],
        }, request=self.fake_request)
        self.assertTrue(candidates["catalog"])
        refs = intake.freeze_response(freeze, "recorded", 0)["formal_bindings"][0]
        fields = []
        for field in ("fast_intake_refs", "fast_intake_source_refs"):
            if refs[field]:
                fields.append(f"{field}:")
                fields.extend("  - " + json.dumps(value, ensure_ascii=False) for value in refs[field])
        draft = self.formal.read_text().replace("\n---\n\n", "\n" + "\n".join(fields) + "\n---\n\n", 1)
        draft += f"\n## 可迁移结论\n\n### 公式：{CONCEPT}\n适用条件：变量是实数。\n\n$$\nx^2\\ge 0\n$$\n"
        self.write_text(self.work / "formal.md", draft)
        quality.write(self.work / "observations.json", declared_observations)
        quality.write(self.work / "prior.json", {FORMAL_ID: prior})
        quality.write(self.work / "outcomes.json", {cid: {
            "outcome": "recurrence_recorded", "reason": "合成练习用于检验复发登记",
        }})
        requirements = quality.requirements(intake, self.work, {
            "schema": "math-formal-quality-draft-v1",
            "cards": [{"formal_id": FORMAL_ID, "operation": "updated",
                       "path": self.formal.relative_to(self.root).as_posix(), "draft": "formal.md"}],
            "observations": "observations.json", "priors": "prior.json", "outcomes": "outcomes.json",
        })
        positions = requirements["entries"]
        result = quality.finalize(intake, self.work, {
            "schema": "math-quality-reviewed-v1", "requirements_sha256": quality.digest(requirements),
            "uses": {key: {"action": "keep_conditions", "position": f"card/{FORMAL_ID}/section/可迁移结论",
                           "reason": "保留实数域条件"} for key in candidates["judgments"]},
            "statements": {
                key: {**{field: value[field] for field in ("sha256", "classification", "units")},
                      "local_verified": True,
                      **({"text": "实数平方非负，须先核对定义域"} if value["classification"] == "api" else {})}
                for key, value in positions.items()
            },
        }, request=self.fake_request)
        self.assertEqual("QUALITY_PREPARED", result["status"])
        return Path(result["proof"])

    def write_companion_receipts(self, freeze, prior):
        card = self.ref(self.formal)
        binding = {
            "formal_card_path": card["path"], "formal_card_sha256": card["sha256"],
            "freeze_id": freeze["event_id"], "capture_event_ids": freeze["capture_event_ids"],
            "capture_bindings": intake.teaching_context_capture_bindings(freeze, FORMAL_ID),
            "formal_evidence_source_version": intake.formal_evidence_source_version_for_card(FORMAL_ID, self.formal),
            "capture_evidence_source_version": intake.teaching_context_capture_evidence_source_version(freeze, FORMAL_ID),
        }
        context = {"schema_version": intake.TEACHING_CONTEXT_SCHEMA, "formal_id": FORMAL_ID,
                   "source_bindings": binding, "prior": prior}
        scope = self.root / "错题知识网络/教学投影" / FORMAL_ID
        context_path = scope / "versions" / (cards.sha(quality.canonical(context)) + ".json")
        quality.write(context_path, context)
        context_ref = self.ref(context_path)
        pointer_path = scope / "current.json"
        quality.write(pointer_path, {
            "schema_version": intake.TEACHING_CONTEXT_POINTER_SCHEMA, "formal_id": FORMAL_ID,
            "context_path": context_ref["path"], "context_sha256": context_ref["sha256"],
            **{k: binding[k] for k in ("formal_card_path", "formal_card_sha256",
                                       "formal_evidence_source_version", "capture_evidence_source_version")},
        })
        pointer_ref = self.ref(pointer_path)

        projection = intake.current_formal_projections({FORMAL_ID})[FORMAL_ID]
        projection_hash = intake.sha256_value(projection)
        snapshot = self.generated / "wrong_questions.json"
        quality.write(snapshot, {"updated_at": STUDY_DAY, "cards": [projection], "similarities": [], "weak_relations": []})
        generated = [snapshot]
        for name in ("错题索引.md", "相似题清单.md", "强关联清单.md", "弱边审计清单.md",
                     "专题链关联清单.md", "错题网络概览.md", "按知识点复做清单.md", "知识网络图.mmd"):
            path = self.generated / name
            self.write_text(path, "合成目录生成物\n")
            generated.append(path)
        cluster = "MATHWIKI-KNOWLEDGE-001"
        wiki_summary = self.wiki / "sources/wrong_cards" / f"SRC-WQ-{FORMAL_ID}.md"
        self.write_text(wiki_summary, f"""---
wiki_id: SRC-WQ-{FORMAL_ID}
subject: 高等数学
last_updated: {STUDY_DAY}
formal_projection_sha256: {projection_hash}
knowledge:
  - "{CONCEPT}"
methods: []
error_causes: []
wrongnet_refs:
  - "{FORMAL_ID}"
source_refs:
  - "{card['path']}"
wiki_refs:
  - "{cluster}"
---

{FORMAL_ID}
""")
        self.write_text(self.wiki / "topics/knowledge_clusters" / f"{cluster}_fixture.md",
                        f"---\nwiki_id: {cluster}\n---\n\n{FORMAL_ID}\n")
        for name in ("sources/SRC-WRONGCARDS-INDEX_全量错题卡覆盖索引.md",
                     "coverage/MATHWIKI-COVERAGE-MATRIX_错题卡多维编译矩阵.md",
                     "coverage/MATHWIKI-COVERAGE-GS_fixture.md"):
            self.write_text(self.wiki / name, f"| {FORMAL_ID} | 合成行 |\n")
        summary = self.ref(wiki_summary)
        return {
            "wrongnet": {"rebuild_count": 1, "artifacts": list(map(self.ref, generated)),
                         "target_projection_hashes": {FORMAL_ID: projection_hash}},
            "relationships": {"state": "not_applicable", "proposals": []},
            "wiki": [{"formal_id": FORMAL_ID, "summary_path": summary["path"], "summary_hash": summary["sha256"]}],
            "visuals": [{"formal_id": FORMAL_ID, "state": "not_applicable", "artifacts": []}],
            "teaching_contexts": [{"formal_id": FORMAL_ID,
                                   "context_path": context_ref["path"], "context_sha256": context_ref["sha256"],
                                   "pointer_path": pointer_ref["path"], "pointer_sha256": pointer_ref["sha256"]}],
        }

    def test_formal_closeout_survives_projection_failure_and_resumes_same_event(self):
        cid, freeze = self.freeze_capture()
        self.install_candidate_catalog()
        declared_observations = {"schema": observations.SCHEMA, "targets": [{
            "formal_id": FORMAL_ID, "observations": [], "no_observation_reason": "合成例不设逐点观察",
        }]}
        prior = {"scope": "prior_only"}
        proof = self.prepare_proof(cid, freeze, declared_observations, prior)
        before_card = self.formal.read_bytes()
        applied = quality.apply_cards(intake, proof, request=self.fake_request)
        self.assertEqual("CARD_APPLIED", applied["status"])
        self.assertNotEqual(before_card, self.formal.read_bytes())
        self.assertEqual({"embeddings", "decisions"}, set(self.requests))

        card = self.ref(self.formal)
        recurrence = f"{FORMAL_ID}|{STUDY_DAY}|2"
        unit = {"复习单元ID": "MATH1-GS-WQ-fixture", "类型": "错题", "关联错题ID": FORMAL_ID,
                "定点同步状态": {"源版本": card["sha256"], "已处理错题事件ID": [recurrence]},
                "调度事件历史": [{"类型": "正式错题复发", "事件ID": recurrence, "复发日期": STUDY_DAY,
                                 "同步日期": STUDY_DAY, "源版本": card["sha256"]}]}
        quality.write(self.units, [unit])
        close = {
            "schema_version": intake.CLOSEOUT_SCHEMA, "freeze_id": freeze["event_id"], "model": "unknown",
            "formal_results": [{"formal_id": FORMAL_ID, "operation": "updated", "card_path_after": card["path"],
                                "card_hash_after": card["sha256"], "changed_fields": ["可迁移结论"]}],
            "capture_results": [{"capture_event_id": cid, "outcome": "recurrence_recorded", "formal_id": FORMAL_ID,
                                 "durable_record": {"store": "rollback_unit", "record_id": recurrence,
                                                    "record_hash": intake.sha256_value(unit)}}],
            "batch_receipts": self.write_companion_receipts(freeze, prior),
            "concept_observations": declared_observations,
        }
        write = cards.write

        def fail_formula_html(path, data):
            if path.name == "index.html" and "objects" in path.parts:
                raise OSError("fixture formula output unavailable")
            return write(path, data)

        with patch.object(cards, "write", side_effect=fail_formula_html):
            committed = self.invoke(intake.cmd_close, "receipt_file", close)
        self.assertEqual("recorded", committed["status"])
        failed = committed["postcommit"]
        self.assertEqual("formula_projection_pending", failed["status"])
        self.assertEqual("formula_asset_write_failed", failed["formula_projection"]["reason"])
        self.assertIsNone(cards.pointer(self.root))

        event = committed["closeout_id"]
        ledger = intake.replay(intake.load_jsonl(self.events))
        self.assertEqual({event}, set(ledger["closeouts"]))
        self.assertEqual(event, ledger["closed_by"][cid])
        originals = {path: path.read_bytes() for path in (self.formal, self.events, self.units, proof, self.score_log)}
        calls = list(self.requests)

        recovered = postcommit.resume_formula_only(self.root, event)
        self.assertEqual("READY", recovered["status"])
        self.assertFalse(recovered["formal_replay_allowed"])
        receipt = quality.read(self.root / recovered["postcommit_receipt_path"])
        self.assertEqual(event, receipt["event_id"])
        self.assertEqual("READY", receipt["formula_projection"]["status"])
        self.assertNotEqual("formula_projection_pending", receipt["status"])
        identity = f"FORMULA-{FORMAL_ID}-" + cards.digest(CONCEPT)[:16]
        formula = cards.lookup(self.root, identity, view="direct", full=True)
        self.assertEqual("ready", formula["status"])
        self.assertEqual(card, formula["card"]["source_refs"][0])
        self.assertIn("x^2", formula["card"]["conclusion_latex"])
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})
        self.assertEqual(calls, self.requests)
