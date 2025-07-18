from __future__ import annotations


__copyright__ = "Copyright (C) 2014 Andreas Kloeckner"

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

import numpy as np
import numpy.linalg as la

from meshmode.discretization.connection.direct import InterpolationBatch


logger = logging.getLogger(__name__)


def freeze_from_numpy(actx, array):
    return actx.freeze(actx.from_numpy(array))


def thaw_to_numpy(actx, array):
    return actx.to_numpy(actx.thaw(array))


# {{{ _make_cross_face_batches

def _make_cross_face_batches(actx,
        tgt_bdry_discr, src_bdry_discr,
        i_tgt_grp, i_src_grp,
        tgt_bdry_element_indices, src_bdry_element_indices,
        tgt_aff_map=None, src_aff_map=None):

    if tgt_bdry_discr.dim == 0:
        return [InterpolationBatch(
            from_group_index=i_src_grp,
            from_element_indices=freeze_from_numpy(actx, src_bdry_element_indices),
            to_element_indices=freeze_from_numpy(actx, tgt_bdry_element_indices),
            result_unit_nodes=src_bdry_discr.groups[i_src_grp].unit_nodes,
            to_element_face=None)]

    from meshmode.mesh.tools import AffineMap

    if tgt_aff_map is None:
        tgt_aff_map = AffineMap()

    if src_aff_map is None:
        src_aff_map = AffineMap()

    tgt_bdry_nodes = tgt_aff_map(np.array([
        thaw_to_numpy(actx, ary[i_tgt_grp])[tgt_bdry_element_indices]
        for ary in tgt_bdry_discr.nodes(cached=False)
        ]))

    src_bdry_nodes = src_aff_map(np.array([
        thaw_to_numpy(actx, ary[i_src_grp])[src_bdry_element_indices]
        for ary in src_bdry_discr.nodes(cached=False)
        ]))

    tol = 1e4 * np.finfo(tgt_bdry_nodes.dtype).eps

    src_mesh_grp = src_bdry_discr.mesh.groups[i_src_grp]
    src_grp = src_bdry_discr.groups[i_src_grp]

    src_unit_nodes = _find_src_unit_nodes_by_matching(
            tgt_bdry_nodes=tgt_bdry_nodes,
            src_bdry_nodes=src_bdry_nodes,
            src_grp=src_grp, tol=tol)
    if src_unit_nodes is None:
        src_unit_nodes = _find_src_unit_nodes_via_gauss_newton(
            tgt_bdry_nodes=tgt_bdry_nodes,
            src_bdry_nodes=src_bdry_nodes,
            src_grp=src_grp, src_mesh_grp=src_mesh_grp,
            tgt_bdry_discr=tgt_bdry_discr, src_bdry_discr=src_bdry_discr,
            tol=tol)

    return list(_find_src_unit_nodes_batches(
            actx=actx, src_unit_nodes=src_unit_nodes,
            i_src_grp=i_src_grp,
            tgt_bdry_element_indices=tgt_bdry_element_indices,
            src_bdry_element_indices=src_bdry_element_indices,
            tol=tol))

# }}}


# {{{ _find_src_unit_nodes_by_matching

def _find_src_unit_nodes_by_matching(
        tgt_bdry_nodes,
        src_bdry_nodes,
        src_grp, tol):
    ambient_dim, nelements, ntgt_unit_nodes = tgt_bdry_nodes.shape

    dist_vecs = (tgt_bdry_nodes.reshape(ambient_dim, nelements, -1, 1)
            - src_bdry_nodes.reshape(ambient_dim, nelements, 1, -1))

    # shape: (nelements, num_tgt_nodes, num_source_nodes)
    is_close = la.norm(dist_vecs, axis=0, ord=2) < tol

    num_close_vertices = np.sum(is_close.astype(np.int32), axis=-1)
    if not (num_close_vertices == 1).all():
        return None

    # Success: it's just a permutation
    source_indices = np.where(is_close)[-1].reshape(nelements, ntgt_unit_nodes)

    # check
    matched_src_bdry_nodes = src_bdry_nodes[
            :, np.arange(nelements).reshape(-1, 1), source_indices]
    dist_vecs = tgt_bdry_nodes - matched_src_bdry_nodes
    is_close = la.norm(dist_vecs, axis=0, ord=2) < tol
    assert is_close.all()

    return src_grp.unit_nodes[:, source_indices]

# }}}


# {{{ _find_src_unit_nodes_via_gauss_newton

