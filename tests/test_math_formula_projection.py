"""End-to-end checks on published formula views and mathematical objects."""

from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "错题知识网络/scripts"))
import math_formula_cards as cards
import math_geometry_projection as geometry
import math_recap as recap
import math_semantic_candidates as semantic


class FormulaProjectionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for source in (cards.RENDERER, "错题知识网络/scripts/math_formula_cards.py",
                       "错题知识网络/schema/formula_card_v1.json"):
            path = self.root / source
            path.parent.mkdir(exist_ok=True, parents=True)
            shutil.copyfile(ROOT / source, path)
        self.source = self.root / "reviewed-page.txt"
        self.source.write_text("reviewed condition and statement")
        self.registry = self.root / recap.BASE / "topics" / "branches.json"
        self.registry.parent.mkdir(parents=True)
        record = {"entry_id": "MRC-test-branch", "section": "secondary_conclusions", "name": "实数绝对值",
                  "conditions": ["x 是实数。"], "symbol_roles": ["x：实数"],
                  "allowed_views": ["direct", "after_attempt"],
                  "content": "当 x 非负时：\n\n$$\n|x|=x\n$$\n\n否则：\n\n$$\n|x|=-x\n$$",
                  "derivation": {"steps": ["direct expansion source detail"]},
                  "source_refs": [{"path": self.source.name, "sha256": cards.sha(self.source.read_bytes())}],
                  "review": {"status": "verified", "basis": "fixture", "reviewed_at": "2026-01-01"}}
        specific = {**record, "entry_id": "MRC-test-Q1", "name": "本题答案",
                    "content": "本题答案：\n\n$$\n8291736\n$$", "allowed_views": ["direct"]}
        self.registry.write_bytes(recap.canonical(
            {"schema": recap.TOPIC_SCHEMA, "topic_id": "MRC-test", "concept_keys": ["实数绝对值"],
             "title": "符号分支", "subject": "高等数学", "chapter": "函数", "entries": [record, specific]}))
        recap.build(self.root)

    def test_formula_views_keep_conditions_branches_and_source_gate(self):
        staged = cards._build(self.root)
        activated = cards._publish(self.root, staged["version"])
        self.assertEqual((1, 1), (activated["ready"], activated["needs_source_review"]))
        self.assertEqual({"status": "protected"}, cards.lookup(self.root, "MRC-test-branch", full=True))
        direct = cards.lookup(self.root, "MRC-test-branch", view="direct", full=True)
        page = (self.root / direct["card_path"]).read_text()
        self.assertLess(page.index("x 是实数"), page.index("<math"))
        self.assertLess(page.index("否则"), page.index("<mo>−</mo>"))
        self.assertEqual(2, page.count("<math"))
        self.assertNotIn("8291736", page)
        partial = cards.lookup(self.root, "MRC-test-branch", view="after_attempt", full=True)
        self.assertNotIn("card_path", partial)
        self.assertNotIn("source_refs", partial["card"])
        self.assertNotIn("direct expansion", json.dumps(partial))
        self.assertNotEqual("ready", cards.lookup(self.root, "MRC-test-Q1", view="direct")["status"])
        manifest = self.root / recap.MANIFEST
        retired = manifest.with_suffix(".withheld")
        manifest.rename(retired)
        self.assertEqual("unresolved", cards.lookup(self.root, "MRC-test-branch", view="direct")["freshness"])
        retired.rename(manifest)
        self.source.write_text("new unreviewed source")
        self.assertEqual("stale", cards.lookup(self.root, "MRC-test-branch", view="direct")["freshness"])

    def test_stage_rejects_source_changed_before_activation(self):
        staged = cards._build(self.root)
        self.source.unlink()
        with self.assertRaisesRegex(cards.CardError, "dependencies_drift:unresolved"):
            cards._publish(self.root, staged["version"])
        self.assertIsNone(cards.pointer(self.root))


class ExactGeometryTest(unittest.TestCase):
    def setUp(self):
        self.data = {"schema": "math-diagram-v1", "assumption_refs": [0],
                     "objects": {
                         "A": {"type": "point", "xyz": [1,0,0]},
                         "B": {"type": "point", "xyz": [1,2,3]},
                         "C": {"type": "point", "xyz": [-1,0,0]},
                         "v": {"type": "vector", "from": "A", "to": "B"}},
                     "directed_edges": [{"object_id": "v", "at": "C", "scale": "1/2"}]}

    def test_translated_arrow_is_derived_and_not_reversed(self):
        view = geometry.render(self.data, ["v非零"])
        self.assertEqual(["-1","0","0"], view["directed_edges"][0]["world_start"])
        self.assertEqual(["-1","1","3/2"], view["directed_edges"][0]["world_end"])
        self.assertTrue(any(r"\overrightarrow{AB}=B-A=" in expr for expr in view["formulas"]))
        self.assertEqual("derived", view["conclusion_checks"][0]["status"])
        self.data["directed_edges"][0]["scale"] = "-1"
        with self.assertRaisesRegex(geometry.DiagramError, "nonpositive_arrow_scale"):
            geometry.render(self.data, ["v非零"])

    def test_proof_with_untranslated_degeneracy_is_unknown(self):
        self.assertEqual("unknown", geometry.symbolic_status([True, ["AreEqual(A,B)"]]))
        self.assertEqual("symbolic_excluding_degeneracies",
                         geometry.symbolic_status([True, ["AreEqual(A,B)"]], {"AreEqual(A,B)": "A≠B"}))


class ScopedCandidatesTest(unittest.TestCase):
    def test_form_similarity_does_not_authorize_equivalence(self):
        p = {"duplicate": .95, "assignment": .9, "conflict": .1, "condition_difference": .9}
        self.assertEqual("different_conditions", semantic.advisory(p, True)["relation"])
        self.assertEqual("insufficient_evidence", semantic.advisory({k:v for k,v in p.items()
                                                                     if k != "condition_difference"}, True)["relation"])
        turns = [{"sequence": 1, "role": "user", "source_text_sha256": "1"*64},
                 {"sequence": 3, "role": "assistant", "source_text_sha256": "3"*64}]
        group = semantic.same_capture_group({"manifest_sha256": "a"*64}, turns)
        self.assertEqual([1,3], [t["sequence"] for t in group["selected_turns"]])
        with self.assertRaises(ValueError):
            semantic.same_capture_group({"manifest_sha256": "a"*64}, list(reversed(turns)))


if __name__ == "__main__":
    unittest.main()
