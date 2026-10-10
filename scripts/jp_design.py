"""Source-backed, completed Japanese design/upgrade standards, split on station projections.

This step only cuts existing geometry. It never moves a track or its display offset.
Unfinished projects remain separate metadata and cannot recolour a completed section.
"""
import json
import unicodedata
from collections import defaultdict
from pathlib import Path

from shapely.ops import substring

from design_speeds import SectionPaths, grade, parts_of, point_name

CATALOG = json.loads((Path(__file__).resolve().parents[1] / "data/jp_design_standards.json").read_text())


def base_colour(name):
    spec = CATALOG["lines"].get(name)
    if not spec:
        return {"c": "hsr250", "e": 1}  # identity alone cannot establish a design number
    return {"c": grade(spec["design"]), "d": spec["design"],
            "ref": CATALOG["sources"][spec["source"]]["url"]}


def record(spec):
    source = CATALOG["sources"][spec["source"]]
    return {"from": spec["from"], "to": spec["to"], "design": spec["design"],
            "ref": source["url"], "title": source["title"],
            **({"basis": spec["basis"]} if spec.get("basis") else {})}


def apply_design(features, rows, stations):
    """Return the same paths cut at verified section boundaries, plus an audit receipt.

    Missing/ambiguous anchors never spread a higher standard to the whole named line.
    """
    points = defaultdict(list)
    for tags, lon, lat in stations:
        name = unicodedata.normalize("NFKC", tags.get("name", "")).strip()
        points[point_name(name)].append((lon, lat))
    by_name = defaultdict(list)
    for f in features:
        by_name[f["properties"].get("n")].append(f)
    replaced, audit = {}, []
    for name, spec in CATALOG["lines"].items():
        if name not in by_name:
            continue
        original = by_name[name]
        row = rows[name]
        sections = spec.get("sections", [spec])
        row["sections"] = [record(s) for s in sections]
        row["upgrades"] = [record(s) | {"status": s["status"]} for s in spec.get("upgrades", [])]
        row["upgrades"] += [{"from": s["from"], "to": s["to"], "design": s["upgrade"],
                             "ref": CATALOG["sources"][s["upgrade_source"]]["url"], "status": s["status"]}
                            for s in sections if s.get("upgrade")]
        if spec.get("sections"):
            parts, owners = [], []
            for f in original:
                for g in parts_of(f):
                    parts.append(g)
                    owners.append(f["properties"])
            boundaries = {s[k] for s in sections for k in ("from", "to")}
            paths = SectionPaths(parts, points, boundaries, near=.003, join=.00003, gap=.0004,
                                 beyond=.003, at_end=.0004, same_place=.01)
            spans = defaultdict(list)
            placed = []
            for s in sections:
                # The baseline already covers the rest. Explicitly place only bounded upgrades
                # and the northern construction range, so no uncertain Tokyo anchor is needed.
                if s["design"] == spec["design"] and not s.get("upgrade"):
                    continue
                route = paths.between(s["from"], s["to"])
                audit.append({"line": name, "from": s["from"], "to": s["to"],
                              "design": s["design"], "placed": bool(route)})
                if not route:
                    continue
                placed.append(s)
                for i, a, b in route:
                    spans[i].append((min(a, b), max(a, b), s))
            # Both tracks of a station loop get the same standard only when they leave
            # and rejoin edges already assigned to that standard.
            for i, extra in paths.other_tracks(spans).items():
                spans[i].extend(extra)
            out = []
            for i, g in enumerate(parts):
                cuts = sorted({0., g.length, *(x for a, b, _ in spans[i] for x in (a, b))})
                for a, b in zip(cuts, cuts[1:]):
                    if b - a < 1e-12:
                        continue
                    found = [s for x, y, s in spans[i] if x - 1e-10 <= (a + b) / 2 <= y + 1e-10]
                    s = found[0] if len({s["design"] for s in found}) == 1 else None
                    p = dict(owners[i])
                    if s:
                        p.update(c=grade(s["design"]), d=s["design"], de=s["from"] + "~" + s["to"],
                                 ref=CATALOG["sources"][s["source"]]["url"])
                        if s.get("upgrade"):
                            p.update(ud=s["upgrade"], ue=s["from"] + "~" + s["to"])
                    co = list(g.coords) if a == 0 and b == g.length else list(substring(g, a, b).coords)
                    out.append({"type": "Feature", "properties": p,
                                "geometry": {"type": "LineString", "coordinates": co}})
            replaced[name] = out
            # Metadata must reflect what was actually placed, not just the intended catalogue.
            row["sections"] = [record(s) for s in sections if s["design"] == spec["design"] or s in placed]
        actual = replaced.get(name, original)
        speeds = sorted({f["properties"]["d"] for f in actual if "d" in f["properties"]})
        row["design"] = speeds
        row["grades"] = sorted({grade(d) for d in speeds}, reverse=True)
        row["c"] = grade(max(speeds))
        if len(speeds) > 1:
            row.pop("d", None)
            row.pop("ref", None)
        else:
            row.update(base_colour(name))
    out, seen = [], set()
    for f in features:
        name = f["properties"].get("n")
        if name not in replaced:
            out.append(f)
        elif name not in seen:
            out.extend(replaced[name])
            seen.add(name)
    return out, audit


def annotate_build(features):
    """The unbuilt Hokkaido extension keeps its dashed construction identity."""
    for f in features:
        p = f["properties"]
        if p.get("n") == "北海道新幹線":
            s = CATALOG["lines"][p["n"]]["upgrades"][0]
            p.update(d=s["design"], de=s["from"] + "~" + s["to"],
                     ref=CATALOG["sources"][s["source"]]["url"])
    return features
