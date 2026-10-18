"""Verified public-service exceptions to the legacy 2 km urban-route cutoff."""

L8 = frozenset({5622077, 5622078})
# FGV, April 2025, annex I p19: an operating tram route Neptú–Marítim.
SOURCE = 'https://www.fgv.es/wp-content/uploads/2025/04/Pliego-condiciones-de-Ocupacion-Temporal_exp-A-2025-003.pdf'


def minimum(code, network, name, relation_ids, default):
    ids = frozenset(relation_ids)
    if (code, network, name) == ('es', 'Metrovalencia', 'Línia 8') and ids and ids <= L8:
        return min(default, .5)
    return default