def _find_src_unit_nodes_via_gauss_newton(
        tgt_bdry_nodes,
        src_bdry_nodes,
        src_grp, src_mesh_grp,
        tgt_bdry_discr, src_bdry_discr,
        tol):
    dim = src_grp.dim
    _, nelements, ntgt_unit_nodes = tgt_bdry_nodes.shape

    initial_guess = np.mean(src_mesh_grp.vertex_unit_coordinates(), axis=0)
    src_unit_nodes = np.empty((dim, nelements, ntgt_unit_nodes))
    src_unit_nodes[:] = initial_guess.reshape(-1, 1, 1)

    import modepy as mp
    src_grp_basis_fcts = src_grp.basis_obj().functions
    vdm = mp.vandermonde(src_grp_basis_fcts, src_grp.unit_nodes)
    inv_t_vdm = la.inv(vdm.T)
    nsrc_funcs = len(src_grp_basis_fcts)

    def apply_map(unit_nodes):
        # unit_nodes: (dim, nelements, ntgt_unit_nodes)

        # basis_at_unit_nodes
        basis_at_unit_nodes = np.empty((nsrc_funcs, nelements, ntgt_unit_nodes))

        for i, f in enumerate(src_grp_basis_fcts):
            basis_at_unit_nodes[i] = (
                    f(unit_nodes.reshape(dim, -1))
                    .reshape(nelements, ntgt_unit_nodes))

        intp_coeffs = np.einsum("fj,jet->fet", inv_t_vdm, basis_at_unit_nodes)

        # If we're interpolating 1, we had better get 1 back.
        one_deviation = np.abs(np.sum(intp_coeffs, axis=0) - 1)
        assert (one_deviation < tol).all(), np.max(one_deviation)

        mapped = np.einsum("fet,aef->aet", intp_coeffs, src_bdry_nodes)
        assert tgt_bdry_nodes.shape == mapped.shape
        return mapped

    def get_map_jacobian(unit_nodes):
        # unit_nodes: (dim, nelements, ntgt_unit_nodes)

        # basis_at_unit_nodes
        dbasis_at_unit_nodes = np.empty(
                (dim, nsrc_funcs, nelements, ntgt_unit_nodes))

        for i, df in enumerate(src_grp.basis_obj().gradients):
            df_result = df(unit_nodes.reshape(dim, -1))

            for rst_axis, df_r in enumerate(df_result):
                dbasis_at_unit_nodes[rst_axis, i] = (
                        df_r.reshape(nelements, ntgt_unit_nodes))

        dintp_coeffs = np.einsum(
                "fj,rjet->rfet", inv_t_vdm, dbasis_at_unit_nodes)

        return np.einsum("rfet,aef->raet", dintp_coeffs, src_bdry_nodes)

    # {{{ test map applier and jacobian

    if 0:
        rng = np.random.default_rng(seed=None)

        u = src_unit_nodes
        f = apply_map(u)
        for h in [1e-1, 1e-2]:
            du = h*rng.normal(size=u.shape)

            f_2 = apply_map(u+du)

            jf = get_map_jacobian(u)

            f2_2 = f + np.einsum("raet,ret->aet", jf, du)

            print(h, la.norm((f_2-f2_2).ravel()))

    # }}}

    # {{{ visualize initial guess

    if 0:
        import matplotlib.pyplot as pt
        guess = apply_map(src_unit_nodes)
        goals = tgt_bdry_nodes

        from meshmode.discretization.visualization import draw_curve
        pt.figure(0)
        draw_curve(tgt_bdry_discr)
        pt.figure(1)
        draw_curve(src_bdry_discr)
        pt.figure(2)

        pt.plot(guess[0].reshape(-1), guess[1].reshape(-1), "or")
        pt.plot(goals[0].reshape(-1), goals[1].reshape(-1), "og")
        pt.plot(src_bdry_nodes[0].reshape(-1), src_bdry_nodes[1].reshape(-1), "xb")
        pt.show()

    # }}}

    logger.debug("_find_src_unit_nodes_via_gauss_newton: begin")

    niter = 0
    while True:
        resid = apply_map(src_unit_nodes) - tgt_bdry_nodes

        df = get_map_jacobian(src_unit_nodes)
        df_inv_resid = np.empty_like(src_unit_nodes)

        # For the 1D/2D accelerated versions, we'll use the normal
        # equations and Cramer's rule. If you're looking for high-end
        # numerics, look no further than meshmode.

        if dim == 1:
            # A is df.T
            ata = np.einsum("ikes,jkes->ijes", df, df)
            atb = np.einsum("ikes,kes->ies", df, resid)

            df_inv_resid = atb / ata[0, 0]

        elif dim == 2:
            # A is df.T
            ata = np.einsum("ikes,jkes->ijes", df, df)
            atb = np.einsum("ikes,kes->ies", df, resid)

            det = ata[0, 0]*ata[1, 1] - ata[0, 1]*ata[1, 0]

            df_inv_resid = np.empty_like(src_unit_nodes)
            df_inv_resid[0] = 1/det * (ata[1, 1] * atb[0] - ata[1, 0]*atb[1])
            df_inv_resid[1] = 1/det * (-ata[0, 1] * atb[0] + ata[0, 0]*atb[1])

        else:
            # The boundary of a 3D mesh is 2D, so that's the
            # highest-dimensional case we genuinely care about.
            #
            # This stinks, performance-wise, because it's not vectorized.
            # But we'll only hit it for boundaries of 4+D meshes, in which
            # case... good luck. :)
            for e in range(nelements):
                for t in range(ntgt_unit_nodes):
                    df_inv_resid[:, e, t], _, _, _ = \
                            la.lstsq(df[:, :, e, t].T, resid[:, e, t])

        src_unit_nodes = src_unit_nodes - df_inv_resid

        # {{{ visualize next guess

        if 0:
            import matplotlib.pyplot as pt
            guess = apply_map(src_unit_nodes)
            goals = tgt_bdry_nodes

            pt.plot(guess[0].reshape(-1), guess[1].reshape(-1), "rx")
            pt.plot(goals[0].reshape(-1), goals[1].reshape(-1), "go")
            pt.show()

        # }}}

        max_resid = np.max(np.abs(resid))

        if max_resid < tol:
            logger.debug("_find_src_unit_nodes_via_gauss_newton: done, "
                    "final residual: %g", max_resid)
            return src_unit_nodes

        niter += 1
        if niter > 10:
            raise RuntimeError("Gauss-Newton (for finding opposite-face reference "
                    "coordinates) did not converge (residual: %g)" % max_resid)

    raise AssertionError()

