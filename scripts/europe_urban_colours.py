"""Match official colour evidence to a complete urban route identity.

No name-only, country-only, network-only or colour-only fallback is permitted.
The caller may supply one route while accumulating a line, or its full route set.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sources():
    return json.loads((ROOT / 'data/europe_urban_sources.json').read_text())


def match_source(code, network, name, relation_ids, records=None):
    if isinstance(relation_ids, (str, bytes)):
        raise TypeError('relation_ids must contain native integer relation IDs')
    wanted = frozenset(relation_ids)
    if not wanted or any(type(rid) is not int for rid in wanted):
        return None
    matches = []
    for entry in sources() if records is None else records:
        if (entry.get('g'), entry.get('network'), entry.get('n')) != (code, network, name):
            continue
        if not entry.get('colour') or entry.get('exclude'):
            continue
        known = frozenset(entry.get('osm_relations', ()))
        if wanted <= known:
            matches.append(entry)
    if len({entry['colour'] for entry in matches}) > 1:
        raise ValueError('conflicting official colours for the same native route identity')
    return matches[0] if matches else None


def colour_for(code, network, name, relation_ids, records=None):
    entry = match_source(code, network, name, relation_ids, records)
    return entry['colour'] if entry else None


def match_colour(code, key, rid, records=None):
    """country.urban_route_key adapter: preserve the full original key on no match."""
    network, name, colour = key
    matched = colour_for(code, network, name, [rid], records)
    return (network, name, matched if matched is not None else colour)
