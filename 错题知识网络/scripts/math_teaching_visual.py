#!/usr/bin/env python3
"""Compile exactly one authorized math explanation into a local Visualize fragment."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

from math_runtime_paths import codex_home


ASSETS = Path(__file__).resolve().parent / "math_teaching_visual"
REPO = Path(__file__).resolve().parents[2]
STUDY_ASSETS = Path("错题知识网络/assets/math-study-recipes")
RECEIPT_SCHEMA = "math_study_recipe_assets_v1"
STUDY_VIEWS = {"after_attempt", "direct"}
STUDY_MATCH = {
    "saddle-sections-tangent": re.compile(r"鞍面|鞍点|截线.*切平面|切平面.*截线"),
    "eigen-directions": re.compile(r"零特征值|特征方向|特征向量.*(?:共线|反向|零向量)"),
    "same-distribution-vs-independence": re.compile(r"(?:同分布|边缘分布).*独立|独立.*(?:同分布|边缘分布)"),
    "riemann-signed-area": re.compile(r"有符号黎曼和|(?:黎曼和|中点和|中点法).*(?:正负|有符号|几何面积)|定积分.*几何面积.*(?:抵消|正负|逆限)"),
    "gradient-direction": re.compile(r"等高线.*(?:方向导数|沿梯度|最陡)|方向导数.*(?:等高线|顺梯度|垂直梯度)"),
}
RECIPE_PARAMETERS = {
    "saddle-sections-tangent": {"coefficients": [1, -1], "point": [0, 0, 0], "half_span": 1.35},
    "eigen-directions": {"diagonals": [[2, -1], [2, 0]]},
    "same-distribution-vs-independence": {"faces": [1, 2, 3, 4, 5, 6]},
    "riemann-signed-area": {"coefficients": [-1, 1], "bounds": [-2, 2], "interval": [-2, 2], "n": 8},
    "gradient-direction": {"coefficients": [3, -1, -2], "point": [0.5, 0.5], "angle": 0},
}
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}")
AXIS = re.compile(r"[A-Za-z][A-Za-z0-9₀-₉′']{0,7}")
INK = {"a", "b", "result", "neutral"}
INPUT_LIMIT = 160_000
VIEWS = {"protected", "after_attempt", "direct"}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def fields(value, required, optional=()):
    require(isinstance(value, dict) and set(required) <= value.keys() <= set(required) | set(optional),
            "unexpected math visual fields")


def text(value, size=90):
    require(isinstance(value, str) and 0 < len(value.strip()) <= len(value) <= size
            and not re.search(r"[$<>\\\x00-\x1f]", value), "plain visual label required; keep formulas in chat")


def number(value):
    require(type(value) in (int, float) and abs(value) <= 10**7 and math.isfinite(value),
            "finite coordinate required")
    return value


def axes(value):
    require(isinstance(value, list) and len(value) == 2
            and all(isinstance(x, str) and AXIS.fullmatch(x) for x in value)
            and len(set(value)) == 2, "use the two current axis symbols")


def bounds(value):
    require(isinstance(value, list) and len(value) == 4, "bounds must be [xmin,xmax,ymin,ymax]")
    xmin, xmax, ymin, ymax = map(number, value)
    require(xmin < xmax and ymin < ymax, "nonempty plotting limits required")
    return ((xmin, xmax), (ymin, ymax))


def optional_flag(scene, key):
    if key in scene:
        require(type(scene[key]) is bool, "expected a boolean")


def points(value, limits, low, high):
    require(isinstance(value, list) and low <= len(value) <= high, "invalid plot points")
    for point in value:
        require(isinstance(point, list) and len(point) == 2, "expected [x,y]")
        for coord, (a, b) in zip(point, limits):
            require(a <= number(coord) <= b, "coordinates outside the plotting window")


def name(value):
    require(isinstance(value, str) and TOKEN.fullmatch(value), "invalid math object ID")


def ordered_rows(items, low, high, validator):
    require(isinstance(items, list) and low <= len(items) <= high, "invalid visual object count")
    by_id = {}
    for row in items:
        validator(row)
        name(row["id"])
        require(row["id"] not in by_id, "duplicate math object ID")
        text(row["label"])
        by_id[row["id"]] = row
    return by_id


def interpolate(curve, t, axis):
    transverse = 1-axis
    for a, b in zip(curve, curve[1:]):
        if a[axis] <= t <= b[axis]:
            if t == a[axis]:
                return a[transverse]
            if t == b[axis]:
                return b[transverse]
            return a[transverse] + (t-a[axis])/(b[axis]-a[axis])*(b[transverse]-a[transverse])
    raise ValueError("band outside its boundary samples")


def validate_region(scene):
    fields(scene, ("kind", "title", "axes", "bounds", "sweep", "boundaries", "bands"),
           ("stops", "windowed", "approximate", "open_endpoints"))
    limits = bounds(scene["bounds"])
    sweep = scene["sweep"]
    fields(sweep, ("axis", "initial", "step"))
    require(sweep["axis"] in ("x", "y"), "use x or y as the fixed plotting axis")
    axis = 0 if sweep["axis"] == "x" else 1
    minimum, maximum = limits[axis]
    span = maximum-minimum
    require(minimum <= number(sweep["initial"]) <= maximum and
            span/100_000 <= number(sweep["step"]) <= span, "invalid sweep range or keyboard step")
    for key in ("windowed", "approximate", "open_endpoints"):
        optional_flag(scene, key)

    def boundary(row):
        fields(row, ("id", "label", "points"))
        curve = row["points"]
        points(curve, limits, 2, 160)
        require(all(a[axis] < b[axis] for a, b in zip(curve, curve[1:])),
                "each boundary must be single-valued and monotone in its scan coordinate")

    curves = {key: row["points"] for key, row in
              ordered_rows(scene["boundaries"], 1, 8, boundary).items()}
    bands = scene["bands"]
    require(isinstance(bands, list) and 1 <= len(bands) <= 12, "expected 1–12 scan bands")
    previous = None
    for band in bands:
        fields(band, ("from", "to", "lower", "upper"))
        a, b = number(band["from"]), number(band["to"])
        require(minimum <= a < b <= maximum and (previous is None or previous["to"] <= a),
                "bands must be sorted and cannot overlap")
        for side in ("lower", "upper"):
            name(band[side])
            require(band[side] in curves, "band needs an existing boundary")
        low, high = (curves[band[side]] for side in ("lower", "upper"))
        knots = {a, b} | {p[axis] for curve in (low, high) for p in curve if a < p[axis] < b}
        require(all(interpolate(low, t, axis) <= interpolate(high, t, axis) for t in knots),
                "lower boundary is above upper boundary between samples")
        if previous and previous["to"] == a:
            require(all(math.isclose(interpolate(curves[previous[side]], a, axis),
                                     interpolate(curves[band[side]], a, axis),
                                     rel_tol=1e-10, abs_tol=1e-10)
                        for side in ("lower", "upper")), "slice is ambiguous at a shared band seam")
        previous = band
    stops = scene.get("stops", [])
    require(isinstance(stops, list) and len(stops) <= 8, "too many key stops")
    last = None
    for stop in stops:
        fields(stop, ("at", "label"))
        at = number(stop["at"])
        require(minimum <= at <= maximum and (last is None or last < at), "key stops must be distinct and sorted")
        text(stop["label"], 50)
        last = at


def validate_compare(scene):
    fields(scene, ("kind", "title", "axes", "bounds", "objects", "cases"))
    limits = bounds(scene["bounds"])
    axis_spans = [hi - lo for lo, hi in limits]
    require(math.isclose(*axis_spans, rel_tol=1e-9), "comparison uses equal axis spans to preserve geometry")

    def object_spec(row):
        fields(row, ("id", "label", "ink"))
        require(isinstance(row["ink"], str) and row["ink"] in INK, "invalid display style")

    objects = ordered_rows(scene["objects"], 1, 8, object_spec)
    cases = scene["cases"]
    require(isinstance(cases, list) and 2 <= len(cases) <= 5, "provide two to five actual condition cases")
    labels = set()
    shapes = []
    for case in cases:
        fields(case, ("label", "items"))
        text(case["label"], 68)
        require(case["label"] not in labels, "condition labels must differ")
        labels.add(case["label"])
        items = case["items"]
        require(isinstance(items, dict) and items.keys() == objects.keys(), "compare the same objects in each condition")
        for item in items.values():
            fields(item, ("kind", "points", "note"))
            require(item["kind"] in ("segment", "vector", "point"), "use a segment, vector or point")
            count = 1 if item["kind"] == "point" else 2
            points(item["points"], limits, count, count)
            require(count == 1 or item["points"][0] != item["points"][1], "zero-length geometry must be a point")
            text(item["note"], 130)
        shapes.append(tuple((item["kind"], tuple(map(tuple, item["points"]))) for item in
                            (items[key] for key in objects)))
    require(len(set(shapes)) == len(cases), "each comparison must show an actual geometric change")


def compile_scene(scene, view, allow_geometry=False):
    """Project no hidden layer. Restricted turns accept only the given-object schema."""
    require(view in VIEWS and type(allow_geometry) is bool, "invalid math disclosure scope")
    require(isinstance(scene, dict) and isinstance(scene.get("kind"), str), "expected a math scene")
    kind = scene["kind"]
    if kind == "text":
        fields(scene, ("kind",))
        return None
    if kind == "given":
        fields(scene, ("kind", "axes"))
        axes(scene["axes"])
        return {"kind": "given", "title": "题设坐标", "axes": scene["axes"]}
    require(view != "protected" and allow_geometry, "derived geometry is not permitted in this turn")
    if kind == "study_recipe":
        fields(scene, ("kind", "recipe_id"))
        return compile_study_recipe(scene["recipe_id"], view)
    require(kind in ("region", "compare"), "unsupported math visual kind")
    (validate_region if kind == "region" else validate_compare)(scene)
    text(scene["title"], 100)
    axes(scene["axes"])
    return scene


def load_renderer():
    path = codex_home() / "skills" / "_shared" / "visual-explanations" / "render.py"
    spec = importlib.util.spec_from_file_location("_math_shared_visual_renderer", path)
    require(spec is not None and spec.loader is not None and path.is_file(), "shared visual renderer unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def compile_study_recipe(identity, view):
    require(view in STUDY_VIEWS, "study recipe requires an authorized derived view")
    require(isinstance(identity, str) and identity in RECIPE_PARAMETERS, "unknown study recipe")
    data = json.loads((ASSETS / "recipes.json").read_bytes())
    require(data.get("schema") == "math_study_recipes_v1" and data.get("authority") == "synthetic_example",
            "invalid study recipe source")
    entry = data["recipes"][identity]
    fields(entry, ("title", "scene_version", "parameters", "math_status"))
    require(entry["parameters"] == RECIPE_PARAMETERS[identity], "fixed sample parameters changed")
    require(type(entry["scene_version"]) is int and entry["scene_version"] > 0, "invalid scene version")
    text(entry["title"])
    name(entry["math_status"])
    return {**entry, "kind": "study_recipe", "recipe_id": identity, "authority": "synthetic_example",
            "view": view}


def recipe_renderer():
    return codex_home() / "skills/_shared/visual-explanations"


def recipe_dependencies():
    sources = {n: ASSETS / n for n in ("recipes.json", "recipes.js", "recipes.css")}
    sources["math_teaching_visual.py"] = Path(__file__).resolve()
    sources.update({f"shared/{n}": recipe_renderer() / n for n in ("render.py", "fragment.html")})
    return {key: _sha(p.read_bytes()) for key, p in sources.items()}


def _recipe_renderer(shared):
    return shared.LocalRenderer(ASSETS / "recipes.js", ASSETS / "recipes.css",
                                "CodexMathStudyRecipes", frozenset())


def _write_recipe_asset(path, contents):
    require(not path.is_symlink(), "study recipe artifact cannot be a symlink")
    if path.exists() and path.read_bytes() == contents:
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(contents)
            handle.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def build_study_recipes(repo=REPO):
    """Install the fixed offline assets at the existing math asset root."""
    root = Path(repo).resolve()
    directory = root / STUDY_ASSETS
    require(directory.resolve() == directory, "study recipe asset root is not canonical")
    directory.mkdir(parents=True, exist_ok=True)
    shared = load_renderer()
    local = _recipe_renderer(shared)
    dependencies = recipe_dependencies()
    rows = {}
    for identity in STUDY_MATCH:
        try:
            scene = compile_study_recipe(identity, "direct")
            fragment = shared.render_fragment(scene, "native", "synthetic/" + identity, local=local)
            page = ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
                    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                    "<style>body{margin:1rem auto;padding:0 .8rem;max-width:50rem;"
                    "background:Canvas;color:CanvasText;font:16px/1.55 system-ui,sans-serif}</style>"
                    "<title>" + scene["title"] + "</title><body>" + fragment + "</body></html>").encode("utf-8")
            relative = STUDY_ASSETS / (identity + ".html")
            _write_recipe_asset(root / relative, page)
            rows[identity] = {k: scene[k] for k in ("title", "scene_version", "parameters", "math_status")}
            rows[identity].update(status="ready", path=relative.as_posix(), sha256=_sha(page), bytes=len(page),
                                  views=sorted(STUDY_VIEWS))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            rows[identity] = {"status": "unavailable", "reason": type(exc).__name__}
    require(dependencies == recipe_dependencies(), "study renderer changed during generation")
    manifest = {"schema": RECEIPT_SCHEMA, "authority": "synthetic_example",
                "dependencies": dependencies, "scenes": rows,
                "capture_association": "not_established", "learning_event_write_count": 0}
    _write_recipe_asset(directory / "manifest.json",
                        (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    return manifest


def checked_study_recipe(repo, identity, view):
    """Read one verified stable example; fall back to teaching text on drift."""
    if view not in STUDY_VIEWS or not isinstance(identity, str) or identity not in STUDY_MATCH:
        return None
    root = Path(repo).resolve()
    try:
        manifest_path = root / STUDY_ASSETS / "manifest.json"
        if manifest_path.resolve() != manifest_path:
            return None
        with manifest_path.open("rb") as handle:
            manifest = json.loads(handle.read(100_000))
        if (manifest.get("schema") != RECEIPT_SCHEMA or manifest.get("authority") != "synthetic_example"
                or manifest.get("capture_association") != "not_established"
                or manifest.get("learning_event_write_count") != 0):
            return None
        row = manifest["scenes"][identity]
        expected = STUDY_ASSETS / (identity + ".html")
        path = root / expected
        if (row["status"] != "ready" or view not in row["views"] or row["path"] != expected.as_posix()
                or path.resolve() != path or manifest["dependencies"] != recipe_dependencies()):
            return None
        scene = compile_study_recipe(identity, view)
        for key in ("title", "scene_version", "parameters", "math_status"):
            if scene[key] != row[key]:
                return None
        with path.open("rb") as handle:
            raw = handle.read(1_000_001)
        if len(raw) >= 1_000_000 or len(raw) != row["bytes"] or _sha(raw) != row["sha256"]:
            return None
        return row, raw
    except (OSError, TypeError, ValueError, KeyError):
        return None


def suggest_study_recipe(repo, operation, view):
    if view not in STUDY_VIEWS or not isinstance(operation, str):
        return None
    hits = [identity for identity, pattern in STUDY_MATCH.items() if pattern.search(operation)]
    if len(hits) != 1:
        return None
    verified = checked_study_recipe(repo, hits[0], view)
    if verified:
        row, _ = verified
        return {"id": hits[0], "v": row["scene_version"], "sha256": row["sha256"]}
    return None


def render(scene, *, question, focus, view="protected", allow_geometry=False,
           engine="auto", output=None, inline_root=None):
    name(question)
    name(focus)
    approved = compile_scene(scene, view, allow_geometry)
    if approved is None:
        return {"status": "text_only", "learning_write_count": 0}
    require(output is not None and inline_root is not None, "inline location is required for a visual")
    shared = load_renderer()
    recipe = approved["kind"] == "study_recipe"
    if recipe:
        require(checked_study_recipe(REPO, approved["recipe_id"], view) is not None,
                "study recipe dependencies or asset changed; return to text")
    local = (_recipe_renderer(shared) if recipe else
             shared.LocalRenderer(ASSETS / "math.bundle.js", ASSETS / "math.css", "CodexMathVisual",
                                  frozenset({"region", "compare"})))
    scope = "/".join((question, focus, view, "geometry" if allow_geometry else "given"))
    result = shared.write_visual(approved, "native" if recipe or approved["kind"] == "given" else engine,
                                 output, inline_root, local=local, scope=scope)
    if recipe:
        result["study_recipe"] = {
            "id": approved["recipe_id"], "version": approved["scene_version"],
            "parameters": approved["parameters"], "view": view, "math_status": approved["math_status"],
            "authority": "synthetic_example", "dependencies": recipe_dependencies(),
            "asset_sha256": _sha(Path(output).read_bytes()), "capture_association": "not_established",
            "learning_event_write_count": 0,
        }
    return {**result, "status": "ready", "kind": approved["kind"], "learning_write_count": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="-")
    parser.add_argument("--question", help="Current exact or transient question identity")
    parser.add_argument("--focus", help="Stable token for the current authorized subquestion/step")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--recipe", choices=tuple(STUDY_MATCH), help="Use a fixed synthetic study example")
    mode.add_argument("--build-recipes", action="store_true", help="Build the stable, math-owned offline examples")
    parser.add_argument("--view", choices=sorted(VIEWS), default="protected")
    parser.add_argument("--allow-geometry", action="store_true",
                        help="Tutor has verified that this turn authorizes all supplied derived geometry")
    parser.add_argument("--engine", choices=("auto", "native", "a2ui"), default="auto")
    parser.add_argument("--inline-root")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        if args.build_recipes:
            print(json.dumps(build_study_recipes(), ensure_ascii=False))
            return 0
        require(args.question is not None and args.focus is not None, "question and focus are required")
        if args.recipe:
            scene = {"kind": "study_recipe", "recipe_id": args.recipe}
        else:
            if args.input == "-":
                raw = sys.stdin.buffer.read(INPUT_LIMIT + 1)
            else:
                with Path(args.input).open("rb") as handle:
                    raw = handle.read(INPUT_LIMIT + 1)
            require(len(raw) <= INPUT_LIMIT, "math visual input too large")
            scene = json.loads(raw)
        result = render(scene, question=args.question, focus=args.focus, view=args.view,
                        allow_geometry=args.allow_geometry, engine=args.engine,
                        output=args.output, inline_root=args.inline_root)
    except (ValueError, OSError, KeyError, TypeError, ImportError) as exc:
        reason = str(exc) if not isinstance(exc, (OSError, KeyError, TypeError)) else "invalid math visual or local resources unavailable"
        print(json.dumps({"status": "unavailable", "reason": reason}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
