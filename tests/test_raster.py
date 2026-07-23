"""Tests for the server-side conditioning rasterizer."""

from escher.coloring import color_tile
from escher.raster import palette_color, render_region, weave_winner
from escher.tile import Tile, digitize
from test_ogden_tile import OGDEN_PIECES


def _ogden():
    tile = Tile(grid=24, pieces=[list(map(tuple, p)) for p in OGDEN_PIECES])
    connections, overlaps = digitize(tile)
    return tile, color_tile(9, connections, overlaps)


def test_color_render_is_periodic_with_big_tile():
    tile, result = _ogden()
    cell = 48
    image = render_region(tile, result, cell=cell, tiles_x=2, tiles_y=6, mode="color")
    assert image.size == (2 * cell, 6 * cell)
    # The Big Tile is 1x3: pixels one Big Tile apart are identical.
    for x, y in [(30, 40), (20, 100), (40, 130)]:
        assert image.getpixel((x, y)) == image.getpixel((x + cell, y))
        assert image.getpixel((x, y)) == image.getpixel((x, y + 3 * cell))


def test_weave_winner_shows_at_crossing():
    tile, result = _ogden()
    cell = 96
    # Crossing of m2 (piece 1) and m5 (piece 4) is a single region (k=0) with
    # interior point ~(6.3, 13.6).
    x, y = int(6.5 / 24 * cell), int(14.0 / 24 * cell)
    winner = weave_winner(1, 4, 0, None)
    color_index = result.colors[winner][0][0]
    image = render_region(tile, result, cell=cell, tiles_x=1, tiles_y=1,
                          mode="color", rails=False)
    assert image.getpixel((x, y)) == palette_color(color_index)
    # Flipping the crossing flips the visible color.
    flipped = 1 + 4 - winner
    override = {"1,4,0": flipped}
    image2 = render_region(tile, result, weave=override, cell=cell,
                           tiles_x=1, tiles_y=1, mode="color", rails=False)
    assert image2.getpixel((x, y)) == palette_color(result.colors[flipped][0][0])


def test_lineart_is_black_on_white():
    tile, result = _ogden()
    image = render_region(tile, result, cell=64, tiles_x=1, tiles_y=3,
                          mode="lineart")
    colors = {pixel for _, pixel in image.getcolors(maxcolors=1024)}
    assert (255, 255, 255) in colors
    assert (0, 0, 0) in colors
    assert colors <= {(0, 0, 0), (255, 255, 255)}
