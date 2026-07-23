"""Rasterize colored, woven wallpaper regions server-side.

Produces the images the generation stage conditions on (and standalone
exports): a *color* map (flat palette fills with weave-correct crossings)
and a *lineart* map (visible ribbon rails only).  All geometry is exact:
crossing patches are shapely polygon intersections, and a rail segment is
hidden exactly where a ribbon passing over it covers it.

The weave convention matches the front end: at a crossing of pieces
``i < j`` the piece drawn on top defaults to ``j`` when ``i + j`` is even,
``i`` otherwise, with per-crossing overrides supplied as ``{"i,j,k": winner}``
where ``k`` indexes the overlap region (two pieces may cross more than once).
"""

import colorsys

from PIL import Image, ImageDraw
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from escher.coloring import ColoringResult
from escher.tile import Tile, crossing_regions

INK = (27, 36, 48)
WHITE = (255, 255, 255)


def palette_color(index: int) -> tuple[int, int, int]:
    """The front end's default palette: red, green, blue, then golden-angle."""
    defaults = [(255, 0, 0), (0, 128, 0), (0, 0, 255)]
    if index < len(defaults):
        return defaults[index]
    hue = ((150 + index * 137.508) % 360) / 360
    r, g, b = colorsys.hls_to_rgb(hue, 0.52, 0.62)
    return int(r * 255), int(g * 255), int(b * 255)


def weave_winner(i: int, j: int, k: int, weave: dict[str, int] | None) -> int:
    a, b = min(i, j), max(i, j)
    if weave and f"{a},{b},{k}" in weave:
        return weave[f"{a},{b},{k}"]
    return b if (a + b) % 2 == 0 else a


def _interior_edges(vertices: list[tuple[int, int]], grid: int) -> list[LineString]:
    """Polygon edges that are real ribbon rails (not along the tile border)."""
    edges = []
    for k in range(len(vertices)):
        a, b = vertices[k], vertices[(k + 1) % len(vertices)]
        on_border = (
            (a[0] == 0 and b[0] == 0)
            or (a[0] == grid and b[0] == grid)
            or (a[1] == 0 and b[1] == 0)
            or (a[1] == grid and b[1] == grid)
        )
        if not on_border:
            edges.append(LineString([a, b]))
    return edges


def _draw_geometry(draw, geometry, transform, color, width=None):
    """Fill polygons or stroke linestrings of any shapely geometry."""
    if geometry.is_empty:
        return
    parts = getattr(geometry, "geoms", [geometry])
    for part in parts:
        if isinstance(part, Polygon):
            draw.polygon([transform(c) for c in part.exterior.coords], fill=color)
        elif isinstance(part, LineString):
            draw.line([transform(c) for c in part.coords], fill=color, width=width)


def render_region(
    tile: Tile,
    result: ColoringResult,
    weave: dict[str, int] | None = None,
    cell: int = 256,
    tiles_x: int | None = None,
    tiles_y: int | None = None,
    mode: str = "color",
    rails: bool = True,
    palette: list[tuple[int, int, int]] | None = None,
    background: tuple[int, int, int] | None = None,
) -> Image.Image:
    """Render a window of the colored, woven wallpaper.

    Args:
        tile: The unit tile geometry.
        result: Coloring from :func:`escher.coloring.color_tile`.
        weave: Per-crossing winner overrides, keyed ``"i,j"`` with ``i < j``.
        cell: Unit tile size in pixels.
        tiles_x: Window width in unit tiles (default: the Big Tile width).
        tiles_y: Window height in unit tiles (default: the Big Tile height).
        mode: ``"color"`` for palette fills, ``"lineart"`` for black rails on
            white, ``"depth"`` for a weave depth map (white = near: crossing
            winners brightest, ribbons mid, background black).
        rails: Whether the color mode draws rails.
        palette: Optional RGB color per color class, overriding the default
            golden-angle palette.
        background: Optional background color for the color mode.

    Returns:
        The rendered image, seamlessly tileable when the window is a
        multiple of the Big Tile.
    """
    if tiles_x is None:
        tiles_x = result.big_width
    if tiles_y is None:
        tiles_y = result.big_height

    grid = tile.grid
    scale = cell / grid
    polygons = [Polygon(p) for p in tile.pieces]
    # Each crossing is one overlap region; a pair may cross more than once.
    regions = [(i, j, k, Polygon(ring)) for i, j, k, ring in crossing_regions(tile)]

    # Per piece: the overlap regions where another ribbon passes over it, so a
    # rail is hidden only inside the crossing it goes under (not everywhere the
    # two pieces meet).  The hidden area extends slightly beyond the crossing
    # (knot-diagram convention): the visible gap before the over ribbon's rail
    # makes the under strand read as dipping beneath a continuous corridor
    # instead of the crossing reading as a closed box.
    gap = grid / 48
    covered_regions: list[list[Polygon]] = [[] for _ in polygons]
    for i, j, k, region in regions:
        winner = weave_winner(i, j, k, weave)
        loser = i if winner == j else j
        covered_regions[loser].append(region.buffer(gap, join_style="mitre"))

    line_width = max(1, round(cell / 128)) if mode == "lineart" else max(
        1, round(cell / 170)
    )
    if mode == "depth":
        background = (0, 0, 0)
    elif background is None:
        background = WHITE
    image = Image.new("RGB", (tiles_x * cell, tiles_y * cell), background)
    draw = ImageDraw.Draw(image)

    for ty in range(tiles_y):
        for tx in range(tiles_x):
            def transform(c, tx=tx, ty=ty):
                return (tx * cell + c[0] * scale, ty * cell + c[1] * scale)

            def fill_of(piece: int, tx=tx, ty=ty) -> tuple[int, int, int]:
                row = result.colors[piece][ty % result.big_height]
                index = row[tx % result.big_width]
                if palette is not None and index < len(palette):
                    return palette[index]
                return palette_color(index)

            if mode in ("color", "depth"):
                ribbon = (150, 150, 150)
                near = (230, 230, 230)
                for index, polygon in enumerate(polygons):
                    fill = ribbon if mode == "depth" else fill_of(index)
                    _draw_geometry(draw, polygon, transform, fill)
                for i, j, k, region in regions:
                    winner = weave_winner(i, j, k, weave)
                    fill = near if mode == "depth" else fill_of(winner)
                    _draw_geometry(draw, region, transform, fill)

            if mode == "lineart" or (mode == "color" and rails):
                color = INK if mode == "color" else (0, 0, 0)
                for index, polygon in enumerate(polygons):
                    hidden = unary_union(covered_regions[index])
                    for edge in _interior_edges(tile.pieces[index], grid):
                        visible = (
                            edge.difference(hidden)
                            if covered_regions[index]
                            else edge
                        )
                        _draw_geometry(draw, visible, transform, color, line_width)
    return image
