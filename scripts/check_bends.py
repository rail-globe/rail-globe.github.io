"""Find tight bends in metres, independent of the number of spline samples.

These are review candidates, not engineering measurements or automatic repairs.
A 20 m chord on either side is compared every 5 m. Adjacent hits form one bend.
Opposite bends less than 120 m apart are also reported as a possible dogleg.
Light rail and monorail can legitimately have small radii and need source review.
"""
import argparse
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
from shapely.geometry import MultiLineString
from shapely.ops import linemerge

from check_layers import lines_of


def scan(co, arm=20, step=5, limit=20):
    co = np.asarray(co, dtype=float)
    scale = np.array([111320 * math.cos(math.radians(float(co[:, 1].mean()))), 110574])
    xy = (co - co[0]) * scale
    length = np.r_[0, np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    closed = np.array_equal(co[0], co[-1])
    if length[-1] < 2 * arm:
        return []
    at = np.arange(0 if closed else arm, length[-1] if closed else length[-1] - arm, step)
    def interp(d):
        d = d % length[-1] if closed else d
        return np.column_stack([np.interp(d, length, xy[:, k]) for k in (0, 1)])
    middle = interp(at)
    u, v = middle - interp(at - arm), interp(at + arm) - middle
    angles = np.degrees(np.arctan2(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0], (u * v).sum(axis=1)))
    hits = np.flatnonzero(abs(angles) > limit)
    groups = []
    for i in hits:
        if groups and i == groups[-1][-1] + 1 and angles[i] * angles[groups[-1][-1]] > 0:
            groups[-1].append(int(i))
        else:
            groups.append([int(i)])
    out = []
    for group in groups:
        i = max(group, key=lambda k: abs(angles[k]))
        pt = middle[i] / scale + co[0]
        out.append({"at": pt.tolist(), "along_m": round(float(at[i]), 1),
                    "turn_degrees": round(float(angles[i]), 2),
                    "radius_proxy_m": round(arm / abs(math.radians(float(angles[i]))), 1),
                    "span_m": round(float(at[group[-1]] - at[group[0]] + step), 1)})
    for i, row in enumerate(out):
        row["reverse_bend"] = any(other["turn_degrees"] * row["turn_degrees"] < 0
                                  and abs(other["along_m"] - row["along_m"]) <= 120
                                  for other in out[max(0, i - 2):i + 3])
    return out


def audit(lines=None, limit=20):
    lines = lines_of("metro") if lines is None else lines
    rows = []
    for key, pieces in sorted(lines.items()):
        g = linemerge(MultiLineString([g for g, _ in pieces]))
        for part in (g.geoms if g.geom_type == "MultiLineString" else [g]):
            for row in scan(part.coords, limit=limit):
                row.update(city=key[0], line=key[1], view=f"#17/{row['at'][1]:.5f}/{row['at'][0]:.5f}")
                rows.append(row)
    rows.sort(key=lambda r: -abs(r["turn_degrees"]))
    return {"arm_m": 20, "step_m": 5, "limit_degrees": limit,
            "lines_checked": len(lines), "cities_checked": len({k[0] for k in lines}),
            "bends": len(rows), "reverse_bends": sum(r["reverse_bend"] for r in rows),
            "affected_lines": len({(r["city"], r["line"]) for r in rows}),
            "by_line": dict(Counter(r["line"] for r in rows).most_common()), "findings": rows}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", type=Path)
    p.add_argument("--limit", type=float, default=20)
    args = p.parse_args()
    result = audit(limit=args.limit)
    print(json.dumps({k: v for k, v in result.items() if k not in ("findings", "by_line")}, ensure_ascii=False, indent=2))
    for r in result["findings"][:30]:
        print(f"{r['turn_degrees']:6.1f}° {r['line']} {r['view']} {'reverse' if r['reverse_bend'] else ''}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2))
