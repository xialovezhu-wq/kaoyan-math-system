"""Checked orthographic sketches of exact 3D objects; no inferred geometry."""
from __future__ import annotations

from fractions import Fraction
from html import escape
from itertools import combinations, product
from math import hypot, isfinite, sqrt
import re

VERSION = "math-diagram-v1"
ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,23}")
RATIONAL = re.compile(r"-?\d{1,12}(?:/[1-9]\d{0,10})?")


class DiagramError(ValueError):
    """A figure that cannot be supported or drawn without misleading the reader."""


def require(ok, reason):
    if not ok:
        raise DiagramError(reason)


def exact(value):
    require(type(value) in (str, int) and RATIONAL.fullmatch(str(value)), "exact_coordinate_required")
    return Fraction(value)


def xyz(values):
    require(isinstance(values, list) and len(values) == 3, "three_coordinates_required")
    return tuple(map(exact, values))


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def times(t, a):
    return tuple(t * x for x in a)


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def cross(a, b):
    return tuple(a[i-2]*b[i-1]-a[i-1]*b[i-2] for i in range(3))


def unit(a):
    length = sqrt(dot(a, a))
    return times(1/length, a)


def tex_num(x):
    return str(x.numerator) if x.denominator == 1 else (
        ("-" if x < 0 else "") + rf"\frac{{{abs(x.numerator)}}}{{{x.denominator}}}")


def tex(v):
    return r"\left(" + ",".join(map(tex_num, v)) + r"\right)"


def tex_id(name):
    return name.replace("_", "_{", 1) + "}" if "_" in name else name


def equation(normal, point, names):
    terms = []
    for c, x in zip(normal, names):
        if c:
            terms.append(("-" if c < 0 else "+") + (tex_num(abs(c)) if abs(c) != 1 else "") + x)
    return "".join(terms).lstrip("+") + "=" + tex_num(dot(normal, point))


