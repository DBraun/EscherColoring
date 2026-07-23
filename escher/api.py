"""Framework-independent entry point for the coloring pipeline.

Both the FastAPI server (`server/main.py`) and the in-browser Pyodide build
call :func:`color_response`, so a tile drawn in the demo produces the same
`/api/color` payload whether the algorithm runs on a server or in the browser.
"""

from escher.coloring import color_tile
from escher.tile import Tile, crossing_regions, digitize


def color_response(
    grid: int, pieces: list[list[tuple[int, int]]], diagonal: bool = True
) -> dict:
    """Digitize a drawn tile and compute its Big Tile coloring.

    Args:
        grid: Subdivisions per unit-tile side.
        pieces: Motif pieces as vertex lists in grid coordinates.
        diagonal: Count corner contact between diagonal tiles as a connection.

    Returns:
        The coloring payload: connections, overlaps, per-component period and
        color data, the Big Tile dimensions, palette size, and the color grid.

    Raises:
        ValueError: If the tile geometry is invalid (propagated from
            :func:`escher.tile.digitize`).
    """
    tile = Tile(grid=grid, pieces=[list(map(tuple, p)) for p in pieces])
    connections, overlaps = digitize(tile, diagonal=diagonal)
    result = color_tile(len(tile.pieces), connections, overlaps)
    return {
        "connections": [[i, j, d[0], d[1]] for i, j, d in connections],
        "overlaps": [[i, j] for i, j in overlaps],
        "crossings": [
            {"i": i, "j": j, "k": k, "poly": [list(v) for v in ring]}
            for i, j, k, ring in crossing_regions(tile)
        ],
        "components": [
            {
                "pieces": r.component.pieces,
                "positions": {
                    str(p): list(v) for p, v in r.component.positions.items()
                },
                "natural": [list(v) for v in r.component.natural],
                "forbidden": [list(v) for v in r.forbidden],
                "basis": [list(v) for v in r.basis],
                "width": r.width,
                "height": r.height,
                "colors": r.colors,
                "colorOffset": r.color_offset,
            }
            for r in result.components
        ],
        "bigWidth": result.big_width,
        "bigHeight": result.big_height,
        "paletteSize": result.palette_size,
        "colors": {str(piece): grid for piece, grid in result.colors.items()},
    }
