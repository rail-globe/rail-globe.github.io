"""Native, ordered OSM route evidence for endpoint ordering.

The extract has no member roles or node IDs. Equality of its unmodified endpoint
coordinates is therefore the only available connection evidence. A displayed
centre line or proximity to another way never supplies a missing connection.
"""
import math
from collections import defaultdict


# Every city whose trial passed (2026-10-18, "将 NATIVE_FINDINGS.md 思路融入排座"): against its
# legacy drawing, no more structural faults (twice, broken, loose, sharp), no more self-crossing
# parts or loops at z12, 14 and 16, its lines' courses on their own tracks kept and none off them
# (output/endpoint-all/trial/compare-<g>.json, tools/compare_cities.py). Basel, Hamburg and the Ruhr
# passed once a branch family's common centre no longer reached the stretch's other end, where it had
# turned every other line in a corner and folded its offset into small loops (endpoint_bundles.
# shared_centres; output/endpoint-all/fix/README.md). Left out, legacy drawing: Germany's elsewhere,
# Mannheim's 6A drawn twice, its input running out and back. Off-track stretches and loose ends the
# legacy drawing has as well are not counted against a trial (Berlin's Tram 67, Karlsruhe's S8 and S7:
# output/endpoint-all/final/failed-cities.md).
ENDPOINT_CITIES = {
    "it": ("佛罗伦萨", "博洛尼亚", "卡利亚里", "墨西拿", "威尼斯", "巴勒莫", "帕多瓦", "的里雅斯特", "米兰", "罗马", "萨萨里", "贝加莫", "那不勒斯", "都灵",),
    "ch": ("伯尔尼", "巴塞尔", "日内瓦", "洛桑", "苏黎世",),
    "es": ("圣克鲁斯-德特内里费", "塞维利亚", "巴塞罗那", "帕尔马", "格拉纳达", "毕尔巴鄂", "瓦伦西亚", "萨拉戈萨", "西班牙其他", "阿利坎特", "马德里", "马拉加",),
    "nl": ("乌得勒支", "海牙", "阿姆斯特丹", "鹿特丹",),
    "be": ("列日", "奥斯坦德", "安特卫普", "布鲁塞尔", "根特", "沙勒罗瓦",),
    "fr": ("南特", "图卢兹", "尼斯", "巴黎", "斯特拉斯堡", "格勒诺布尔", "法国其他", "波尔多", "蒙彼利埃", "里尔", "里昂", "马赛", "鲁昂",),
    "de": ("不来梅", "卡尔斯鲁厄", "哈勒", "德累斯顿", "慕尼黑", "斯图加特", "杜塞尔多夫", "柏林", "汉堡", "汉诺威", "法兰克福", "科隆", "纽伦堡", "莱比锡", "鲁尔",),
    # South-East Asia (2026-10-19), compared the same way: Kuala Lumpur's z12 self-crossings 2 -> 0,
    # Jakarta's 1 -> 0, every line kept and on its own track. Bangkok's and Singapore's light rail
    # lines share no stretch, so the order at their junctions is not in question.
    "my": ("吉隆坡",),
    "id": ("巨港", "雅加达",),
    # Austria and Hungary (2026-10-21), compared the same way (output/at-hu-runs/endpoint/compare-*.txt):
    # every line kept and on its own track; z12 self-crossings Vienna 30 -> 10, Graz 15 -> 7,
    # Innsbruck 19 -> 4, Linz 10 -> 2, Szeged 5 -> 1, Miskolc 2 -> 0. At first left out, legacy drawing:
    # Budapest, where the trial drew one more line twice beside itself (tram 51; tram 59 more of
    # its length), though its self-crossings fell 42 -> 22. With the lines drawn once
    # (single_track.one_copy, 2026-10-22) Budapest passes too: z12 self-crossings 42 -> 27, z14
    # 15 -> 7, z16 9 -> 1, every line on its own track (59 was at 35%, 61 at 65%).
    "at": ("因斯布鲁克", "奥地利其他", "林茨", "格拉茨", "维也纳",),
    "hu": ("塞格德", "德布勒森", "米什科尔茨", "布达佩斯",),
}
# A trial of every city of a country (2026-10-18, "将 NATIVE_FINDINGS.md 思路融入排座"): the
# environment variable ENDPOINT_TRIAL=1 makes every city of the light rail use endpoint ordering,
# so each can be compared with its legacy drawing before it is switched on in ENDPOINT_CITIES.
import os
ENDPOINT_TRIAL = os.environ.get("ENDPOINT_TRIAL") == "1"


def endpoint_cities_of(code, features):
    """The cities whose light rail is ordered at its endpoints: those listed, or in a trial all."""
    if ENDPOINT_TRIAL:
        return tuple(sorted({f["properties"].get("ct") for f in features
                             if f["properties"].get("jk") == "urban" and f["properties"].get("ct")}))
    return ENDPOINT_CITIES.get(code, ())


