import json
from pathlib import Path
import tempfile
import unittest

import math_teaching_visual as visual
from math_tutoring_inputs import teaching_inputs


class MathStudyRecipeTests(unittest.TestCase):
    def test_current_recipe_needs_permission_and_uses_only_fixed_parameters(self):
        selector = {"kind": "study_recipe", "recipe_id": "eigen-directions"}
        for view, allowed in (("protected", True), ("after_attempt", False)):
            with self.assertRaises(ValueError):
                visual.compile_scene(selector, view, allow_geometry=allowed)
        self.assertEqual(visual.compile_scene(selector, "after_attempt", True)["parameters"],
                         {"diagonals": [[2, -1], [2, 0]]})
        with self.assertRaises(ValueError):
            visual.compile_scene({**selector, "parameters": {"private": True}}, "direct", True)

    def test_v2_recipes_use_same_protected_gate_and_dependency_fallback(self):
        recipes = ('riemann-signed-area', 'gradient-direction')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = visual.build_study_recipes(root)
            for identity in recipes:
                scene = {'kind': 'study_recipe', 'recipe_id': identity}
                self.assertIsNotNone(visual.checked_study_recipe(root, identity, 'after_attempt'))
                with self.assertRaisesRegex(ValueError, 'derived geometry'):
                    visual.compile_scene(scene, 'protected', True)
                with self.assertRaisesRegex(ValueError, 'derived geometry'):
                    visual.compile_scene(scene, 'after_attempt', False)
            self.assertIsNone(visual.suggest_study_recipe(root, '只说明定积分', 'after_attempt'))
            self.assertEqual('riemann-signed-area', visual.suggest_study_recipe(root, '解释有符号黎曼和', 'direct')['id'])
            self.assertEqual('gradient-direction', visual.suggest_study_recipe(root, '等高线上的方向导数', 'direct')['id'])
            self.assertIsNone(visual.suggest_study_recipe(root, '等高线上的方向导数与有符号黎曼和', 'direct'))
            self.assertEqual(0, manifest['learning_event_write_count'])
            self.assertEqual('not_established', manifest['capture_association'])
            manifest['dependencies']['recipes.js'] = '0' * 64
            (root/visual.STUDY_ASSETS/'manifest.json').write_text(json.dumps(manifest))
            self.assertTrue(all(visual.checked_study_recipe(root, identity, 'direct') is None for identity in recipes))

    def test_bounded_teaching_uses_checked_recipe_until_its_asset_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = visual.build_study_recipes(root)
            for identity, scene in manifest["scenes"].items():
                checked = visual.checked_study_recipe(root, identity, "direct")
                self.assertIsNotNone(checked)
                self.assertEqual(scene["sha256"], checked[0]["sha256"])
            data = {"view": "after_attempt", "status": "source_based", "version": "v", "records": []}
            operation = "核对零特征值下的特征向量"
            live = teaching_inputs(data, 4500, repo=root, operation=operation)
            self.assertEqual(live["teaching_inputs"]["study_recipe"]["id"], "eigen-directions")
            protected = teaching_inputs({**data, "view": "protected"}, 4500, repo=root, operation=operation)
            self.assertNotIn("study_recipe", protected["teaching_inputs"])
            (root / manifest["scenes"]["eigen-directions"]["path"]).unlink()
            fallback = teaching_inputs(data, 4500, repo=root, operation=operation)
            self.assertNotIn("study_recipe", fallback["teaching_inputs"])
            self.assertIn("visual_entry", fallback["teaching_inputs"])
            self.assertNotEqual(live["version"], fallback["version"])