def verify(data, assumptions):
    """Keep construction, derivation and configuration checks distinguishable.

    Input vectors are endpoint pairs, optionally translated by a positive scale.
    A plane uses one point and two independent vectors; its normal is computed.
    """
    require(data.get("schema") == VERSION, "invalid_diagram_schema")
    defs = data.get("objects")
    require(isinstance(defs, dict) and 2 <= len(defs) <= 20 and
            all(ID.fullmatch(k) and isinstance(v, dict) for k, v in defs.items()),
            "invalid_object_id")
    refs = data.get("assumption_refs")
    require(isinstance(refs, list) and len(set(refs)) == len(refs) and
            all(type(i) is int and 0 <= i < len(assumptions) for i in refs) and refs,
            "unbound_geometry_assumptions")

    positions, vectors, planes, formulas = {}, {}, {}, []
    names = data.get("coordinate_names", ["x", "y", "z"])
    require(isinstance(names, list) and len(names) == 3 and len(set(names)) == 3
            and all(re.fullmatch(r"[xyz]'?", name) for name in names), "invalid_coordinate_names")
    for key, obj in defs.items():
        if obj.get("type") == "point":
            positions[key] = xyz(obj["xyz"])
    for key, obj in defs.items():
        if obj.get("type") != "vector":
            continue
        a, b = obj["from"], obj["to"]
        require(a in positions and b in positions, "unknown_vector_endpoint")
        delta = sub(positions[b], positions[a])
        require(any(delta), "zero_direction")
        vectors[key] = delta
        formulas.append(rf"\overrightarrow{{{tex_id(a)}{tex_id(b)}}}={tex_id(b)}-{tex_id(a)}={tex(delta)}")
    for key, obj in defs.items():
        if obj.get("type") != "plane":
            continue
        point, a, b = obj["through"], *obj["basis"]
        require(point in positions and a in vectors and b in vectors, "unknown_plane_object")
        normal = cross(vectors[a], vectors[b])
        require(any(normal), "degenerate_plane_basis")
        planes[key] = (point, a, b, normal, exact(obj.get("extent", 1)))
        require(planes[key][-1] > 0, "nonpositive_plane_extent")
        formulas.extend([tex_id(key) + r":\quad " + equation(normal, positions[point], names),
                         tex_id("n_" + key) + "=" + tex(normal)])
    require(set(defs) == positions.keys() | vectors.keys() | planes.keys(), "unknown_geometry_object")
    edges = []
    for edge in data.get("directed_edges", []):
        key = edge["object_id"]
        a = edge.get("at")
        scale = exact(edge.get("scale", 1))
        require(scale > 0, "nonpositive_arrow_scale")
        if key in vectors:
            source = a or defs[key]["from"]
            require(source in positions, "unknown_translated_anchor")
            start = positions[source]
            delta = vectors[key]
            if source != defs[key]["from"] or scale != 1:
                formulas.append(rf"{tex_id(source)}={tex(start)},\qquad t={tex_num(scale)}>0")
                formulas.append(rf"{tex_id(source)}+t\overrightarrow{{{tex_id(defs[key]['from'])}{tex_id(defs[key]['to'])}}}"
                                + "=" + tex(add(start, times(scale, delta))))
        elif key in planes and edge.get("role") == "normal":
            point, _, _, delta, _ = planes[key]
            require(a is None or a == point, "normal_origin_must_be_plane_anchor")
            start = positions[point]
        else:
            raise DiagramError("arrow_not_bound_to_mathematical_object")
        edges.append((key, start, add(start, times(scale, delta))))
    require(edges and len({key for key, *_ in edges}) == len(edges), "missing_or_duplicate_arrow")
    checks = [{"status": "derived", "object_id": key, "relation": "nonzero_endpoint_difference"}
              for key in vectors]
    for key, (_, a, b, n, _) in planes.items():
        require(dot(vectors[a], n) == dot(vectors[b], n) == 0, "normal_check_failed")
        checks.append({"status": "derived", "object_id": key,
                       "relation": "nonzero_cross_product_is_normal"})
    for check in data.get("relations", []):
        u, plane = check["vector"], check["plane"]
        require(u in vectors and plane in planes, "unknown_relation_object")
        n = planes[plane][3]
        kind = check["kind"]
        require(kind in ("direction_parallel_to_plane", "direction_perpendicular_to_plane"),
                "unknown_relation_kind")
        ok = (dot(vectors[u], n) == 0 if kind == "direction_parallel_to_plane"
              else not any(cross(vectors[u], n)))
        require(ok, "asserted_relation_false_for_configuration")
        checks.append({"status": "configuration_verified", "object_ids": [u, plane], "relation": kind,
                       "dot": str(dot(vectors[u], n)),
                       "cross": list(map(str, cross(vectors[u], n)))})
    return positions, planes, edges, formulas, checks


def symbolic_status(value, exclusions=None):
    """Classify an already verified external result; never assert an engine ran."""
    if value == []:
        return "unknown"
    if value == [False] and type(value[0]) is bool:
        return "not_general"
    if value == [True] and type(value[0]) is bool:
        return "symbolic_under_construction"
    if (isinstance(value, list) and len(value) == 2 and value[0] is True
            and isinstance(value[1], list) and value[1] and isinstance(exclusions, dict)
            and all(isinstance(x, str) and x not in ("...", "…")
                    and isinstance(exclusions.get(x), str) and exclusions[x].strip() for x in value[1])):
        return "symbolic_excluding_degeneracies"
    return "unknown"


