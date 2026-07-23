"""Shared verification helpers for the Escher coloring tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from escher.coloring import ColoringResult
from escher.forbidden import Overlap
from escher.lattice import reduce_mod
from escher.periods import Connection


def verify_coloring(
    num_pieces: int,
    connections: list[Connection],
    overlaps: list[Overlap],
    result: ColoringResult,
    window: int = 9,
) -> None:
    """Verify the coloring guarantee on a finite wallpaper window.

    Checks, for every piece instance in a ``window x window`` block of unit
    tiles:

    1. Instances connected through period-graph connections (ground truth via
       union-find, independent of the algorithm) have equal colors.
    2. Union-find-connected instances belong to the same component copy as
       predicted by the natural-period lattice (validates natural periods).
    3. Overlapping instances of *different* component copies have different
       colors: the central guarantee of Gethner's algorithm.

    Args:
        num_pieces: Number of motif pieces.
        connections: Period-graph connections.
        overlaps: Overlapping piece pairs within a unit tile.
        result: The coloring to verify.
        window: Side length of the verification window in unit tiles.

    Raises:
        AssertionError: If any check fails.
    """
    piece_component = {}
    for comp_index, comp_result in enumerate(result.components):
        for piece in comp_result.component.pieces:
            piece_component[piece] = comp_index

    def color(piece: int, x: int, y: int) -> int:
        return result.colors[piece][y % result.big_height][x % result.big_width]

    def copy_id(piece: int, x: int, y: int) -> tuple:
        comp_index = piece_component[piece]
        comp = result.components[comp_index].component
        px, py = comp.positions[piece]
        return comp_index, reduce_mod(comp.natural, (x - px, y - py))

    # Union-find over piece instances in the window.
    parent: dict[tuple, tuple] = {}

    def find(node: tuple) -> tuple:
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(a: tuple, b: tuple) -> None:
        parent[find(a)] = find(b)

    for piece in range(num_pieces):
        for x in range(window):
            for y in range(window):
                node = (piece, x, y)
                parent[node] = node
    for i, j, (dx, dy) in connections:
        for x in range(window):
            for y in range(window):
                nx, ny = x + dx, y + dy
                if 0 <= nx < window and 0 <= ny < window:
                    union((i, x, y), (j, nx, ny))

    # Check 1 and 2: connected instances agree on color and on copy identity.
    for (piece, x, y), _ in parent.items():
        root = find((piece, x, y))
        assert color(piece, x, y) == color(*root), (
            f"Connected instances colored differently: {(piece, x, y)} vs {root}"
        )
        assert copy_id(piece, x, y) == copy_id(*root), (
            f"Connected instances in different predicted copies: "
            f"{(piece, x, y)} vs {root}"
        )

    # Check 3: overlapping distinct copies never share a color.
    for i, j in overlaps:
        for x in range(window):
            for y in range(window):
                if copy_id(i, x, y) == copy_id(j, x, y):
                    continue
                assert color(i, x, y) != color(j, x, y), (
                    f"Overlapping components share color {color(i, x, y)}: "
                    f"pieces {i}, {j} in tile ({x}, {y})"
                )
