"""Randomized property test: the coloring guarantee holds for random tiles."""

import random

from conftest import verify_coloring
from escher.coloring import color_tile
from escher.tile import Tile, digitize

GRID = 6


def _random_rectangle(rng: random.Random) -> list[tuple[int, int]]:
    x0 = rng.randint(0, GRID - 1)
    y0 = rng.randint(0, GRID - 1)
    x1 = rng.randint(x0 + 1, GRID)
    y1 = rng.randint(y0 + 1, GRID)
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def test_random_rectangle_tiles():
    for seed in range(40):
        rng = random.Random(seed)
        num_pieces = rng.randint(1, 4)
        tile = Tile(grid=GRID, pieces=[_random_rectangle(rng) for _ in range(num_pieces)])
        connections, overlaps = digitize(tile)
        result = color_tile(num_pieces, connections, overlaps)
        verify_coloring(num_pieces, connections, overlaps, result, window=8)
        assert result.palette_size >= len(result.components)
