"""Forbidden vectors and collision-free period completion.

Implements thesis sections 2.10 (compute forbidden vectors), 2.11
(normalize forbidden vectors) and 2.12 (choose collision-free vectors).

Terminology: a copy of a wallpaper component is identified by its *origin*,
the wallpaper position of its origin piece.  Copies whose origins differ by
a natural period are the same component.  A vector ``f`` is *forbidden* when
a component overlaps its own translate by ``f``; the coloring lattice must
avoid all nonzero forbidden classes so equally-colored components never
overlap.

The selection here is stricter than the thesis pseudocode: instead of only
checking a candidate vector against each forbidden class directly, the full
candidate lattice (natural periods plus chosen vectors) is verified to
contain no forbidden vector.  This also covers collisions at integer
multiples or mixed combinations of the chosen vectors.
"""

from escher.lattice import Vec, det, hnf_basis, lattice_contains, reduce_mod
from escher.periods import Component

Overlap = tuple[int, int]

_SEARCH_LIMITS = (4, 8, 16, 32, 64)


def forbidden_classes(component: Component, overlaps: list[Overlap]) -> list[Vec]:
    """Compute the forbidden vector classes of one component.

    Every overlap between two pieces of the component that belong to
    *different* copies of the component yields a forbidden translation
    between those copies (in both directions).  Overlaps whose pieces belong
    to the same copy (difference inside the natural lattice) are harmless
    self-overlaps and are skipped.

    Args:
        component: The component with generating set and natural periods.
        overlaps: All overlapping piece pairs of the tile.

    Returns:
        Sorted canonical representatives, one per forbidden class modulo the
        natural-period lattice (thesis Table 2.5, plus the opposite signs).
    """
    positions = component.positions
    classes: set[Vec] = set()
    for a, b in overlaps:
        if a not in positions or b not in positions:
            continue
        pa, pb = positions[a], positions[b]
        for f in ((pa[0] - pb[0], pa[1] - pb[1]), (pb[0] - pa[0], pb[1] - pa[1])):
            if lattice_contains(component.natural, f):
                continue
            classes.add(reduce_mod(component.natural, f))
    return sorted(classes)


def _lattice_is_collision_free(basis: list[Vec], forbidden: list[Vec]) -> bool:
    """Check that no forbidden class representative lies in the lattice."""
    return not any(lattice_contains(basis, f) for f in forbidden)


def _candidates(limit: int) -> list[Vec]:
    """Candidate vectors with ``max(|x|, |y|) <= limit``, up to sign symmetry."""
    result = []
    for a in range(limit + 1):
        for b in range(-limit, limit + 1):
            if a == 0 and b <= 0:
                continue
            result.append((a, b))
    result.sort(key=lambda v: (max(abs(v[0]), abs(v[1])), abs(v[0]) + abs(v[1])))
    return result


def choose_periods(component: Component, forbidden: list[Vec]) -> list[Vec]:
    """Complete the natural periods to a full-rank collision-free lattice.

    For a doubly periodic component the natural lattice itself is returned:
    with that lattice, two copies share a color exactly when they are the
    same component, so no collision is possible.  Otherwise one or two
    collision-free vectors are added (thesis section 2.12).  Among all valid
    completions within the smallest sufficient search ring, one minimizing
    the determinant (= number of colors) is chosen.

    Args:
        component: The component whose lattice is being completed.
        forbidden: Forbidden classes from :func:`forbidden_classes`.

    Returns:
        Full-rank HNF basis of the coloring lattice.

    Raises:
        RuntimeError: If no collision-free completion exists within the
            search limits.
    """
    natural = component.natural
    if len(natural) == 2:
        return natural

    for limit in _SEARCH_LIMITS:
        best: tuple[int, list[Vec]] | None = None
        candidates = _candidates(limit)
        if len(natural) == 1:
            for v in candidates:
                basis = hnf_basis(natural + [v])
                if len(basis) < 2:
                    continue
                if _lattice_is_collision_free(basis, forbidden):
                    if best is None or det(basis) < best[0]:
                        best = (det(basis), basis)
        else:
            # Trivially periodic: greedily fix the first vector (any vector
            # whose multiples avoid every forbidden class), then complete.
            for v1 in candidates:
                if not _lattice_is_collision_free(hnf_basis([v1]), forbidden):
                    continue
                for v2 in candidates:
                    basis = hnf_basis([v1, v2])
                    if len(basis) < 2:
                        continue
                    if _lattice_is_collision_free(basis, forbidden):
                        if best is None or det(basis) < best[0]:
                            best = (det(basis), basis)
                if best is not None and best[0] == 1:
                    break
        if best is not None:
            return best[1]
    raise RuntimeError(
        f"No collision-free lattice found within search limit {_SEARCH_LIMITS[-1]}"
    )
