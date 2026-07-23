"""End-to-end test on the worked example of the Ogden thesis.

The tile of thesis Figure 2.1 has nine motif pieces whose connections
(Table 2.1) and overlaps (Table 2.2) are transcribed here 0-based.  Expected
results from the thesis: one connected component, natural period (-1, 3)
(section 2.8), forbidden vector classes {(1,-2), (0,1), (1,-1), (0,2)}
(Table 2.5), coloring lattice HNF {(1,0), (0,3)} (eq. 2.9), Big Tile size
1 x 3 (section 2.13), and 3 colors (Table 2.6).
"""

from conftest import verify_coloring
from escher.coloring import color_tile
from escher.lattice import lattice_contains, reduce_mod
from escher.periods import build_components

CONNECTIONS = [
    (0, 1, (1, 0)),
    (0, 5, (0, 1)),
    (0, 7, (1, 1)),
    (0, 8, (0, 1)),
    (1, 2, (0, -1)),
    (1, 7, (0, 1)),
    (1, 8, (-1, 1)),
    (2, 3, (-1, 0)),
    (3, 4, (1, 0)),
    (4, 5, (0, -1)),
    (5, 6, (1, 0)),
    (7, 8, (-1, 0)),
]

OVERLAPS = [(0, 2), (0, 5), (1, 2), (1, 4), (1, 5), (3, 5)]

NUM_PIECES = 9


def test_single_component_and_natural_period():
    components = build_components(NUM_PIECES, CONNECTIONS)
    assert len(components) == 1
    comp = components[0]
    assert comp.pieces == list(range(NUM_PIECES))
    # The natural-period lattice is spanned by (-1, 3) (thesis section 2.8).
    assert comp.natural == [(-1, 3)]


def test_generating_set_is_consistent():
    comp = build_components(NUM_PIECES, CONNECTIONS)[0]
    assert comp.positions[0] == (0, 0)
    # Positions are spanning-tree dependent, but every connection must be
    # satisfied modulo the natural-period lattice.
    for i, j, (dx, dy) in CONNECTIONS:
        px, py = comp.positions[i]
        qx, qy = comp.positions[j]
        residue = (px + dx - qx, py + dy - qy)
        assert lattice_contains(comp.natural, residue), (
            f"Connection {(i, j, (dx, dy))} violated: residue {residue}"
        )


def test_forbidden_classes_match_table_2_5():
    result = color_tile(NUM_PIECES, CONNECTIONS, OVERLAPS)
    comp_result = result.components[0]
    natural = comp_result.component.natural
    # Table 2.5 lists one representative per overlap pair; the implementation
    # keeps both signs.  Compare as classes modulo the natural lattice.
    thesis = [(1, -2), (0, 1), (1, -1), (0, 2)]
    expected = {reduce_mod(natural, f) for f in thesis}
    expected |= {reduce_mod(natural, (-f[0], -f[1])) for f in thesis}
    assert set(comp_result.forbidden) == expected


def test_lattice_big_tile_and_palette():
    result = color_tile(NUM_PIECES, CONNECTIONS, OVERLAPS)
    assert len(result.components) == 1
    comp_result = result.components[0]
    assert comp_result.basis == [(1, 0), (0, 3)]
    assert (comp_result.width, comp_result.height) == (1, 3)
    assert comp_result.colors == 3
    assert result.palette_size == 3
    assert (result.big_width, result.big_height) == (1, 3)


def test_coloring_guarantee_on_window():
    result = color_tile(NUM_PIECES, CONNECTIONS, OVERLAPS)
    verify_coloring(NUM_PIECES, CONNECTIONS, OVERLAPS, result, window=9)
