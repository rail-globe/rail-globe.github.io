"""Choose one principal grade from the track length of every grade on a line."""
from collections import Counter


GRADE_ORDER = ("branch", "main", "hsr200", "hsr250", "hsr350")
FAST_GRADES = GRADE_ORDER[2:]


def grade_votes(tagged_km, ungraded_fast_km=0.0):
    """Unknown-speed high-speed track follows its line's observed fast grade.

    Without an observed fast grade, retain the existing unknown-HSR fallback of 250.
    Ordinary untagged track already has its main/branch usage grade in tagged_km.
    """
    votes = Counter(tagged_km)
    if ungraded_fast_km:
        observed = [grade for grade in FAST_GRADES if votes[grade] > 0]
        grade = max(observed, key=lambda g: votes[g]) if observed else "hsr250"
        votes[grade] += ungraded_fast_km
    return votes


def principal_class(tagged_km, ungraded_fast_km=0.0):
    """Vote once across all grades, rather than pooling fast grades first.

    For example, 45 km main + 31 km 250 + 25 km 200 is a main line. Pooling the
    two fast grades first would incorrectly promote all 101 km to the minority 250 grade.
    Exact ties use the lower grade, independent of the input way order.
    """
    votes = grade_votes(tagged_km, ungraded_fast_km)
    return max(GRADE_ORDER, key=lambda g: votes[g]) if sum(votes.values()) else "branch"
