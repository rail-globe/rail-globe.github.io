"""Conservative, opt-in aliases for independently audited service identities.

No name/colour/proximity heuristic. A reviewed original route master, exact child
relation set, refs, modes and source networks must still match. This module does
not change generated data or install itself in the pipeline. Call build_matcher
from a preflight and compose the returned callback with urban_route_key.

Essen's conflicting colours require a caller-provided reviewed colour. Identity
proof does not decide a colour. Milan 31/ and Naples 2BR are intentionally absent:
current operating variants/status do not justify a blanket same-service merge.
"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Candidate:
    country: str
    master: int
    routes: tuple
    ref: str
    mode: str
    networks: tuple
    official_url: str


CANDIDATES = (
    Candidate('ch',9173651,(4253314,9129284,11815262,11815263),'8','tram',('RVL;TNW','TNW'),
              'https://rvl-online.de/liniennetz-fahrplan/linien/'),
    Candidate('de',273002,(4783689,4783690,4785803,5781485),'S 1','light_rail',('saarVV;TER Grand Est','saarVV'),
              'https://www.saarbahn.de/fahrplan/fahrplaene'),
    Candidate('de',21602858,(21602856,21602857),'101','tram',('VRR',),
              'https://metropolnetz.ruhrbahn.de/'),
    Candidate('de',4232441,(11065592,11065593),'103','tram',('VRR',),
              'https://metropolnetz.ruhrbahn.de/'),
    Candidate('de',5310407,(38430,4540371),'106','tram',('VRR',),
              'https://metropolnetz.ruhrbahn.de/'),
)


def colour(value):
    return value.lower() if isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value) else None


def build_matcher(extract, country, *, reviewed_colours=None):
    """Return (route_key_callback, audit). Existing unbound keys pass unchanged.

    reviewed_colours maps actual master IDs to explicitly reviewed display colours.
    The callback has Country.urban_route_key's (key, actual_rid) signature. All
    constituent original relation IDs remain in country's line provenance ledger.
    """
    reviewed_colours = reviewed_colours or {}
    relations = {rid:(tags,members) for rid,tags,members in extract['relations']}
    mapping,audit={},[]
    for candidate in CANDIDATES:
        if candidate.country != country:
            continue
        issues=[]
        master=relations.get(candidate.master)
        if master is None:
            issues.append('missing_master')
        else:
            tags,members=master
            if (tags.get('type'),tags.get('route_master'),tags.get('ref')) != ('route_master',candidate.mode,candidate.ref):
                issues.append('master_tags_changed')
            if {ref for typ,ref in members if typ=='r'} != set(candidate.routes):
                issues.append('master_children_changed')
            if tags.get('network') not in candidate.networks or not tags.get('name'):
                issues.append('master_identity_changed')
        native_colours=set()
        for rid in candidate.routes:
            route=relations.get(rid)
            if route is None:
                issues.append('missing_route:'+str(rid));continue
            tags,_=route
            if (tags.get('type'),tags.get('route'),tags.get('ref')) != ('route',candidate.mode,candidate.ref):
                issues.append('route_tags_changed:'+str(rid))
            if tags.get('network') not in candidate.networks:
                issues.append('route_network_changed:'+str(rid))
            native_colours.add(colour(tags.get('colour')))
        selected=colour(reviewed_colours.get(candidate.master))
        if selected is None and len(native_colours)==1 and None not in native_colours:
            selected=next(iter(native_colours))
        if selected is None:
            issues.append('reviewed_colour_required')
        row=dict(country=country,master=candidate.master,routes=list(candidate.routes),ref=candidate.ref,
                 source=candidate.official_url,status='blocked' if issues else 'accepted',issues=issues,
                 native_colours=sorted(native_colours,key=lambda c:c or ''),canonical_colour=selected)
        if not issues:
            tags,_=master
            canonical=(tags['network'],tags['name'],selected)
            row['canonical_key']=list(canonical)
            for rid in candidate.routes:
                mapping[rid]=(candidate,canonical)
        audit.append(row)

    def route_key(key, actual_rid):
        bound=mapping.get(actual_rid)
        if bound is None:
            return key
        candidate,canonical=bound
        if key[0] not in candidate.networks or key[1] != canonical[1]:
            return key                         # another callback changed the identity
        return canonical
    return route_key,audit
