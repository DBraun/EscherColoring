"""Unit tests for exact integer lattice arithmetic."""

from escher.lattice import (
    coset_reps,
    det,
    ext_gcd,
    hnf_basis,
    lattice_contains,
    reduce_mod,
)


def test_ext_gcd_identity():
    for a, b in [(12, 18), (-12, 18), (0, 5), (5, 0), (0, 0), (7, -3)]:
        g, x, y = ext_gcd(a, b)
        assert g >= 0
        assert a * x + b * y == g


def test_hnf_rank0():
    assert hnf_basis([]) == []
    assert hnf_basis([(0, 0)]) == []


def test_hnf_rank1():
    assert hnf_basis([(-1, 3)]) == [(-1, 3)]
    assert hnf_basis([(2, 0)]) == [(2, 0)]
    assert hnf_basis([(0, -4)]) == [(0, 4)]
    assert hnf_basis([(2, 4), (3, 6)]) == [(1, 2)]


def test_hnf_rank2_thesis_example():
    # Thesis eq. 2.8/2.9: natural period (-1, 3) plus collision-free (1, 0).
    assert hnf_basis([(-1, 3), (1, 0)]) == [(1, 0), (0, 3)]


def test_hnf_rank2_general():
    basis = hnf_basis([(2, 1), (0, 3)])
    (w, z), (b, h) = basis
    assert z == 0 and w > 0 and h > 0 and 0 <= b < w
    for v in [(2, 1), (0, 3)]:
        assert lattice_contains(basis, v)
    assert det(basis) == 6


def test_lattice_contains_rank1():
    basis = [(-1, 3)]
    assert lattice_contains(basis, (0, 0))
    assert lattice_contains(basis, (-2, 6))
    assert lattice_contains(basis, (1, -3))
    assert not lattice_contains(basis, (1, 3))
    assert not lattice_contains(basis, (0, 1))


def test_reduce_mod_is_canonical():
    basis = hnf_basis([(-1, 3), (1, 0)])
    for v in [(5, 7), (-4, -2), (0, 0), (13, -9)]:
        rep = reduce_mod(basis, v)
        assert lattice_contains(basis, (v[0] - rep[0], v[1] - rep[1]))
        assert rep in coset_reps(basis)
    assert len(coset_reps(basis)) == det(basis) == 3
