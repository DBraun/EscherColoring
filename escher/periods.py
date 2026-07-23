"""Period graph analysis: generating sets, removed edges, natural periods.

Implements thesis sections 2.3 (period graph), 2.5 (spanning forest),
2.6 (generating set of motif pieces), 2.7 (removed edges) and 2.8
(ghost nodes / natural periods).

A *connection* is a 4-tuple ``(i, j, (dx, dy))`` meaning: motif piece ``i``
in some unit tile touches motif piece ``j`` in the adjacent unit tile that
is ``(dx, dy)`` tile-units away.  Every connection implies its complement
``(j, i, (-dx, -dy))``; only one of the two needs to be listed.
"""

from dataclasses import dataclass, field

from escher.lattice import Vec, hnf_basis

Connection = tuple[int, int, Vec]


@dataclass
class Component:
    """One connected component of the period graph.

    Attributes:
        pieces: Sorted labels of the motif pieces in this component.
        positions: Generating set: piece label -> position vector relative
            to the component's origin piece (thesis Table 2.3).
        removed_edges: Connections removed while building the spanning tree
            (thesis Table 2.4).
        natural: HNF basis of the lattice spanned by the natural periods
            (thesis section 2.8).
    """

    pieces: list[int] = field(default_factory=list)
    positions: dict[int, Vec] = field(default_factory=dict)
    removed_edges: list[Connection] = field(default_factory=list)
    natural: list[Vec] = field(default_factory=list)


def build_components(num_pieces: int, connections: list[Connection]) -> list[Component]:
    """Partition the period graph into components and compute their periods.

    Runs a depth-first search over each component, assigning every piece a
    position vector relative to the component's origin piece.  Edges that
    close a cycle are the removed edges; each yields a ghost-node difference,
    and the HNF basis of those differences is the natural-period lattice.

    Args:
        num_pieces: Number of motif pieces, labeled ``0 .. num_pieces - 1``.
        connections: Connections of the period graph (complements implied).

    Returns:
        One :class:`Component` per connected component, ordered by their
        smallest piece label.
    """
    adjacency: list[list[tuple[int, Vec, int]]] = [[] for _ in range(num_pieces)]
    for edge_id, (i, j, (dx, dy)) in enumerate(connections):
        adjacency[i].append((j, (dx, dy), edge_id))
        adjacency[j].append((i, (-dx, -dy), edge_id))

    components: list[Component] = []
    visited: dict[int, Vec] = {}
    for origin in range(num_pieces):
        if origin in visited:
            continue
        comp = Component()
        visited[origin] = (0, 0)
        members = [origin]
        used_edges: set[int] = set()
        period_diffs: list[Vec] = []
        stack = [origin]
        while stack:
            i = stack.pop()
            pos_i = visited[i]
            for j, (dx, dy), edge_id in adjacency[i]:
                if edge_id in used_edges:
                    continue
                used_edges.add(edge_id)
                ghost = (pos_i[0] + dx, pos_i[1] + dy)
                if j not in visited:
                    visited[j] = ghost
                    members.append(j)
                    stack.append(j)
                else:
                    # Removed edge: the ghost position may disagree with the
                    # spanning-tree position, revealing a natural period.
                    comp.removed_edges.append((i, j, (dx, dy)))
                    pos_j = visited[j]
                    diff = (ghost[0] - pos_j[0], ghost[1] - pos_j[1])
                    if diff != (0, 0):
                        period_diffs.append(diff)
        comp.pieces = sorted(members)
        comp.positions = {p: visited[p] for p in comp.pieces}
        comp.natural = hnf_basis(period_diffs)
        components.append(comp)
    return components
