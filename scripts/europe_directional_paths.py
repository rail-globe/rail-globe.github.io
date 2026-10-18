"""Opt-in complete native directions for four source-audited tram services.

Lucentum L4/L5 retain only the original service=crossover member ways named in
their reviewed profiles. Their unnamed masters exist in the original PBF but
are absent from this extract. The fingerprint binds that exact absence AND all
available original parents, in addition to complete route/member/way inputs.
Any new or changed parent or member fails closed. No general service-track
exception is introduced.

This hook runs after normal urban ``drawn`` construction and before ``rounded``.
It changes no service identity and adds no endpoint-ordering scope. Callers must
also enable the existing ``line_bundles.apply(source_bound_cities=...)`` for the
chosen city. Unknown identities, incomplete/changed native membership, or a
source-bound failure return the original ``drawn`` object unchanged.

The fingerprints bind the reviewed frozen extract, including absent platform
members and complete route-master member lists. Zurich's two absent master
children are planned routes starting 2026-12-13 in the original PBF, not current
running directions. Evidence: reports/remaining-track-cases and directional-paths.
"""
import hashlib
import json
import math
from dataclasses import dataclass
from shapely.geometry import LineString
from shapely.ops import unary_union
from process_jp import runs_of
from single_track import stitch

# Fingerprints are populated from the reviewed original extract, never from
# adopted display names, colours, geometry proximity or generated array order.
@dataclass(frozen=True)
class SourceProfile:
    master: int
    fingerprint: str
    railway: tuple = ('tram',)
    running_service_members: tuple = ()
    expected_absent_master: bool = False
    context_fingerprint: str = None


PROFILES = {('ch', 'Libero', 'Tram 9', (1358504, 5507193)): SourceProfile(master=2629996, fingerprint='e032170367e116a330d93901d12803de8f96a1a61959b592352e2445ed6d3964', railway=('tram',), running_service_members=(), expected_absent_master=False, context_fingerprint='a284716fc80c6e74089bf26b64c9a09a830c58a3af335e2123d676604e183c24'), ('ch', 'ZVV', 'Tram 17', (1903834, 1903835)): SourceProfile(master=1903836, fingerprint='695e2af3641a22039bc902f229610da7ca6c2478715bf6e8029a8aedf1cec868', railway=('tram',), running_service_members=(), expected_absent_master=False, context_fingerprint='cc3cc7a31b22471dbcb550e1d0c0d8d17c6deb354c2d19471a169228e95b2244'), ('es', "TRAM Metropolità d'Alacant", "TRAM Metropolità d'Alacant L4", (190184, 6266683)): SourceProfile(master=21011335, fingerprint='f3f06d10bfaad4f5b4b64820c87cac74fa7f693e05ad2956211bff2f69b85240', railway=('tram', 'light_rail'), running_service_members=(421604691,), expected_absent_master=True, context_fingerprint='61d309e559917432e96574feb46d0794588e03490ffa1f41b080728c3841f42c'), ('es', "TRAM Metropolità d'Alacant", "TRAM Metropolità d'Alacant L5", (13154071, 14193223)): SourceProfile(master=21012558, fingerprint='ad24d9eb42649ab514e9250772ddfa168d5d403ae0e9e0c43b83e0a1276ad643', railway=('tram', 'light_rail'), running_service_members=(421604691, 421883135), expected_absent_master=True, context_fingerprint='b137ebfa8243192c4050cfb8f6d07cbf2979f44bb5099c6cebae0f9e6ed17de1')}



def source_fingerprint(rids, master, ways, relations, *, expected_absent_master=False):
    """Canonical complete relation/member/way input, including missing members."""
    relation_ids = tuple(sorted(set(rids)))
    records = []
    for rid in relation_ids + (master,):
        if rid not in relations:
            if rid == master and expected_absent_master:
                records.append([rid, None])
                continue
            return None
        tags, members = relations[rid]
        records.append([rid, tags, members])
    members = sorted({ref for rid in relation_ids for kind, ref in relations[rid][1]
                      if kind == 'w'})
    parents = [[rid, tags, members] for rid, (tags, members) in sorted(relations.items())
               if any(kind == 'r' and ref in relation_ids for kind, ref in members)]
    payload = {'relations': records, 'all_native_parents': parents,
               'ways': [[wid, ways.get(wid)] for wid in members]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def approved_service_way(country, rid, wid, ways, relations):
    """Pure shared source-ledger qualification for reviewed route crossovers.

    Country accumulation and an own-source auditor must use this same test.
    Ordinary source-track qualification remains the caller's responsibility.
    A way must be an explicit member of the exact reviewed native direction,
    and the entire source profile (not this way alone) must still match.
    """
    for (code, network, name, rids), profile in PROFILES.items():
        if code != country or rid not in rids or wid not in profile.running_service_members:
            continue
        if rid not in relations or ('w', wid) not in relations[rid][1]:
            return False
        if source_fingerprint(rids, profile.master, ways, relations,
                              expected_absent_master=profile.expected_absent_master) in tuple(v for v in (profile.fingerprint,profile.context_fingerprint) if v is not None):
            return True
    return False


def directional_paths(country, network, name, rids, ways, relations, drawn):
    """Return complete per-rid paths only for an exact audited source profile.

    ``ways`` maps original way ID to (original_tags, coordinates), ``relations``
    maps original relation ID to (original_tags, original_member_tuples), and
    ``rids`` must contain the complete current service identity. The return type
    is the same list-of-LineString stage used by normal ``drawn``. This is an
    explicit hook, not an automatic global replacement or an identity merger.
    """
    try:
        identity = tuple(sorted(int(r) for r in rids))
    except (TypeError, ValueError):
        return drawn
    profile = PROFILES.get((country, network, name, identity))
    if profile is None:
        return drawn
    if source_fingerprint(identity, profile.master, ways, relations,
                          expected_absent_master=profile.expected_absent_master) not in tuple(v for v in (profile.fingerprint,profile.context_fingerprint) if v is not None):
        return drawn
    candidates = []
    for rid in identity:
        # The fingerprint proves every omitted member was reviewed. Preserve
        # original member order and keep each complete direction independent.
        native = [ways[wid][1] for kind, wid in relations[rid][1]
                  if kind == 'w' and wid in ways
                  and ways[wid][0].get('railway') in profile.railway
                  and (not ways[wid][0].get('service')
                       or wid in profile.running_service_members)]
        if not native:
            return drawn
        paths = stitch(runs_of(native), bends=True)
        if not paths:
            return drawn
        pts = [pt for co in native for pt in co]
        lon = sum(pt[0] for pt in pts) / len(pts)
        lat = sum(pt[1] for pt in pts) / len(pts)
        sx = 111320 * math.cos(math.radians(lat))
        def metric(co):
            return LineString([((x-lon)*sx, (y-lat)*111320) for x, y in co])
        source = unary_union([metric(co) for co in native if len(co)>1])
        output = unary_union([metric(list(g.coords)) for g in paths])
        # Continuous symmetric geometric guard, measured separately per native
        # direction. No line is allowed to repair a missing source direction.
        if source.is_empty or output.is_empty or source.hausdorff_distance(output) > 25:
            return drawn
        candidates.extend(paths)
    return candidates