# }}}


# {{{ _find_src_unit_nodes_batches

def _find_src_unit_nodes_batches(
        actx, src_unit_nodes, i_src_grp,
        tgt_bdry_element_indices, src_bdry_element_indices,
        tol):
    dim, nelements, _ = src_unit_nodes.shape

    done_elements = np.zeros(nelements, dtype=bool)
    while True:
        todo_elements, = np.where(~done_elements)
        if not len(todo_elements):
            return

        template_unit_nodes = src_unit_nodes[:, todo_elements[0], :]

        unit_node_dist = np.max(np.max(np.abs(
                src_unit_nodes[:, todo_elements, :]
                - template_unit_nodes.reshape(dim, 1, -1)),
                axis=2), axis=0)

        close_els = todo_elements[unit_node_dist < tol]
        done_elements[close_els] = True

        yield InterpolationBatch(
                from_group_index=i_src_grp,
                from_element_indices=freeze_from_numpy(
                    actx, src_bdry_element_indices[close_els]),
                to_element_indices=freeze_from_numpy(
                    actx, tgt_bdry_element_indices[close_els]),
                result_unit_nodes=template_unit_nodes,
                to_element_face=None)

# }}}


def _find_ibatch_for_face(vbc_tgt_grp_batches, iface):
    vbc_tgt_grp_face_batches = [
            batch
            for batch in vbc_tgt_grp_batches
            if batch.to_element_face == iface]

    assert len(vbc_tgt_grp_face_batches) == 1

    vbc_tgt_grp_face_batch, = vbc_tgt_grp_face_batches

    return vbc_tgt_grp_face_batch


def _make_bdry_el_lookup_table(actx, connection, igrp):
    """Given a volume-to-boundary connection as *connection*, return
    a table of shape ``(from_nelements, nfaces)`` to look up the
    element number of the boundary element for that face.
    """
    from_nelements = connection.from_discr.groups[igrp].nelements
    from_nfaces = connection.from_discr.mesh.groups[igrp].nfaces

    iel_lookup = np.full((from_nelements, from_nfaces), -1,
            dtype=connection.from_discr.mesh.element_id_dtype)

    for batch in connection.groups[igrp].batches:
        from_element_indices = thaw_to_numpy(actx, batch.from_element_indices)
        iel_lookup[from_element_indices, batch.to_element_face] = \
                thaw_to_numpy(actx, batch.to_element_indices)

    return iel_lookup

# }}}


# {{{ make_opposite_face_connection

