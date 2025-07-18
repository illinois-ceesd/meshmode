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


__doc__ = """
.. autoexception:: Error
.. autoexception:: DataUnavailableError

.. autoexception:: InconsistentMeshError
.. autoexception:: InconsistentArrayDTypeError
.. autoexception:: InconsistentVerticesError
.. autoexception:: InconsistentAdjacencyError
"""

from builtins import FileExistsError  # noqa: F401

from meshmode.mesh.tools import AffineMap  # noqa: F401


class Error(RuntimeError):
    """Exception base for :mod:`meshmode` errors."""


class DataUnavailableError(Error):
    """Raised when some data on the mesh or the discretization is not available.

    This error should not be raised when the specific data simply fails to be
    computed for other reasons.
    """


DataUnavailable = DataUnavailableError


class InconsistentMeshError(Error):
    """Raised when the mesh is inconsistent in some fashion.

    Prefer the more specific exceptions, e.g. :exc:`InconsistentVerticesError`
    when possible.
    """


class InconsistentArrayDTypeError(InconsistentMeshError):
    """Raised when a mesh (or group) array does not match the provided
    :class:`~numpy.dtype`.
    """


class InconsistentVerticesError(InconsistentMeshError):
    """Raised when an element's local-to-global mapping does not map the unit
    vertices to the corresponding values in the mesh's *vertices* array.
    """


class InconsistentAdjacencyError(InconsistentMeshError):
    """Raised when the nodal or the facial adjacency is inconsistent."""


def _acf():
    """A tiny undocumented function to pass to tests that take an ``actx_factory``
    argument when running them from the command line.
    """
    import pyopencl as cl

    from meshmode.array_context import PyOpenCLArrayContext

    context = cl._csc()
    queue = cl.CommandQueue(context)
    return PyOpenCLArrayContext(queue)
