"""Native-ID-bound display correction after station capsule source proof.
Installed through Country.urban_station_display, retaining raw stop names upstream.
No source tuple, stop name, station position or feature count is changed.
"""
import copy

EXPECTED_NODES={1770715974:'6032',2032998808:'6031'}
OLD='Cappuccina Villa ErizzoM9'
NEW='Cappuccina Villa Erizzo M9'

def correct_generated_station_names(code,stations,*,extract_sha256,proof):
    output=copy.deepcopy(stations)
    if code!='it' or extract_sha256!=proof.get('extract_sha256'):
        return output
    nodes={x['id']:x for x in proof.get('native_nodes',[]) if x.get('type')=='n'}
    if set(nodes)!=set(EXPECTED_NODES):return output
    for nid,ref in EXPECTED_NODES.items():
        tags=nodes[nid]['tags']
        if (tags.get('name'),tags.get('ref'),tags.get('network'),tags.get('public_transport')) != (OLD,ref,'Rete Urbana di Mestre','platform'):
            return output
    allowed={tuple(round(v,5) for v in nodes[nid]['at']) for nid in EXPECTED_NODES}
    for f in output:
        p=f.get('properties',{});g=f.get('geometry',{})
        if (p.get('g'),p.get('n'),p.get('m'),g.get('type'))==('it',OLD,1,'Point') and tuple(g.get('coordinates',())) in allowed:
            p['n']=NEW
    return output
