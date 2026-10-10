"""Apply source-backed operating status without changing the cached OSM objects.

A rule names the line it is about (names, and a bbox for a section of it), or, for track that OSM
gives no name, the ways themselves (ways: their ids). A rule of the second kind can also say what
line the track is (line) and of what use (usage): 乐德线 runs on from where its named track ends to
the copper mine at 泗洲 over 22 km of track that OSM has as an unnamed industrial spur."""
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
        if not rule.get("sources") or not rule.get("checked") or not (rule.get("names") or rule.get("ways")):
            raise ValueError("status rule needs names or ways, evidence and date: " + rule["id"])
    return rules


def matching_rules(tags, coords, rules, way=None):
    names = {tags.get("name"), tags.get("name:zh")}
    for rule in rules:
        if rule.get("ways"):
            if way in rule["ways"]:
                yield rule
            continue
        if not names.intersection(rule["names"]):
            continue
        if rule.get("bbox"):
            west, south, east, north = rule["bbox"]
            # Never change a way crossing the verified section boundary wholesale.
            if not all(west <= x <= east and south <= y <= north for x, y in coords):
                continue
        yield rule


def corrected_tags(tags, coords, rules, way=None):
    hits = list(matching_rules(tags, coords, rules, way))
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
    if rule.get("line"):                 # unnamed track that a source shows to be a line's
        out["name"] = rule["line"]
        out.pop("service", None)
        out["usage"] = rule.get("usage", "branch")
    return out, rule["id"]
