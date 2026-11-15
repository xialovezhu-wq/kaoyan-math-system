"""Integration against a local synthetic index, with no user evidence."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "错题知识网络/scripts"))
import math_concept_index as native
import math_teaching_context as cli


class BoundedTeachingCLI(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        db = self.root / native.INDEX
        db.parent.mkdir(parents=True)
        with contextlib.closing(sqlite3.connect(db)) as conn, conn:
            conn.executescript("""
                CREATE TABLE meta (key TEXT, value TEXT);
                CREATE TABLE lookup (name TEXT, key TEXT);
                CREATE TABLE concepts (key TEXT, label TEXT, normalized TEXT);
                CREATE TABLE records (id TEXT, payload TEXT);
                CREATE TABLE teaching_profiles (key TEXT, view TEXT, payload TEXT);
            """)
            label, key = "根式", native.concept_key("根式")
            conn.execute("INSERT INTO meta VALUES ('version', ?)", (json.dumps("synthetic-generation"),))
            conn.execute("INSERT INTO concepts VALUES (?, ?, ?)", (key, label, native.normalize(label)))
            conn.execute("INSERT INTO lookup VALUES (?, ?)", (native.normalize(label), key))
            conn.execute("INSERT INTO records VALUES (?, ?)", ("GS-001", json.dumps({
                "labels": [label], "source_refs": [{"path": "错题知识网络/错题卡/GS-001_FIXTURE-ANSWER.md"}],
            })))
            for view in ("protected", "after_attempt"):
                row = {"concept_key": key, "concept_name": label, "status": "semantic_current"}
                if view == "after_attempt":
                    row["short_summary"] = "这个合成摘要超出小预算。" * 120
                conn.execute("INSERT INTO teaching_profiles VALUES (?, ?, ?)", (key, view, json.dumps(row)))

    def read(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(0, cli.main(["--repo", str(self.root), "resolve", "--formal-id", "GS-001",
                                          "--audit-context", *args]))
        return json.loads(out.getvalue()), json.loads(err.getvalue())

    def test_incomplete_same_version_keeps_the_failure(self):
        a, _ = self.read("--view", "after_attempt", "--max-bytes", "850")
        self.assertEqual("budget_too_small", a["status"])
        b, receipt = self.read("--view", "after_attempt", "--max-bytes", "850", "--known-version", a["version"])
        self.assertEqual(a, b)
        self.assertEqual("full_delivery_not_established", receipt["body_state"])

    def test_protected_payload_and_audit_do_not_expose_answer_bearing_path(self):
        doc, receipt = self.read("--view", "protected")
        self.assertEqual("available", doc["status"])
        self.assertNotIn("card_path", doc["identity"])
        self.assertNotIn("FIXTURE-ANSWER", str(doc))
        self.assertEqual({}, receipt["delivered_json_pointers"])


if __name__ == "__main__":
    unittest.main()
