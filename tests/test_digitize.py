"""Tests for the polygon digitizer on hand-checkable tiles."""

import pytest

from conftest import verify_coloring
from escher.coloring import color_tile
from escher.tile import Tile, digitize


def test_horizontal_strip_self_connects():
    # A strip crossing the whole tile connects to itself left-to-right.
    tile = Tile(grid=6, pieces=[[(0, 2), (6, 2), (6, 4), (0, 4)]])
    connections, overlaps = digitize(tile)
    assert (0, 0, (1, 0)) in connections
    assert all(d == (1, 0) for _, _, d in connections)
    assert overlaps == []
    result = color_tile(1, connections, overlaps)
    # Natural period (1, 0); one color suffices as nothing overlaps.
    assert result.components[0].component.natural == [(1, 0)]
    assert result.palette_size == 1
    verify_coloring(1, connections, overlaps, result)


def test_crossing_strips_two_components_two_colors():
    # A horizontal and a vertical strip overlap in the middle; they are
    # different components, so they get disjoint palettes (one color each).
    tile = Tile(
        grid=6,
        pieces=[
            [(0, 2), (6, 2), (6, 4), (0, 4)],
            [(2, 0), (4, 0), (4, 6), (2, 6)],
        ],
    )
    connections, overlaps = digitize(tile)
    assert (0, 0, (1, 0)) in connections
    assert (1, 1, (0, 1)) in connections
    assert overlaps == [(0, 1)]
    result = color_tile(2, connections, overlaps)
    assert len(result.components) == 2
    assert result.palette_size == 2
    verify_coloring(2, connections, overlaps, result)


def test_diagonal_touch_at_corner():
    # A triangle at the top-left corner and one at the bottom-right corner
    # meet at tile corners diagonally.
    tile = Tile(
        grid=6,
        pieces=[
            [(0, 0), (2, 0), (0, 2)],
            [(6, 6), (4, 6), (6, 4)],
        ],
    )
    connections, overlaps = digitize(tile)
    # Piece 1's corner (6, 6) is corner (0, 0) of the tile diagonally
    # down-right; piece 0 sits there.
    assert (1, 0, (1, 1)) in connections
    assert overlaps == []
    result = color_tile(2, connections, overlaps)
    verify_coloring(2, connections, overlaps, result)


def test_overlapping_self_periodic_strips_need_colors():
    # Two full-width strips that overlap each other: same component via no
    # connection between them? They do not touch across tiles, so they are
    # separate components; each is singly periodic and they overlap, but
    # disjoint palettes keep them apart.
    tile = Tile(
        grid=6,
        pieces=[
            [(0, 1), (6, 1), (6, 3), (0, 3)],
            [(0, 2), (6, 2), (6, 5), (0, 5)],
        ],
    )
    connections, overlaps = digitize(tile)
    assert overlaps == [(0, 1)]
    result = color_tile(2, connections, overlaps)
    verify_coloring(2, connections, overlaps, result)


def test_diagonal_toggle():
    # Corner-touching triangles connect under Ogden's convention but not
    # under the FUN 2012 (horizontal/vertical only) convention.
    tile = Tile(
        grid=6,
        pieces=[
            [(0, 0), (2, 0), (0, 2)],
            [(6, 6), (4, 6), (6, 4)],
        ],
    )
    with_diagonal, _ = digitize(tile, diagonal=True)
    without_diagonal, _ = digitize(tile, diagonal=False)
    assert (1, 0, (1, 1)) in with_diagonal
    assert without_diagonal == []


def test_rejects_degenerate_piece():
    tile = Tile(grid=6, pieces=[[(0, 0), (1, 0)]])
    with pytest.raises(ValueError, match="fewer than 3 vertices"):
        digitize(tile)


def test_rejects_out_of_bounds_piece():
    tile = Tile(grid=6, pieces=[[(0, 0), (7, 0), (0, 2)]])
    with pytest.raises(ValueError, match="outside the tile grid"):
        digitize(tile)


def test_rejects_self_intersecting_piece():
    tile = Tile(grid=6, pieces=[[(0, 0), (2, 2), (2, 0), (0, 2)]])
    with pytest.raises(ValueError, match="not a valid simple polygon"):
        digitize(tile)