def line_key(props):
    return f"{props.get('network', '')}|{props['n']}|{props.get('rid', '')}"


def _coordinates(co):
    try:
        points = [tuple(p) for p in co]
        if len(points) < 2 or any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in points):
            return None
        return points if len(set(points)) > 1 else None
    except (TypeError, ValueError):
        return None


def route_chunks(rid, tags, members, ways, allowed_railways):
    """Retain ordered way provenance and break every unsupported transition.

    Station nodes do not describe the route path. Unknown relation members do,
    however, form barriers. With roles absent, two adjacent ways can join only
    when exactly one endpoint pair matches and the current direction agrees.
    """
    chunks, chunk_members, breaks = [], [], []
    current, provenance = [], []
    previous = None

    def flush():
        nonlocal current, provenance, previous
        if current:
            chunks.append([list(p) for p in current])
            chunk_members.append(provenance)
        current, provenance, previous = [], [], None

    def barrier(index, ref, reason, **details):
        flush()
        breaks.append(dict(member_index=index, ref=ref, reason=reason, **details))

    for index, member in enumerate(members):
        kind, ref = member[:2]
        if kind == "n":
            continue
        if kind != "w":
            barrier(index, ref, "unsupported_member_type", kind=kind)
            continue
        if ref not in ways:
            barrier(index, ref, "missing_way")
            continue
        way_tags, raw = ways[ref]
        if way_tags.get("railway") not in allowed_railways or way_tags.get("service"):
            barrier(index, ref, "ineligible_way")
            continue
        co = _coordinates(raw)
        if co is None:
            barrier(index, ref, "invalid_geometry")
            continue
        item = dict(way_id=ref, member_index=index, reversed=False)
        if previous is None:
            current, provenance, previous = co[:], [item], co
            continue
        matches = [(a, b) for a in (0, -1) for b in (0, -1) if previous[a] == co[b]]
        if len(matches) != 1:
            barrier(index, ref, "endpoint_gap" if not matches else "ambiguous_orientation")
            current, provenance, previous = co[:], [item], co
            continue
        a, b = matches[0]
        if len(provenance) == 1:
            # A first way has no established direction until this unique join.
            if a == 0:
                current.reverse()
                provenance[0]["reversed"] = True
        elif current[-1] != previous[a]:
            # Ordered members would have to traverse the preceding way twice.
            barrier(index, ref, "direction_conflict")
            current, provenance, previous = co[:], [item], co
            continue
        oriented = co if b == 0 else co[::-1]
        item["reversed"] = b != 0
        current.extend(oriented[1:])
        provenance.append(item)
        previous = co
    flush()
    return {"rid": rid, "tags": dict(tags), "chunks": chunks,
            "chunk_members": chunk_members, "breaks": breaks,
            "disconnected_member_breaks": len(breaks)}


def build_sources(features, ways, relations, allowed_railways):
    """Build source evidence keyed exactly like the generated feature identity.

    `ways` and `relations` are the native extract mappings, before one_track,
    stitch or rounded. Unavailable identities are explicit incomplete evidence.
    """
    master_of = defaultdict(list)
    for master_id, (tags, members) in relations.items():
        if tags.get("type") == "route_master":
            for kind, ref, *_ in members:
                if kind == "r":
                    master_of[ref].append(master_id)
    result = {}
    for feature in features:
        props = feature["properties"]
        key = line_key(props)
        if key in result:
            continue
        raw_ids = str(props.get("rid") or "").split(",")
        valid_ids = [int(value) for value in raw_ids if value.strip().isdigit()]
        rids = sorted(set(valid_ids))
        reasons = []
        if not rids or len(valid_ids) != len(raw_ids):
            reasons.append({"reason": "missing_or_invalid_feature_relation_identity"})
        source = {"rids": rids, "masters": sorted({mid for rid in rids for mid in master_of[rid]}),
                  "routes": [], "way_ids": [], "ways": [], "incomplete_reasons": reasons,
                  "coordinate_basis": "native_extract_way_coordinates", "member_roles_available": False,
                  "node_ids_available": False}
        used = set()
        for rid in rids:
            if rid not in relations:
                reasons.append({"reason": "missing_relation", "rid": rid})
                continue
            tags, members = relations[rid]
            if tags.get("type") != "route":
                reasons.append({"reason": "not_route_relation", "rid": rid})
                continue
            route = route_chunks(rid, tags, members, ways, allowed_railways)
            route["masters"] = sorted(master_of[rid])
            source["routes"].append(route)
            reasons.extend(dict(event, rid=rid) for event in route["breaks"])
            used.update(item["way_id"] for chunk in route["chunk_members"] for item in chunk)
        source["way_ids"] = sorted(used)
        source["ways"] = [{"way_id": wid, "tags": dict(ways[wid][0]),
                           "coordinates": [list(p) for p in ways[wid][1]]} for wid in sorted(used)]
        result[key] = source
    return result