def make_opposite_face_connection(actx, volume_to_bdry_conn):
    """Given a boundary restriction connection *volume_to_bdry_conn*,
    return a :class:`DirectDiscretizationConnection` that performs data
    exchange across opposite faces.
    """

    vol_discr = volume_to_bdry_conn.from_discr
    vol_mesh = vol_discr.mesh
    bdry_discr = volume_to_bdry_conn.to_discr

    # make sure we were handed a volume-to-boundary connection
    for i_tgrp, conn_grp in enumerate(volume_to_bdry_conn.groups):
        for batch in conn_grp.batches:
            assert batch.from_group_index == i_tgrp
            assert batch.to_element_face is not None

    ngrps = len(volume_to_bdry_conn.groups)
    assert ngrps == len(vol_discr.groups)
    assert ngrps == len(bdry_discr.groups)

    # One interpolation batch in this connection corresponds
    # to a key (i_tgt_grp,)  (i_src_grp, i_face_tgt,)

    # a list of batches for each group
    groups = [[] for i_tgt_grp in range(ngrps)]

    for i_src_grp in range(ngrps):
        src_grp_el_lookup = _make_bdry_el_lookup_table(
                actx, volume_to_bdry_conn, i_src_grp)

        for i_tgt_grp in range(ngrps):
            vbc_tgt_grp_batches = volume_to_bdry_conn.groups[i_tgt_grp].batches

            from meshmode.mesh import InteriorAdjacencyGroup
            adj_grps = [
                adj for adj in vol_mesh.facial_adjacency_groups[i_tgt_grp]
                if isinstance(adj, InteriorAdjacencyGroup)
                and adj.ineighbor_group == i_src_grp]

            for adj in adj_grps:
                for i_face_tgt in range(vol_mesh.groups[i_tgt_grp].nfaces):
                    vbc_tgt_grp_face_batch = _find_ibatch_for_face(
                            vbc_tgt_grp_batches, i_face_tgt)

                    # {{{ index wrangling

                    # The elements in the adjacency group will be a subset of
                    # the elements in the restriction interpolation batch:
                    # Imagine an inter-group boundary. The volume-to-boundary
                    # connection will include all faces as targets, whereas
                    # there will be separate adjacency groups for intra- and
                    # inter-group connections.

                    adj_tgt_flags = adj.element_faces == i_face_tgt
                    adj_els = adj.elements[adj_tgt_flags]
                    if adj_els.size == 0:
                        # NOTE: this case can happen for inter-group boundaries
                        # when all elements are adjacent on the same face
                        # index, so all other ones will be empty
                        continue

                    vbc_els = thaw_to_numpy(actx,
                            vbc_tgt_grp_face_batch.from_element_indices)

                    if len(adj_els) == len(vbc_els):
                        # Same length: assert (below) that the two use the same
                        # ordering.
                        vbc_used_els = slice(None)

                    else:
                        # Genuine subset: figure out an index mapping.
                        vbc_els_sort_idx = np.argsort(vbc_els)
                        vbc_used_els = vbc_els_sort_idx[np.searchsorted(
                            vbc_els, adj_els, sorter=vbc_els_sort_idx
                            )]

                    assert np.array_equal(vbc_els[vbc_used_els], adj_els)

                    # find tgt_bdry_element_indices

                    tgt_bdry_element_indices = thaw_to_numpy(
                            actx,
                            vbc_tgt_grp_face_batch.to_element_indices
                            )[vbc_used_els]

                    # find src_bdry_element_indices

                    src_vol_element_indices = adj.neighbors[adj_tgt_flags]
                    src_element_faces = adj.neighbor_faces[adj_tgt_flags]

                    src_bdry_element_indices = src_grp_el_lookup[
                            src_vol_element_indices, src_element_faces]

                    # }}}

                    # {{{ visualization (for debugging)

                    if 0:
                        print("target volume elements:", adj.elements[adj_tgt_flags])
                        print("target boundary elements:", tgt_bdry_element_indices)
                        print("neighbor volume elements:", src_vol_element_indices)
                        import matplotlib.pyplot as pt

                        from meshmode.mesh.visualization import draw_2d_mesh
                        draw_2d_mesh(vol_discr.mesh, draw_element_numbers=True,
                                set_bounding_box=True,
                                draw_vertex_numbers=False,
                                draw_face_numbers=True,
                                fill=None)
                        pt.figure()

                        draw_2d_mesh(bdry_discr.mesh, draw_element_numbers=True,
                                set_bounding_box=True,
                                draw_vertex_numbers=False,
                                draw_face_numbers=True,
                                fill=None)

                        pt.show()

                    # }}}

                    batches = _make_cross_face_batches(actx,
                            bdry_discr, bdry_discr,
                            i_tgt_grp, i_src_grp,
                            tgt_bdry_element_indices,
                            src_bdry_element_indices,
                            tgt_aff_map=adj.aff_map)
                    groups[i_tgt_grp].extend(batches)

    from meshmode.discretization.connection import (
        DirectDiscretizationConnection,
        DiscretizationConnectionElementGroup,
    )
    return DirectDiscretizationConnection(
            from_discr=bdry_discr,
            to_discr=bdry_discr,
            groups=[
                DiscretizationConnectionElementGroup(batches=batches)
                for batches in groups],
            is_surjective=True)

