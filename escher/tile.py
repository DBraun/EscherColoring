"""Digitizing: from motif-piece polygons to connections and overlaps.

Implements the digitizing steps of thesis sections 2.2-2.4.  A tile is a
unit square subdivided into a ``grid x grid`` lattice; motif pieces are
simple polygons whose vertices sit on integer grid points (coordinates in
``0 .. grid``).  Working in integer grid coordinates keeps the geometric
predicates robust.

* A *connection* ``(i, j, (dx, dy))`` is recorded when piece ``j`` translated
  by one tile unit in direction ``(dx, dy)`` shares at least one point with
  piece ``i`` (thesis section 2.3).  The y-axis points down, matching screen
  coordinates in the design tool; the algorithm is agnostic to orientation.
* An *overlap* ``(i, j)`` is recorded when two pieces of the same unit tile
  share at least one point (thesis section 2.4).
"""

from dataclasses import dataclass

from shapely.affinity import translate
from shapely.geometry import Polygon

from escher.forbidden import Overlap
from escher.lattice import Vec
from escher.periods import Connection

# Directions to adjacent tiles, up to complement: right, down, down-right,
# up-right.  Together with the implied complements these cover all eight
# neighbors of a unit tile.  Ogden's thesis includes the diagonal (corner)
# adjacencies; Gethner, Kirkpatrick and Pippenger (FUN 2012) define abutment
# for horizontally and vertically adjacent tiles only, so the diagonals are
# optional.
_AXIS_DIRS: list[Vec] = [(1, 0), (0, 1)]
_DIAGONAL_DIRS: list[Vec] = [(1, 1), (1, -1)]


@dataclass
class Tile:
    """An Escher unit tile.

    Attributes:
        grid: Number of subdivisions per side of the unit square.
        pieces: Motif pieces as vertex lists in integer grid coordinates.
    """

    grid: int
    pieces: list[list[Vec]]


def _polygons(tile: Tile) -> list[Polygon]:
    """Validate the tile and build shapely polygons for its pieces.

    Args:
        tile: The tile to validate.

    Returns:
        One polygon per motif piece.

    Raises:
        ValueError: If a piece is degenerate, self-intersecting, or has
            vertices outside the unit tile.
    """
    polygons = []
    for index, vertices in enumerate(tile.pieces):
        if len(vertices) < 3:
            raise ValueError(f"Piece {index} has fewer than 3 vertices")
        for x, y in vertices:
            if not (0 <= x <= tile.grid and 0 <= y <= tile.grid):
                raise ValueError(
                    f"Piece {index} vertex ({x}, {y}) lies outside the tile grid"
                )
        polygon = Polygon(vertices)
        if not polygon.is_valid or polygon.area == 0:
            raise ValueError(f"Piece {index} is not a valid simple polygon")
        polygons.append(polygon)
    return polygons


def digitize(
    tile: Tile, diagonal: bool = True
) -> tuple[list[Connection], list[Overlap]]:
    """Extract the period-graph connections and overlaps of a tile.

    Args:
        tile: The tile whose pieces are analyzed.
        diagonal: Whether corner contact between diagonally adjacent tiles
            counts as a connection (Ogden's convention).  With False, only
            horizontal and vertical abutment connects (FUN 2012 convention).

    Returns:
        ``(connections, overlaps)``: connections list one representative per
        undirected period-graph edge (complements implied); overlaps are
        pairs ``(i, j)`` with ``i < j``.
    """
    polygons = _polygons(tile)
    g = tile.grid
    n = len(polygons)
    directions = _AXIS_DIRS + (_DIAGONAL_DIRS if diagonal else [])

    # For each unordered pair and each of the four canonical directions,
    # (i, j, d) and (j, i, d) are distinct period-graph edges (e.g. a strip
    # crossing the tile connects to itself on both sides); each edge's
    # complement (j, i, -d) is implied and not stored.
    connections: list[Connection] = []
    for i in range(n):
        for j in range(i, n):
            for dx, dy in directions:
                shifted = translate(polygons[j], xoff=dx * g, yoff=dy * g)
                if shifted.intersects(polygons[i]):
                    connections.append((i, j, (dx, dy)))
                if i != j:
                    shifted = translate(polygons[i], xoff=dx * g, yoff=dy * g)
                    if shifted.intersects(polygons[j]):
                        connections.append((j, i, (dx, dy)))

    overlaps: list[Overlap] = []
    for i in range(n):
        for j in range(i + 1, n):
            if polygons[i].intersects(polygons[j]):
                overlaps.append((i, j))
    return connections, overlaps


def crossing_regions(
    tile: Tile,
) -> list[tuple[int, int, int, list[tuple[float, float]]]]:
    """Distinct overlap regions between piece pairs, for weaving.

    Two pieces can cross at more than one place (e.g. a ribbon that meets
    another ribbon twice); each such place is woven independently, so the
    front end and the server renderer key their over/under choice by region.

    Args:
        tile: The tile whose pieces are analyzed.

    Returns:
        One entry ``(i, j, k, ring)`` per connected overlap region of positive
        area: ``i < j`` are the pieces, ``k`` is the region's index within that
        pair (stable ordering), and ``ring`` is the region's exterior boundary
        as vertex ``(x, y)`` pairs in grid coordinates.
    """
    polygons = _polygons(tile)
    n = len(polygons)
    regions: list[tuple[int, int, int, list[tuple[float, float]]]] = []
    for i in range(n):
        for j in range(i + 1, n):
            intersection = polygons[i].intersection(polygons[j])
            parts = getattr(intersection, "geoms", [intersection])
            k = 0
            for part in parts:
                if not isinstance(part, Polygon) or part.area == 0:
                    continue
                ring = [
                    (round(x, 4), round(y, 4)) for x, y in part.exterior.coords[:-1]
                ]
                regions.append((i, j, k, ring))
                k += 1
    return regions
