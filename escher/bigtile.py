"""Big Tile size and color assignment.

Implements thesis sections 2.13 (compute Big Tile size), 2.14 (locate color
vectors) and 2.15 (assign colors to lattice points).

Because the coloring lattice basis is kept in Hermite normal form
``[(w, 0), (b, h)]``, the color vectors are simply the integer points of the
half-open fundamental parallelogram ``{(x, y): 0 <= x < w, 0 <= y < h}`` and
color assignment is exact coset reduction: the piece ``i`` instance in unit
tile ``t`` belongs to the component copy with origin ``t - alpha_i``, and
the copy's color is its origin's coset modulo the lattice.
"""

from math import gcd

from escher.lattice import Vec, coset_reps, det, reduce_mod
from escher.periods import Component


def big_tile_size(basis: list[Vec]) -> tuple[int, int]:
    """Width and height of the Big Tile for a full-rank lattice (eq. 2.21).

    The Big Tile is the smallest ``width x height`` block of unit tiles whose
    coloring repeats: ``(width, 0)`` and ``(0, height)`` are the minimal
    axis-aligned lattice vectors.

    Args:
        basis: Full-rank HNF basis ``[(w, 0), (b, h)]``.

    Returns:
        ``(width, height)`` in unit tiles.
    """
    (w, _), (b, h) = basis
    return w, (w * h) // gcd(w, b)


def assign_colors(
    component: Component,
    basis: list[Vec],
    width: int,
    height: int,
) -> dict[int, list[list[int]]]:
    """Assign a color index to every piece at every Big Tile location.

    Args:
        component: Component with generating-set positions.
        basis: Full-rank HNF basis of the coloring lattice.
        width: Big Tile width in unit tiles.
        height: Big Tile height in unit tiles.

    Returns:
        Mapping ``piece -> grid`` where ``grid[b][a]`` is the color index
        (``0 .. det - 1``, local to this component) of the piece in the unit
        tile at Big Tile location ``(a, b)``.
    """
    reps = coset_reps(basis)
    rep_index = {rep: k for k, rep in enumerate(reps)}
    colors: dict[int, list[list[int]]] = {}
    for piece, (px, py) in component.positions.items():
        grid = []
        for b in range(height):
            row = []
            for a in range(width):
                origin = (a - px, b - py)
                row.append(rep_index[reduce_mod(basis, origin)])
            grid.append(row)
        colors[piece] = grid
    return colors


def num_colors(basis: list[Vec]) -> int:
    """Number of colors used by the lattice (its determinant)."""
    return det(basis)
