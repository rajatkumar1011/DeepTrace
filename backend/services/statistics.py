"""Small-sample statistics shared by everything in DeepTrace that reports a rate.

There is exactly one implementation of the Wilson interval here because three
surfaces quote intervals — the labelled benchmark, the robustness harness and the
A/V consistency module — and a figure printed in a report next to a figure shown
on screen must not be able to come from two different formulas.

Wilson rather than the normal approximation, for the reason that matters at
DeepTrace's scale: at n=12 the normal interval on 11 successes runs past 1.0,
which would let the system print an upper bound of 100%. Wilson does not.
"""

import math

DEFAULT_Z = 1.96  # two-sided 95%


def wilson_interval(successes: int, total: int, z: float = DEFAULT_Z):
    """95% Wilson score interval, or None when there is nothing to bound.

    ``None`` for ``total == 0`` is deliberate and must be preserved by callers: a
    rate with no denominator is undefined, not zero, and rendering it as [0, 0]
    would present the absence of data as a measured certainty.
    """
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z / denominator * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


def interval_width(interval) -> float | None:
    """How wide a reported interval is — the honest headline for a small sample."""
    if not isinstance(interval, (list, tuple)) or len(interval) != 2:
        return None
    try:
        return round(abs(float(interval[1]) - float(interval[0])), 4)
    except (TypeError, ValueError):
        return None
