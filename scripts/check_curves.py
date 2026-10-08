"""Audit visible metro corners, including seams between display features.

Unlike the topology check's 70 degree limit, 12 degrees also catches the angular
bends left by an under-sampled or independently constrained smoothing curve.
Segments shorter than 3 m are ignored here because coordinate rounding dominates
their headings. This checks the written map data, not an intermediate spline.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from shapely.geometry import MultiLineString
from shapely.ops import linemerge

from check_layers import here, lines_of, sharp


def audit(limit=12, lines=None):
    lines = lines_of("metro") if lines is None else lines
    joined = {}
    for key, pieces in lines.items():
        g = linemerge(MultiLineString([g for g, _ in pieces]))
        joined[key] = [(part, 0) for part in (g.geoms if g.geom_type == "MultiLineString" else [g])]
    findings = sharp(joined, limit)
    counts = Counter(key for _, key, _ in findings)
    return {
        "limit_degrees": limit,
        "minimum_leg_m": 3.33,
        "lines_checked": len(lines),
        "cities_checked": len({key[0] for key in lines}),
        "corners": len(findings),
        "affected_lines": len(counts),
        "small_segments": {"minimum_leg_m": .5, "corners": len(sharp(joined, limit, .5 / 111000))},
        "by_threshold": {str(t): sum(a > t for a, _, _ in findings) for t in (12, 15, 20, 30, 45, 70) if t >= limit},
        "by_city": dict(Counter(key[0] for _, key, _ in findings).most_common()),
        "by_line": [{"city": key[0], "line": key[1], "corners": n} for key, n in counts.most_common()],
        "findings": [{"angle": round(a, 2), "city": key[0], "line": key[1],
                      "at": [pt.x, pt.y], "view": here(pt, 17)} for a, key, pt in findings],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--limit", type=float, default=12)
    args = parser.parse_args()
    result = audit(args.limit)
    print(json.dumps({k: v for k, v in result.items() if k not in ("findings", "by_line", "by_city")}, ensure_ascii=False, indent=2))
    for row in result["findings"][:20]:
        print(f"{row['angle']:5.1f}° {row['city']} {row['line']} {row['view']}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2))