def render(data, assumptions):
    points, planes, edges, formulas, checks = verify(data, assumptions)
    formulas = [rf"{tex_id(key)}={tex(point)}" for key, point in points.items()] + formulas
    # Different axes are chosen deterministically. Never rotate a single arrow
    # independently of the objects it is meant to describe.
    cameras = data.get("projection", {}).get("view_directions",
              [[4, -7, 5], [3, 5, 8], [7, 2, 5], [-3, 6, 5], [-2, 3, -5]])
    require(isinstance(cameras, list) and 1 <= len(cameras) <= 16, "invalid_projection_candidates")
    polygons = {}
    hidden = set(data.get("hidden_points", []))
    for key, (p, u, v, normal, scale) in planes.items():
        delta = {}
        # Basis arrows need not be displayed. Recover their exact displacement
        # from the vector definitions rather than from a screen segment.
        for k in (u, v):
            obj = data["objects"][k]
            delta[k] = sub(points[obj["to"]], points[obj["from"]])
        # A finite patch denotes the underlying plane. Include any labeled,
        # exactly coplanar point, or the drawing falsely suggests it is off
        # the plane. Derive patch bounds in the plane's own basis.
        U, V = delta[u], delta[v]
        uu, uv, vv = dot(U,U), dot(U,V), dot(V,V)
        det = uu*vv-uv*uv
        umin, umax, vmin, vmax = -scale, scale, -scale, scale
        padding = Fraction(1, 6)
        for name, point in points.items():
            w = sub(point, points[p])
            if name in hidden or dot(normal, w) != 0:
                continue
            wu, wv = dot(w,U), dot(w,V)
            a, b = (wu*vv-wv*uv)/det, (wv*uu-wu*uv)/det
            umin, umax = min(umin,a-padding), max(umax,a+padding)
            vmin, vmax = min(vmin,b-padding), max(vmax,b+padding)
        polygons[key] = [add(points[p], add(times(a,U), times(b,V)))
                         for a,b in ((umin,vmin),(umax,vmin),(umax,vmax),(umin,vmax))]
    cloud = [*points.values(), *(v for pair in edges for v in pair[1:]),
             *(v for corners in polygons.values() for v in corners)]
    used = set()
    for camera in map(xyz, cameras):
        require(any(camera), "zero_camera_direction")
        right = cross((0, 0, 1), camera)
        right = unit(right if any(right) else (1, 0, 0))
        up = unit(cross(camera, right))
        xy = {p: (dot(p, right), dot(p, up)) for p in cloud}
        if not all(isfinite(n) for p in xy.values() for n in p):
            continue
        used.add(camera)
        if any(abs(dot(unit(camera), unit(n))) < .17 for _, _, _, n, _ in planes.values()):
            continue
        xs, ys = zip(*xy.values())
        spanx, spany = max(xs)-min(xs), max(ys)-min(ys)
        if max(spanx, spany) == 0:
            continue
        scale = min(576 / max(spanx, 1e-12), 280 / max(spany, 1e-12))

        def screen(p):
            x, y = xy[p]
            return (340+scale*(x-(max(xs)+min(xs))/2), 190-scale*(y-(max(ys)+min(ys))/2))

        drawn = [(key, screen(a), screen(b), sub(b, a)) for key, a, b in edges]
        if any(hypot(*sub(b,a)) < 32 for _, a, b, _ in drawn):
            continue
        accidental = False
        for (_, a, b, ab), (_, c, d, cd) in combinations(drawn, 2):
            x, y = sub(b, a), sub(d, c)
            angle_cos = abs(dot(x, y))/(hypot(*x)*hypot(*y))
            same_length = abs(hypot(*x)-hypot(*y))/max(hypot(*x),hypot(*y)) < .035
            if ((angle_cos > .984 and any(cross(ab, cd)))
                    or (angle_cos < .035 and dot(ab, cd) != 0)
                    or (same_length and dot(ab, ab) != dot(cd, cd))):
                accidental = True
        if accidental:
            continue
        # Place labels outside strokes and other labels. A view with projected
        # point collisions must be replaced rather than hiding a point label.
        points2 = {key:screen(value) for key, value in points.items()
                   if key not in hidden}
        if any(hypot(*sub(a,b)) < 14 for a,b in combinations(points2.values(), 2)):
            continue
        labels = []
        obstacles = [(p[0]-6,p[1]-6,p[0]+6,p[1]+6) for p in points2.values()]

        def label(name, anchor):
            w = max(18, 9 * len(name) + 8)
            for r, (dx, dy) in product((12, 23, 34), ((1,-1),(1,1),(-1,-1),(-1,1),(0,-1),(0,1))):
                x = anchor[0] + dx*r - (w if dx < 0 else w/2 if dx == 0 else 0)
                y = anchor[1] + dy*r - (18 if dy < 0 else 0)
                box = (x, y, x+w, y+18)
                if x < 12 or y < 14 or x+w > 668 or y+18 > 372:
                    continue
                if any(x < d and x+w > a and y < e and y+18 > b for a,b,d,e in obstacles):
                    continue
                if any(_segment_box(a,b,box) for _,a,b,_ in drawn):
                    continue
                obstacles.append(box)
                labels.append((name, x+3, y+14))
                return True
            return False

        if not all(label(name, p) for name, p in points2.items()):
            continue
        if not all(label("n_" + key if key in planes else key, times(.5, add(a,b)))
                   for key,a,b,_ in drawn):
            continue
        svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 380" role="img" aria-labelledby="diagram-title">',
               '<title id="diagram-title">精确三维对象的正交投影；箭头从起点指向终点</title>',
               '<defs><marker id="tip" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse">'
               '<path d="M0 0L8 4L0 8Z" fill="#174f87"/></marker></defs>',
               '<rect width="680" height="380" fill="#f5f8fc"/>']
        for corners in polygons.values():
            path = " ".join(f"{x:.3f},{y:.3f}" for x,y in map(screen,corners))
            svg.append(f'<polygon points="{path}" fill="#d4e9ef" stroke="#5f8997"/>')
        for key,a,b,_ in drawn:
            svg.append(f'<line data-object="{key}" x1="{a[0]:.6f}" y1="{a[1]:.6f}" x2="{b[0]:.6f}" y2="{b[1]:.6f}" '
                       'stroke="#174f87" stroke-width="2.5" marker-end="url(#tip)"/>')
        for key,(x,y) in points2.items():
            svg.append(f'<circle data-object="{key}" cx="{x:.6f}" cy="{y:.6f}" r="4" fill="#182937"/>')
        for name,x,y in labels:
            svg.append(f'<text x="{x:.3f}" y="{y:.3f}" fill="#172c40" font-size="15" '
                       f'font-family="system-ui,sans-serif">{escape(name)}</text>')
        svg.append('</svg>')
        first = edges[0][0]
        if first in planes:
            primary = tex_id("n_" + first) + "=" + tex(planes[first][3])
        else:
            a, b = (data["objects"][first][k] for k in ("from", "to"))
            primary = rf"\overrightarrow{{{tex_id(a)}{tex_id(b)}}}={tex_id(b)}-{tex_id(a)}={tex(sub(points[b],points[a]))}"
        return {"svg": "".join(svg), "formulas": formulas, "primary_formula": primary,
                "object_ids": list(data["objects"]),
                "assumption_refs": data["assumption_refs"], "renderer_version": VERSION,
                "construction_checks": {"status": "verified", "reason": "exact_objects_and_nondegeneracy"},
                "conclusion_checks": checks,
                "visual_checks": {"status": "verified", "views_checked": len(used), "annotation": "no_right_angle_or_equal_length_marks",
                                  "camera_world": list(map(str,camera)),
                                  "projection": "orthographic",
                                  "checks": ["arrow_endpoints", "noncollapsed_projection", "nonoverlapping_labels",
                                             "no_accidental_parallel_perpendicular_equal_length",
                                             "labeled_coplanar_points_in_drawn_patch"]},
                "directed_edges": [{"object_id": key, "world_start": list(map(str,a)), "world_end": list(map(str,b))}
                                   for key,a,b in edges]}
    raise DiagramError("no_nonmisleading_projection")


def _segment_box(a, b, box):
    lo, hi = 0., 1.
    for axis in range(2):
        x = a[axis]
        d = b[axis]-x
        lower, upper = box[axis]-3, box[axis+2]+3
        if abs(d) < 1e-10:
            if x < lower or x > upper:
                return False
        else:
            p,q = sorted(((lower-x)/d,(upper-x)/d))
            lo,hi = max(lo,p),min(hi,q)
            if lo > hi:
                return False
    return True
