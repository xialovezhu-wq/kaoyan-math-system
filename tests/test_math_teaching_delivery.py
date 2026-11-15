import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
from time import perf_counter_ns
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "错题知识网络/scripts"))
from math_teaching_delivery import emit_audit, has_delivery_gap


class DeliveryTests(unittest.TestCase):
    def emit(self, document, **kwargs):
        supplied = {"view": document["view"], "max_bytes": 12000, **kwargs}
        with contextlib.redirect_stdout(io.StringIO()) as body, contextlib.redirect_stderr(io.StringIO()) as receipt:
            emit_audit(document, args=SimpleNamespace(**supplied), began_ns=perf_counter_ns(), exit_status=0)
        output = body.getvalue().removesuffix("\n").encode("utf-8")
        audit = json.loads(receipt.getvalue())
        self.assertEqual(document, json.loads(output))
        self.assertEqual(len(output), audit["stdout_utf8_bytes"])
        self.assertEqual(hashlib.sha256(output).hexdigest(), audit["stdout_sha256"])
        return audit

    def test_receipt_points_only_to_delivered_evidence_and_does_not_copy_text(self):
        document = {"status": "available", "view": "after_attempt", "source_version": "fixture",
                    "records": [{"status": "semantic_current", "short_summary": "合成内容",
                                 "step_evidence": [{"scope": "完整适用条件。"}]},
                                {"status": "semantic_stale", "short_summary": "过期判断"}],
                    "memory_context": {"pending_evidence": {"status": "budget_too_small", "records": []}}}
        audit = self.emit(document, query="不可复制的查询")
        pts = audit["delivered_json_pointers"]
        self.assertEqual(["/records/0/short_summary"], pts["short_summary"])
        self.assertEqual(["/records/0/step_evidence/0"], pts["step_evidence"])
        self.assertNotIn("records", pts)
        self.assertEqual("full_delivery_not_established", audit["body_state"])
        self.assertNotIn("合成内容", str(audit))
        self.assertNotIn("不可复制的查询", str(audit))

    def test_protected_and_cache_hit_have_no_evidence_pointers(self):
        doc = {"status": "available", "view": "protected",
               "records": [{"concept_name": "题面对象"}]}
        audit = self.emit(doc, operation="当前小问")
        self.assertEqual({}, audit["delivered_json_pointers"])
        other = self.emit(doc, operation="不同小问")
        self.assertNotEqual(audit["scope_sha256"], other["scope_sha256"])
        hit = self.emit({"status": "unchanged", "view": "after_attempt", "records": []})
        self.assertEqual("cached_body_not_returned", hit["body_state"])
        self.assertEqual({}, hit["delivered_json_pointers"])

    def test_public_status_keeps_budget_gaps_separate_from_view_withholding(self):
        doc = {"status": "available", "view": "after_attempt",
               "records": [{"status": "semantic_current", "personal_fields_withheld": ["step_evidence.source_refs"]}]}
        self.assertFalse(has_delivery_gap(doc))
        self.assertTrue(has_delivery_gap({**doc, "truncated": True}))
        receipt = self.emit(doc, max_bytes=10)
        self.assertFalse(receipt["within_budget"])


if __name__ == "__main__":
    unittest.main()
