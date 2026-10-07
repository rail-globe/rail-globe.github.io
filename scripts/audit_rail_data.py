"""Inventory every named national-rail way and its status evidence; does not edit data."""
import csv
import json
import math
import pickle
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from rail_status import corrected_tags, load_rules

ROOT = Path(__file__).resolve().parents[1]


def track_km(coords):
    return sum(math.hypot((b[0] - a[0]) * math.cos(math.radians((a[1] + b[1]) / 2)), b[1] - a[1]) * 111.2
               for a, b in zip(coords, coords[1:]))


def main():
    ex = pickle.load(open(ROOT / "data/raw/extract.pkl", "rb"))
    rules = load_rules(ROOT / "data/rail_status_overrides.json")
    rows = defaultdict(lambda: {"ways": 0, "tags_km": Counter(), "effective_km": Counter(),
                                "evidence": set(), "highspeed_km": 0, "bbox": [180, 90, -180, -90]})
    unnamed = Counter()
    invalid = []
    tag_counts = Counter()
    for wid, tags, coords in ex["ways"]:
        if tags.get("railway") not in ("rail", "construction") or tags.get("service"):
            continue
        if tags["railway"] == "construction" and not (tags.get("construction") == "rail" or
                                                       tags.get("construction:railway") == "rail"):
            continue  # Subway construction is audited with the metro layer, not national rail.
        tag_counts[tags["railway"]] += 1
        if len(coords) < 2 or any(not math.isfinite(x) or not math.isfinite(y) or
                                  not (-180 <= x <= 180 and -90 <= y <= 90) for x, y in coords):
            invalid.append(wid)
            continue
        name = tags.get("name:zh") or tags.get("name", "")
        length = track_km(coords)
        if not name:
            unnamed[tags["railway"]] += length
            continue
        row = rows[name]
        row["ways"] += 1
        row["tags_km"][tags["railway"]] += length
        fixed, evidence = corrected_tags(tags, coords, rules)
        row["effective_km"][fixed["railway"]] += length
        if evidence:
            row["evidence"].add(evidence)
        if tags.get("highspeed") == "yes":
            row["highspeed_km"] += length
        b = row["bbox"]
        for x, y in coords:
            b[:] = [min(b[0], x), min(b[1], y), max(b[2], x), max(b[3], y)]
    out = []
    for name, row in rows.items():
        row["name"] = name
        row["tags_km"] = {k: round(v, 3) for k, v in row["tags_km"].items()}
        row["effective_km"] = {k: round(v, 3) for k, v in row["effective_km"].items()}
        row["highspeed_km"] = round(row["highspeed_km"], 3)
        row["evidence"] = sorted(row["evidence"])
        row["verification"] = "source-backed section" if row["evidence"] else "OSM tags only, operating status not independently certified"
        row["evidence_stages"] = sorted({r["stage"] for r in rules if r["id"] in row["evidence"]})
        row["risk"] = ("status corrected" if row["tags_km"] != row["effective_km"] else
                       "mixed operating/construction sections" if len(row["tags_km"]) > 1 else
                       "construction needs opening check" if "construction" in row["tags_km"] else
                       "no known tag conflict")
        out.append(row)
    out.sort(key=lambda r: (not bool(r["evidence"]), r["risk"], -sum(r["tags_km"].values())))
    dest = ROOT / "output/freshness"
    dest.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    audit = {"checked_at": now.isoformat(), "sources": ex.get("sources", []),
             "named_lines": len(out), "unnamed_track_km": dict(unnamed),
             "scope": "Raw OSM railway=rail and construction=rail track names, including heavy-rail urban/intercity track; name variants are not separate certified lines.",
             "eligible_ways": dict(tag_counts), "invalid_geometry_way_ids": invalid,
             "rules_due_for_review": [r["id"] for r in rules if r.get("review_after", "9999-12-31") <= now.date().isoformat()],
             "rules": rules, "lines": out}
    (dest / "rail-inventory.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    with open(dest / "rail-inventory.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["line", "OSM rail track km", "OSM construction track km", "effective rail track km",
                         "effective construction track km", "effective proposed track km", "risk", "verification", "evidence stage", "evidence rule", "bbox"])
        for r in out:
            writer.writerow([r["name"], r["tags_km"].get("rail", 0), r["tags_km"].get("construction", 0),
                             r["effective_km"].get("rail", 0), r["effective_km"].get("construction", 0),
                             r["effective_km"].get("proposed", 0), r["risk"], r["verification"],
                             "; ".join(r["evidence_stages"]), "; ".join(r["evidence"]), r["bbox"]])
    print("named railway inventories:", len(out), "source-backed:", sum(bool(r["evidence"]) for r in out))
    print("risks:", dict(Counter(r["risk"] for r in out)))
    print("rules due for review:", audit["rules_due_for_review"], "invalid geometries:", len(invalid))


if __name__ == "__main__":
    main()
