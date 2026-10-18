"""Retain named and unnamed construction, including short urban extensions."""
from collections import defaultdict

from process_jp import CURVE, TOL, geometry, rounded, runs_of
from single_track import one_track


def construction_features(cfg, ways, namer):
    groups = defaultdict(list)
    for wid, (tags, coords) in ways.items():
        kind = tags.get("construction") or tags.get("construction:railway")
        if (tags.get("railway") != "construction" or tags.get("service")
                or kind not in cfg.rail | cfg.urban | {None} or len(coords) < 2):
            continue
        name = cfg.build_name(cfg.plain_name(tags.get("name")))
        # Unknown names remain empty; type keeps tram and railway construction distinct.
        groups[(kind, name)].append(wid)
    result = []
    for (kind, name), wids in sorted(groups.items(), key=lambda row: (row[0][0] or "", row[0][1])):
        paths = one_track(runs_of([ways[wid][1] for wid in sorted(wids)]))
        # No gap-spanning stitch: these are actual currently mapped construction stretches.
        coords = rounded(paths, TOL["rail"], CURVE["rail"], places=5)
        if not coords:
            continue
        props = {"c": "build", "n": name, "g": cfg.code,
                 "construction_kind": kind or "unknown",
                 "source_way_ids": ",".join(str(wid) for wid in sorted(wids))}
        if not name:
            props["unnamed"] = 1
        else:
            for wid in wids:
                namer.add(name, ways[wid][0])
            namer.line(props)
        result.append({"type": "Feature", "properties": props, "geometry": geometry(coords)})
    return result
