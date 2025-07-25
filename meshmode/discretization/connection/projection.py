from __future__ import annotations


__copyright__ = """Copyright (C) 2018 Alexandru Fikl"""

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

import numpy as np

import loopy as lp
import modepy as mp
from arraycontext import (
    NotAnArrayContainerError,
    deserialize_container,
    make_loopy_program,
    serialize_container,
)
from pytools import keyed_memoize_in, keyed_memoize_method, memoize_in

from meshmode.discretization import InterpolatoryElementGroupBase
from meshmode.discretization.connection.chained import ChainedDiscretizationConnection
from meshmode.discretization.connection.direct import (
    DirectDiscretizationConnection,
    DiscretizationConnection,
)
from meshmode.transform_metadata import FirstAxisIsElementsTag


class L2ProjectionInverseDiscretizationConnection(DiscretizationConnection):
    """Creates an inverse :class:`DiscretizationConnection` from an existing
    connection to allow transporting from the original connection's
    *to_discr* to *from_discr*.

    .. attribute:: from_discr
    .. attribute:: to_discr
    .. attribute:: is_surjective

    .. attribute:: conn
    .. automethod:: __call__

    """

    def __new__(cls, connections, is_surjective=False):
        if isinstance(connections, DirectDiscretizationConnection):
            return DiscretizationConnection.__new__(cls)
        elif isinstance(connections, ChainedDiscretizationConnection):
            if len(connections.connections) == 0:
                return connections

            return cls(connections.connections, is_surjective=is_surjective)
        else:
            conns = []
            for cnx in reversed(connections):
                conns.append(cls(cnx, is_surjective=is_surjective))

            return ChainedDiscretizationConnection(conns)

    def __init__(self, conn, is_surjective=False):
        if conn.from_discr.dim != conn.to_discr.dim:
            raise RuntimeError("cannot transport from face to element")

        if not all(g.is_orthonormal_basis() for g in conn.to_discr.groups):
            raise RuntimeError("`to_discr` must have an orthonormal basis")

        self.conn = conn
        super().__init__(
                from_discr=self.conn.to_discr,
                to_discr=self.conn.from_discr,
                is_surjective=is_surjective)

    @keyed_memoize_method(key=lambda actx: ())
    def _batch_weights(self, actx):
        """Computes scaled quadrature weights for each interpolation batch in
        :attr:`conn`. The quadrature weights can be used to integrate over
        child elements in the domain of the parent element, by a change of
        variables.

        :return: a dictionary with keys ``(group_id, batch_id)``.
        """

        from functools import reduce
        from operator import xor

        from pymbolic.geometric_algebra import MultiVector

        def det(v):
            nnodes = v[0].shape[0]
            det_v = np.empty(nnodes)

            for i in range(nnodes):
                outer_product = reduce(xor, [MultiVector(x[i, :].T) for x in v])
                det_v[i] = abs((outer_product.I | outer_product).as_scalar())

            return det_v

        weights = {}
        jac = np.empty(self.to_discr.dim, dtype=object)

        for igrp, grp in enumerate(self.to_discr.groups):
            if not isinstance(grp, InterpolatoryElementGroupBase):
                raise ValueError("element group must be interpolatory")

            matrices = mp.diff_matrices(grp.basis_obj(), grp.unit_nodes)

            for ibatch, batch in enumerate(self.conn.groups[igrp].batches):
                for iaxis in range(grp.dim):
                    jac[iaxis] = matrices[iaxis] @ batch.result_unit_nodes.T

                weights[igrp, ibatch] = actx.freeze(actx.from_numpy(
                    det(jac) * grp.quadrature_rule().weights))

        return weights

    def __call__(self, ary):
        """
        :arg ary: a :class:`~meshmode.dof_array.DOFArray`, or an
            :class:`arraycontext.ArrayContainer` of them, containing nodal
            coefficient data on :attr:`from_discr`.
        """

        # {{{ recurse into array containers

        from meshmode.dof_array import DOFArray
        if not isinstance(ary, DOFArray):
            try:
                iterable = serialize_container(ary)
            except NotAnArrayContainerError:
                pass
            else:
                return deserialize_container(ary, [
                    (key, self(subary)) for key, subary in iterable
                    ])

        # }}}

        if __debug__:
            from meshmode.dof_array import check_dofarray_against_discr
            check_dofarray_against_discr(self.from_discr, ary)

        actx = ary.array_context

        @memoize_in(actx, (L2ProjectionInverseDiscretizationConnection,
            "conn_projection_knl"))
        def kproj():
            t_unit = make_loopy_program(
                [
                    "{[iel_init]: 0 <= iel_init < n_to_elements}",
                    "{[idof_init]: 0 <= idof_init < n_to_nodes}",
                    "{[iel]: 0 <= iel < nelements}",
                    "{[i_quad]: 0 <= i_quad < n_to_nodes}",
                    "{[ibasis]: 0 <= ibasis < n_to_nodes}"
                ],
                """
                    result[iel_init, idof_init] = 0 {id=init}
                    ... gbarrier {id=barrier, dep=init}
                    result[to_element_indices[iel], ibasis] =               \
                        result[to_element_indices[iel], ibasis] +           \
                        sum(i_quad, ary[from_element_indices[iel], i_quad]  \
                                    * basis_tabulation[ibasis, i_quad]      \
                                    * weights[i_quad]) {dep=barrier}
                """,
                [
                    lp.GlobalArg("ary", None,
                                 shape=("n_from_elements", "n_from_nodes")),
                    lp.GlobalArg("result", None,
                                 shape=("n_to_elements", "n_to_nodes"),
                                 is_input=False),
                    lp.GlobalArg("basis_tabulation", None,
                                 shape=("n_to_nodes", "n_to_nodes")),
                    lp.GlobalArg("weights", None,
                                 shape="n_from_nodes"),
                    lp.ValueArg("n_from_elements", np.int32),
                    lp.ValueArg("n_from_nodes", np.int32),
                    lp.ValueArg("n_to_elements", np.int32),
                    lp.ValueArg("n_to_nodes", np.int32),
                    "..."
                ],
                name="conn_projection_knl"
            )
            from meshmode.transform_metadata import (
                ConcurrentDOFInameTag,
                ConcurrentElementInameTag,
            )
            return lp.tag_inames(t_unit, {
                    "iel_init": ConcurrentElementInameTag(),
                    "idof_init": ConcurrentDOFInameTag(),
                    "iel": ConcurrentElementInameTag(),
                    "ibasis": ConcurrentDOFInameTag(),
                    })

        # compute weights on each refinement of the reference element
        weights = self._batch_weights(actx)

        # perform dot product (on reference element) to get basis coefficients
        c_group_data = []
        for igrp, cgrp in enumerate(self.conn.groups):
            c_batch_data = []
            for ibatch, batch in enumerate(cgrp.batches):
                sgrp = self.from_discr.groups[batch.from_group_index]

                # Generate the basis tabulation matrix
                tabulations = []
                for basis_fn in sgrp.basis_obj().functions:
                    tabulations.append(basis_fn(batch.result_unit_nodes).flatten())
                tabulations = actx.from_numpy(np.asarray(tabulations))

                # NOTE: batch.*_element_indices are reversed here because
                # they are from the original forward connection, but
                # we are going in reverse here. a bit confusing, but
                # saves on recreating the connection groups and batches.
                c_batch_data.append(
                    actx.call_loopy(
                        kproj(),
                        ary=ary[batch.from_group_index],
                        basis_tabulation=tabulations,
                        weights=weights[igrp, ibatch],
                        from_element_indices=batch.to_element_indices,
                        to_element_indices=batch.from_element_indices,
                        n_to_elements=self.to_discr.groups[igrp].nelements,
                        n_to_nodes=self.to_discr.groups[igrp].nunit_dofs,
                    )["result"]
                )

            c_group_data.append(sum(c_batch_data))
        coefficients = DOFArray(actx, data=tuple(c_group_data))

        @keyed_memoize_in(
            actx, (L2ProjectionInverseDiscretizationConnection,
                   "vandermonde_matrix"),
            lambda grp: grp.discretization_key()
        )
        def vandermonde_matrix(grp):
            from modepy import vandermonde
            vdm = vandermonde(grp.basis_obj().functions,
                              grp.unit_nodes)
            return actx.from_numpy(vdm)

        return DOFArray(
            actx,
            data=tuple(
                actx.einsum("ij,ej->ei",
                            vandermonde_matrix(grp),
                            c_i,
                            arg_names=("vdm", "coeffs"),
                            tagged=(FirstAxisIsElementsTag(),))
                for grp, c_i in zip(self.to_discr.groups, coefficients, strict=True)
            )
        )


# vim: foldmethod=marker
