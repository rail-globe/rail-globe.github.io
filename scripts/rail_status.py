"""Apply source-backed operating status without changing the cached OSM objects."""
import json
from pathlib import Path


def load_rules(path):
    rules = json.loads(Path(path).read_text()) if Path(path).exists() else []
    ids = set()
    for rule in rules:
        if rule["id"] in ids:
            raise ValueError("duplicate status rule: " + rule["id"])
        ids.add(rule["id"])
        if rule["status"] not in ("rail", "construction", "proposed"):
            raise ValueError("invalid status: " + rule["status"])
        if not rule.get("sources") or not rule.get("checked") or not rule.get("names"):
            raise ValueError("status rule needs names, evidence and date: " + rule["id"])
    return rules


def matching_rules(tags, coords, rules):
    names = {tags.get("name"), tags.get("name:zh")}
    for rule in rules:
        if not names.intersection(rule["names"]):
            continue
        if rule.get("bbox"):
            west, south, east, north = rule["bbox"]
            # Never change a way crossing the verified section boundary wholesale.
            if not all(west <= x <= east and south <= y <= north for x, y in coords):
                continue
        yield rule


def corrected_tags(tags, coords, rules):
    hits = list(matching_rules(tags, coords, rules))
    if not hits:
        return tags, None
    if len({r["status"] for r in hits}) != 1:
        raise ValueError("conflicting status evidence: " + str([r["id"] for r in hits]))
    rule = hits[-1]
    out = dict(tags)
    out["railway"] = rule["status"]
    if rule["status"] == "construction":
        if out.get("construction") != "rail" and out.get("construction:railway") != "rail":
            out["construction"] = "rail"
    else:
        out.pop("construction", None)
        out.pop("construction:railway", None)
    if rule.get("speed"):
        out["maxspeed"] = str(rule["speed"])
    return out, rule["id"]
