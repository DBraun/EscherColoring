"""End-to-end test on the geometric transcription of Ogden's Figure 2.1 tile.

The tile is drawn on a 24-grid (y down; the thesis y-axis points up, so a
thesis connection ``[i, j, x, y]`` corresponds to ``(i-1, j-1, (x, -y))``
here).  Digitizing the polygons must reproduce thesis Table 2.1 exactly, and
the coloring must match the thesis: natural period lattice spanned by
(1, 3), coloring lattice {(1,0), (0,3)}, Big Tile 1x3, three colors.

The transcription has one overlap beyond thesis Table 2.2: (m5, m6).  Its
forbidden class equals that of an existing overlap modulo the natural
lattice, so the coloring is unchanged; the thesis figure shows those two
ribbons in contact as well.
"""

from conftest import verify_coloring
from escher.coloring import color_tile
from escher.tile import Tile, digitize

OGDEN_PIECES = [
    [(6, 0), (9, 0), (13, 4), (21, 0), (24, 0), (24, 2), (14, 7)],
    [(0, 0), (3, 0), (7, 12), (13, 24), (10, 24), (4, 12), (0, 2)],
    [(10, 0), (13, 0), (0, 7), (0, 5)],
    [(24, 5), (24, 7), (18, 12), (24, 16), (24, 19), (15, 13)],
    [(0, 16), (12, 9), (19, 24), (16, 24), (11, 12), (0, 19)],
    [(16, 0), (19, 0), (24, 10), (24, 12), (9, 24), (6, 24), (19, 12)],
    [(0, 10), (3, 11), (0, 12)],
    [(0, 21), (0, 24), (3, 24)],
    [(21, 24), (24, 21), (24, 24)],
]

THESIS_CONNECTIONS = [
    (1, 2, 1, 0), (1, 6, 0, 1), (1, 8, 1, 1), (1, 9, 0, 1),
    (2, 3, 0, -1), (2, 8, 0, 1), (2, 9, -1, 1), (3, 4, -1, 0),
    (4, 5, 1, 0), (5, 6, 0, -1), (6, 7, 1, 0), (8, 9, -1, 0),
]

THESIS_OVERLAPS = {(0, 2), (0, 5), (1, 2), (1, 4), (1, 5), (3, 5)}


def _canon(i, j, dx, dy):
    if (dx, dy) in [(1, 0), (0, 1), (1, 1), (1, -1)]:
        return (i, j, dx, dy)
    return (j, i, -dx, -dy)


def test_digitization_matches_thesis_table_2_1():
    connections, overlaps = digitize(Tile(grid=24, pieces=OGDEN_PIECES))
    expected = {
        _canon(i - 1, j - 1, dx, -dy) for i, j, dx, dy in THESIS_CONNECTIONS
    }
    got = {_canon(i, j, d[0], d[1]) for i, j, d in connections}
    assert got == expected
    assert THESIS_OVERLAPS <= set(overlaps)
    assert set(overlaps) - THESIS_OVERLAPS <= {(4, 5)}


def test_coloring_matches_thesis():
    connections, overlaps = digitize(Tile(grid=24, pieces=OGDEN_PIECES))
    result = color_tile(9, connections, overlaps)
    assert len(result.components) == 1
    comp = result.components[0]
    assert comp.component.natural == [(1, 3)]
    assert comp.basis == [(1, 0), (0, 3)]
    assert (comp.width, comp.height) == (1, 3)
    assert result.palette_size == 3
    verify_coloring(9, connections, overlaps, result, window=9)
