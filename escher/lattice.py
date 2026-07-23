"""Exact integer lattice arithmetic in Z^2.

All lattices are sublattices of Z^2 represented by a Hermite-normal-form
basis (Ogden thesis, appendix A.2; Table 2.7):

* rank 0: ``[]``
* rank 1: ``[(px, py)]`` with ``py > 0``, or ``py == 0 and px > 0``
* rank 2: ``[(w, 0), (b, h)]`` with ``w > 0``, ``h > 0``, ``0 <= b < w``

The first basis vector of a rank-2 lattice lies on the x-axis, matching the
"normalized lattice" the thesis uses to locate color vectors (section 2.14).
"""

from math import gcd

Vec = tuple[int, int]


def ext_gcd(a: int, b: int) -> tuple[int, int, int]:
    """Extended Euclidean algorithm.

    Args:
        a: First integer.
        b: Second integer.

    Returns:
        A tuple ``(g, x, y)`` with ``g = gcd(a, b) >= 0`` and ``g = a*x + b*y``.
    """
    if b == 0:
        if a < 0:
            return -a, -1, 0
        return a, 1, 0
    g, x, y = ext_gcd(b, a % b)
    return g, y, x - (a // b) * y


def hnf_basis(vectors: list[Vec]) -> list[Vec]:
    """Compute the Hermite-normal-form basis of the integer span of vectors.

    Args:
        vectors: Integer 2-vectors spanning the lattice.

    Returns:
        The canonical basis in the form documented at module level.
    """
    vecs = [v for v in vectors if v != (0, 0)]
    if not vecs:
        return []

    # Combine vectors until one vector u carries the gcd of all y-components.
    u = vecs[0]
    for v in vecs[1:]:
        if v[1] == 0:
            continue
        g, s, t = ext_gcd(u[1], v[1])
        u = (s * u[0] + t * v[0], g)
    if u[1] < 0:
        u = (-u[0], -u[1])

    if u[1] == 0:
        # All vectors lie on the x-axis.
        w = 0
        for v in vecs:
            w = gcd(w, v[0])
        return [(w, 0)]

    h = u[1]
    # Eliminate the y-component of every vector; the leftovers span the
    # x-axis part of the lattice.
    w = 0
    for v in vecs:
        q = v[1] // h
        w = gcd(w, v[0] - q * u[0])
    if w == 0:
        return [u]
    return [(w, 0), (u[0] % w, h)]


def lattice_contains(basis: list[Vec], v: Vec) -> bool:
    """Test whether vector ``v`` is a member of the lattice.

    Args:
        basis: HNF basis as produced by :func:`hnf_basis`.
        v: Vector to test.

    Returns:
        True if ``v`` is an integer combination of the basis vectors.
    """
    if not basis:
        return v == (0, 0)
    if len(basis) == 1:
        px, py = basis[0]
        if py != 0:
            if v[1] % py != 0:
                return False
            s = v[1] // py
        else:
            if px == 0:
                raise RuntimeError("Rank-1 basis vector must be nonzero")
            if v[0] % px != 0:
                return False
            s = v[0] // px
        return (s * px, s * py) == v
    (w, _), (b, h) = basis
    if v[1] % h != 0:
        return False
    t = v[1] // h
    return (v[0] - t * b) % w == 0


def reduce_mod(basis: list[Vec], v: Vec) -> Vec:
    """Reduce ``v`` to a canonical representative of its coset ``v + L``.

    This is the "normalize forbidden vectors" step (thesis section 2.11)
    extended to any lattice rank.

    Args:
        basis: HNF basis of the lattice ``L``.
        v: Vector to reduce.

    Returns:
        The canonical coset representative.
    """
    if not basis:
        return v
    if len(basis) == 1:
        px, py = basis[0]
        if py != 0:
            q = v[1] // py
        else:
            q = v[0] // px
        return (v[0] - q * px, v[1] - q * py)
    (w, _), (b, h) = basis
    t = v[1] // h
    x = v[0] - t * b
    return (x % w, v[1] - t * h)


def coset_reps(basis: list[Vec]) -> list[Vec]:
    """Enumerate coset representatives of ``Z^2 / L`` for a full-rank lattice.

    These are exactly the "color vectors" of thesis section 2.14: the integer
    points of the half-open fundamental parallelogram of the normalized
    lattice.

    Args:
        basis: Full-rank (length 2) HNF basis.

    Returns:
        List of ``w * h`` representatives, one per color.
    """
    if len(basis) != 2:
        raise RuntimeError("coset_reps requires a full-rank lattice")
    (w, _), (_, h) = basis
    return [(x, y) for x in range(w) for y in range(h)]


def det(basis: list[Vec]) -> int:
    """Absolute determinant of a full-rank HNF basis (the number of colors)."""
    if len(basis) != 2:
        raise RuntimeError("det requires a full-rank lattice")
    (w, _), (_, h) = basis
    return w * h