# }}}


# {{{ make_partition_connection

# FIXME: Consider adjusting terminology from local/remote to self/other.
def make_partition_connection(actx, *, local_bdry_conn,
        remote_bdry_discr, remote_group_infos):
    """
    Connects ``local_bdry_conn`` to a neighboring part.

    :arg local_bdry_conn: A :class:`DiscretizationConnection` of the local part.
    :arg remote_bdry_discr: A :class:`~meshmode.discretization.Discretization`
        of the boundary of the remote part.
    :arg remote_group_infos: An array of
        :class:`meshmode.distributed.RemoteGroupInfo` instances, one per remote
        volume element group.
    :returns: A :class:`DirectDiscretizationConnection` that performs data
        exchange across faces from the remote part to the local part.

    .. versionadded:: 2017.1

    .. warning:: Interface is not final.
    """

    from meshmode.discretization.connection import (
        DirectDiscretizationConnection,
        DiscretizationConnectionElementGroup,
    )
    from meshmode.mesh.processing import find_group_indices

    local_vol_mesh = local_bdry_conn.from_discr.mesh
    local_vol_groups = local_vol_mesh.groups

    part_batches = [[] for _ in local_vol_groups]

    assert len(local_vol_groups) == len(local_bdry_conn.to_discr.groups)

    # We need a nested loop over remote and local groups here.
    # The code assumes that there is the same number of volume and surface groups.
    #
    # A weak reason to choose remote as the outer loop is because
    # InterPartAdjacency refers to neighbors by global volume element
    # numbers, and we only have enough information to resolve those to (group,
    # group_local_el_nr) for local elements (whereas we have no information
    # about remote volume elements).
    #
    # (See the find_group_indices below.)

    for rgi in remote_group_infos:
        rem_ipags = rgi.inter_part_adj_groups

        for rem_ipag in rem_ipags:
            i_local_grps = find_group_indices(local_vol_groups, rem_ipag.neighbors)

            # {{{ make remote_vol_to_bdry

            remote_approx_vol_nelements = np.max(rgi.vol_elem_indices)+1
            remote_approx_nfaces = np.max(rgi.bdry_faces)+1
            remote_vol_to_bdry = np.full(
                    (remote_approx_vol_nelements, remote_approx_nfaces),
                    -1, dtype=remote_bdry_discr.mesh.element_id_dtype)
            remote_vol_to_bdry[rgi.vol_elem_indices, rgi.bdry_faces] = \
                    rgi.bdry_elem_indices

            # }}}

            for i_local_grp in np.unique(i_local_grps):

                # {{{ come up with matched_{local,remote}_bdry_el_indices

                local_vol_to_bdry = _make_bdry_el_lookup_table(actx, local_bdry_conn,
                            i_local_grp)

                local_indices = np.where(i_local_grps == i_local_grp)[0]

                local_grp_vol_elems = (
                        rem_ipag.neighbors[local_indices]
                        - local_vol_mesh.base_element_nrs[i_local_grp])
                # These are group-local.
                remote_grp_vol_elems = rem_ipag.elements[local_indices]

                matched_local_bdry_el_indices = local_vol_to_bdry[
                        local_grp_vol_elems,
                        rem_ipag.neighbor_faces[local_indices]]
                assert (matched_local_bdry_el_indices >= 0).all()
                matched_remote_bdry_el_indices = remote_vol_to_bdry[
                        remote_grp_vol_elems,
                        rem_ipag.element_faces[local_indices]]
                assert (matched_remote_bdry_el_indices >= 0).all()

                # }}}

                grp_batches = _make_cross_face_batches(actx,
                            local_bdry_conn.to_discr, remote_bdry_discr,
                            i_local_grp, rem_ipag.igroup,
                            matched_local_bdry_el_indices,
                            matched_remote_bdry_el_indices,
                            src_aff_map=rem_ipag.aff_map)

                part_batches[i_local_grp].extend(grp_batches)

    return DirectDiscretizationConnection(
            from_discr=remote_bdry_discr,
            to_discr=local_bdry_conn.to_discr,
            groups=[DiscretizationConnectionElementGroup(batches=grp_batches)
                        for grp_batches in part_batches],
            is_surjective=True)

# }}}


# vim: foldmethod=marker
