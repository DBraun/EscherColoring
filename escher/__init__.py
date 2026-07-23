"""Automatic Escher tiling and coloring.

Implementation of Ellen Gethner's Escher-tile coloring algorithm following
the blueprint in Stephen C. Ogden's M.S. thesis, "Automating Escher Tiling
and Coloring: An Implementation" (University of Colorado Denver, 2004).
"""

from escher.coloring import ColoringResult, color_tile
from escher.tile import Tile, digitize

__all__ = ["ColoringResult", "color_tile", "Tile", "digitize"]
