"""Final display-only topology pass. Routing still uses every original track."""
from collections import defaultdict

from shapely.geometry import LineString

from single_track import bridge, one_track, smooth, stitch, unfold


def unfolded(parts):
    """The parts with their turnbacks taken out."""
    # Ten-metre samples and opposing headings find short turnback folds that the
    # coarse reduction misses without cutting ordinary curves or circular lines.
    for iteration in range(3):
        split = [piece for g in parts for piece in unfold(g, step=0.0001, fine=True)]
        if iteration and len(split) == len(parts):
            break
        previous = sum(g.length for g in parts)
        parts = stitch(one_track(split))
        # Stitching can expose a second fold that was hidden inside the first one.
        if previous - sum(g.length for g in parts) < .00002:
            break
    return parts


def finish_metro(features, routing):
    source = defaultdict(list)
    for name, colour, tracks in routing:
        source[name].extend([list(map(tuple, co)) for co in tracks])
    repaired = removed = 0
    for f in features:
        props, geom = f["properties"], f["geometry"]
        coords = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
        parts = [LineString(co) for co in coords if len(co) > 1]
        before = sum(g.length for g in parts)
        parts = unfolded(parts)
        removed += before - sum(g.length for g in parts) > 0.0001
        tracks = source.get(props.get("n")) if props.get("k") != "s" else None
        for _ in range(3 if tracks else 0):
            bag = {props["n"]: parts}
            joins = bridge(bag, tracks, joined=0.0015, reach=0.03, limit=0.045, project_ends=True)
            parts = stitch(bag[props["n"]], reach=0.0036)
            if not joins:
                break
            repaired += joins
            # A join restored along the source track can bring a turnback back with it: the way
            # round a terminal loop and back (輕鐵505綫 at 三聖). It is taken out again, and the
            # line is looked at once more for what that leaves apart.
            parts = unfolded(parts)
        out = []
        for g in parts:
            co = [[round(x, 6), round(y, 6)] for x, y in smooth(list(g.coords), reverse=181)]
            if len(co) > 1:
                out.append(co)
        if out:
            f["geometry"] = {"type": "LineString", "coordinates": out[0]} if len(out) == 1 else {"type": "MultiLineString", "coordinates": out}
    print(f"final metro display: folds reduced on {removed} lines; {repaired} joins restored along source tracks", flush=True)
