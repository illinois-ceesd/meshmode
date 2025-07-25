from __future__ import annotations


__copyright__ = "Copyright (C) 2020 Andreas Kloeckner"

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import logging
from functools import partial

import pytest

from arraycontext import ArrayContextFactory, pytest_generate_tests_for_array_contexts

import meshmode.mesh.generation as mgen
from meshmode import _acf  # noqa: F401
from meshmode.array_context import PytestPyOpenCLArrayContextFactory
from meshmode.discretization import Discretization
from meshmode.discretization.connection import FACE_RESTR_ALL
from meshmode.discretization.poly_element import (
    LegendreGaussLobattoTensorProductGroupFactory,
    PolynomialEquidistantSimplexGroupFactory,
    PolynomialRecursiveNodesGroupFactory,
    PolynomialWarpAndBlend2DRestrictingGroupFactory,
    PolynomialWarpAndBlend3DRestrictingGroupFactory,
)
from meshmode.mesh import SimplexElementGroup, TensorProductElementGroup


logger = logging.getLogger(__name__)
pytest_generate_tests = pytest_generate_tests_for_array_contexts(
        [PytestPyOpenCLArrayContextFactory])


@pytest.mark.parametrize("group_factory", [
        "warp_and_blend",
        PolynomialEquidistantSimplexGroupFactory,
        LegendreGaussLobattoTensorProductGroupFactory,
        partial(PolynomialRecursiveNodesGroupFactory, family="lgl"),
        ])
@pytest.mark.parametrize("dim", [2, 3])
@pytest.mark.parametrize("order", [1, 2, 3, 4, 5])
def test_bdry_restriction_is_permutation(
            actx_factory: ArrayContextFactory,
            group_factory,
            dim,
            order):
    """Check that restriction to the boundary and opposite-face swap
    for the element groups, orders and dimensions above is actually just
    indirect access.
    """
    actx = actx_factory()

    if group_factory == "warp_and_blend":
        group_factory = {
                2: PolynomialWarpAndBlend2DRestrictingGroupFactory,
                3: PolynomialWarpAndBlend3DRestrictingGroupFactory,
                }[dim]

    if group_factory is LegendreGaussLobattoTensorProductGroupFactory:
        group_cls = TensorProductElementGroup
    else:
        group_cls = SimplexElementGroup

    mesh = mgen.generate_warped_rect_mesh(dim, order=order, nelements_side=5,
            group_cls=group_cls)

    vol_discr = Discretization(actx, mesh, group_factory(order))
    from meshmode.discretization.connection import (
        make_face_restriction,
        make_opposite_face_connection,
    )
    bdry_connection = make_face_restriction(
            actx, vol_discr, group_factory(order),
            FACE_RESTR_ALL)

    assert bdry_connection.is_permutation()

    opp_face = make_opposite_face_connection(actx, bdry_connection)
    assert opp_face.is_permutation()

    bdry_connection_upsample = make_face_restriction(
            actx, vol_discr, group_factory(order+1),
            FACE_RESTR_ALL)
    assert not bdry_connection_upsample.is_permutation()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        exec(sys.argv[1])
    else:
        from pytest import main
        main([__file__])

# vim: fdm=marker
