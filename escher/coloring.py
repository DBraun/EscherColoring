"""Top-level Escher tile coloring pipeline (thesis section 2.1).

Combines the per-component machinery into a single call: build the period
graph components, compute natural periods, forbidden vectors, collision-free
lattices, per-component Big Tiles, and merge everything into one combined
Big Tile with a disjoint palette per component (thesis section 2.16).
"""

from dataclasses import dataclass, field
from math import lcm

from escher.bigtile import assign_colors, big_tile_size, num_colors
from escher.forbidden import Overlap, choose_periods, forbidden_classes
from escher.lattice import Vec
from escher.periods import Component, Connection, build_components


@dataclass
class ComponentResult:
    """Coloring results for one connected component."""

    component: Component
    forbidden: list[Vec]
    basis: list[Vec]
    width: int
    height: int
    colors: int
    color_offset: int
    assignment: dict[int, list[list[int]]] = field(default_factory=dict)


@dataclass
class ColoringResult:
    """Complete coloring of an Escher tile.

    Attributes:
        components: Per-component results.
        big_width: Combined Big Tile width (lcm of component widths).
        big_height: Combined Big Tile height (lcm of component heights).
        palette_size: Total number of colors across all components.
        colors: Mapping ``piece -> grid`` where ``grid[b][a]`` is the global
            color index of the piece in unit tile ``(a, b)`` of the combined
            Big Tile.  The wallpaper coloring of the piece in unit tile
            ``(x, y)`` is ``grid[y % big_height][x % big_width]``.
    """

    components: list[ComponentResult]
    big_width: int
    big_height: int
    palette_size: int
    colors: dict[int, list[list[int]]]


def color_tile(
    num_pieces: int,
    connections: list[Connection],
    overlaps: list[Overlap],
) -> ColoringResult:
    """Color an Escher tile given its digitized structure.

    Args:
        num_pieces: Number of motif pieces, labeled ``0 .. num_pieces - 1``.
        connections: Period-graph connections ``(i, j, (dx, dy))``.
        overlaps: Overlapping piece pairs ``(i, j)`` within the unit tile.

    Returns:
        The full coloring, with the guarantee that no two overlapping
        wallpaper components receive the same color.
    """
    components = build_components(num_pieces, connections)
    results: list[ComponentResult] = []
    offset = 0
    for comp in components:
        forbidden = forbidden_classes(comp, overlaps)
        basis = choose_periods(comp, forbidden)
        width, height = big_tile_size(basis)
        colors = num_colors(basis)
        assignment = assign_colors(comp, basis, width, height)
        results.append(
            ComponentResult(
                component=comp,
                forbidden=forbidden,
                basis=basis,
                width=width,
                height=height,
                colors=colors,
                color_offset=offset,
                assignment=assignment,
            )
        )
        offset += colors

    big_width = lcm(*(r.width for r in results)) if results else 1
    big_height = lcm(*(r.height for r in results)) if results else 1

    merged: dict[int, list[list[int]]] = {}
    for r in results:
        for piece, grid in r.assignment.items():
            merged[piece] = [
                [
                    grid[b % r.height][a % r.width] + r.color_offset
                    for a in range(big_width)
                ]
                for b in range(big_height)
            ]

    return ColoringResult(
        components=results,
        big_width=big_width,
        big_height=big_height,
        palette_size=offset,
        colors=merged,
    )
