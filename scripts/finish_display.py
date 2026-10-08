"""Final display-only topology pass. Routing still uses every original track."""
from collections import defaultdict

from shapely.geometry import LineString, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

from single_track import bridge, curved, one_track, smooth, stitch, unfold
from metro_bends import repair as repair_bends, junctions


def unfolded(parts):
    """The parts with their turnbacks taken out."""
    # Ten-metre samples and opposing headings find short turnback folds that the
    # coarse reduction misses without cutting ordinary curves or circular lines.
    for iteration in range(3):
        split = [piece for g in parts for piece in unfold(g, step=0.0001, fine=True)]
        if iteration and len(split) == len(parts):
            break
        previous = sum(g.length for g in parts)
        parts = stitch(one_track(split), bends=True)
        # Stitching can expose a second fold that was hidden inside the first one.
        if previous - sum(g.length for g in parts) < .00002:
            break
    return parts


def finish_metro(features, routing, curve=None, within=None, light=(), light_curve=None, light_within=None, anchors=()):
    """light: the (region, name) of the light-rail lines, whose street curves are drawn with
    light_curve and light_within in place of curve and within."""
    source = defaultdict(list)
    for name, colour, tracks in routing:
        source[name].extend([list(map(tuple, co)) for co in tracks])
    repaired = removed = 0
    bend_report = []
    prepared = []
    for f in features:
        geom=f['geometry']
        coords=geom['coordinates'] if geom['type']=='MultiLineString' else [geom['coordinates']]
        parts=[LineString(co) for co in coords if len(co)>1]
        before=sum(g.length for g in parts)
        parts=unfolded(parts)
        removed += before-sum(g.length for g in parts)>.0001
        prepared.append(parts)
    physical = junctions([co for tracks in source.values() for co in tracks])
    physical_tree = STRtree([Point(p) for p in physical])
    drawn = unary_union([g for parts in prepared for g in parts])
    drawn_parts = list(drawn.geoms) if drawn.geom_type=='MultiLineString' else [drawn]
    # Only a source junction that is actually used as a branch in the drawing
    # is fixed. A spare crossover beside the passenger path must not pin a
    # wrong detour onto the map. Noding removes duplicate collinear edges.
    ports = [p for p in junctions([list(g.coords) for g in drawn_parts])
             if len(physical_tree.query(Point(p),predicate='dwithin',distance=.00002))]
    for f,parts in zip(features,prepared):
        props, geom = f["properties"], f["geometry"]
        coords = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
        tracks = source.get(props.get("n")) if props.get("k") != "s" else None
        fine = (props.get("r"), props.get("n")) in light
        bend, tol = (light_curve, light_within) if fine else (curve, within)
        for _ in range(3 if tracks else 0):
            bag = {props["n"]: parts}
            joins = bridge(bag, tracks, joined=0.0015, reach=0.03, limit=0.045, project_ends=True)
            parts = stitch(bag[props["n"]], reach=0.0036, bends=True)
            if not joins:
                break
            repaired += joins
            # A join restored along the source track can bring a turnback back with it: the way
            # round a terminal loop and back (輕鐵505綫 at 三聖). It is taken out again, and the
            # line is looked at once more for what that leaves apart.
            parts = unfolded(parts)
        if tracks:
            # First restore wrong local detours using this line's source track. Only
            # verified source errors get a separate bounded refit. Sampling is last.
            xs,ys=zip(*(p for co in coords for p in co))
            xmin,xmax,ymin,ymax=min(xs)-.00003,max(xs)+.00003,min(ys)-.00003,max(ys)+.00003
            nearby=[p for p in ports if xmin<=p[0]<=xmax and ymin<=p[1]<=ymax]
            parts, findings = repair_bends(parts, tracks, props.get('n'), protected=nearby, anchors=anchors)
            bend_report.extend(findings)
        out = []
        for g in parts:
            # last of all the bends are drawn back as curves: nothing after this moves a vertex
            co = smooth(list(g.coords), reverse=181)
            co = [[round(x, 7), round(y, 7)] for x, y in (curved(co, *bend, within=tol, adaptive=True) if bend else co)]
            co = [p for i, p in enumerate(co) if not i or p != co[i - 1]]
            if len(co) > 1:
                out.append(co)
        if out:
            f["geometry"] = {"type": "LineString", "coordinates": out[0]} if len(out) == 1 else {"type": "MultiLineString", "coordinates": out}
    print(f"final metro display: folds reduced on {removed} lines; {repaired} joins restored along source tracks", flush=True)
    return bend_report
