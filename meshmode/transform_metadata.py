"""
.. autoclass:: FirstAxisIsElementsTag
.. autoclass:: ConcurrentElementInameTag
.. autoclass:: ConcurrentDOFInameTag
.. autoclass:: DiscretizationEntityAxisTag
.. autoclass:: DiscretizationElementAxisTag
.. autoclass:: DiscretizationFaceAxisTag
.. autoclass:: DiscretizationDOFAxisTag
.. autoclass:: DiscretizationAmbientDimAxisTag
.. autoclass:: DiscretizationTopologicalDimAxisTag
.. autoclass:: DiscretizationDOFPickListAxisTag
"""

__copyright__ = """
Copyright (C) 2020-1 University of Illinois Board of Trustees
"""

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

from pytools.tag import Tag, UniqueTag, tag_dataclass
from pytato.transform.metadata import AxisIgnoredForPropagationTag


class FirstAxisIsElementsTag(Tag):
    """A tag that is applicable to array outputs indicating that the first
    index corresponds to element indices. This suggests that the implementation
    should set element indices as the outermost loop extent.

    For convenience, this tag may *also* be applied to a kernel if that kernel
    contains exactly one assignment, in which case the tag is considered
    equivalent to being applied to the (single) output array argument.
    """


class ConcurrentElementInameTag(Tag):
    """A tag applicable to an iname indicating that this iname is used to
    iterate over elements in a discretization. States that no dependencies
    exist between elements, i.e. that computations for all elements may be
    performed concurrently.
    """


class ConcurrentDOFInameTag(Tag):
    """A tag applicable to an iname indicating that this iname is used to
    iterate over degrees of freedom (DOFs) within an element in a discretization.
    States that no dependencies exist between output DOFs, i.e. that
    computations for all DOFs within each element may be performed
    concurrently.
    """


class DiscretizationEntityAxisTag(UniqueTag):
    """
    A tag applicable to an array's axis to describe which discretization entity
    the axis indexes over.
    """


@tag_dataclass
class DiscretizationElementAxisTag(DiscretizationEntityAxisTag):
    """
    Array dimensions tagged with this tag type describe an axis indexing over
    the discretization's elements.
    """


@tag_dataclass
class DiscretizationFaceAxisTag(DiscretizationEntityAxisTag):
    """
    Array dimensions tagged with this tag type describe an axis indexing over
    the discretization's faces.
    """


@tag_dataclass
class DiscretizationDOFAxisTag(DiscretizationEntityAxisTag):
    """
    Array dimensions tagged with this tag type describe an axis indexing over
    the discretization's DoFs (nodal or modal).
    """


@tag_dataclass
class DiscretizationFlattenedDOFAxisTag(DiscretizationEntityAxisTag):
    """
    Array dimensions tagged with this tag type describe an axis indexing over
    the discretization's DoFs.
    """


@tag_dataclass
class DiscretizationDimAxisTag(DiscretizationEntityAxisTag):
    pass


class DiscretizationAmbientDimAxisTag(DiscretizationDimAxisTag):
    """
    Array dimensions tagged with this tag type describe an axis indexing over
    the discretization's reference coordinate dimensions.
    """


class DiscretizationTopologicalDimAxisTag(DiscretizationDimAxisTag):
    """
    Array dimensions tagged with this tag type describe an axis indexing over
    the discretization's physical coordinate dimensions.
    """


@tag_dataclass
class DiscretizationDOFPickListAxisTag(DiscretizationEntityAxisTag):
    """
    Array dimensions tagged with this tag type describe an axis indexing over
    DOF pick lists. See :mod:`meshmode.discretization.connection.direct` for
    details.
    """

# {{{ tensor-product and operator metadata

class OperatorTag(Tag):
    """
    Used to signify that an array is an operator.
    """


class FaceMassOperatorTag(OperatorTag):
    """
    Used to signify than an array is a face mass operator.
    """


class MassOperatorTag(OperatorTag):
    """
    Used to signify that an array is a mass operator.
    """


class MassInverseOperatorTag(OperatorTag):
    """
    Used to signify that an array is an inverse mass operator.
    """


class DifferentiationOperatorTag(OperatorTag):
    """
    Used to signify that an array is a *strong* differentiation operator.
    """


class StiffnessOperatorTag(OperatorTag):
    """
    Used to signify that an array is a *weak* differentiation operator.
    """


@tag_dataclass
class TensorProductDOFAxisTag(DiscretizationEntityAxisTag):
    """
    Signify an axis as containing the DOFs of a tensor product discretization.
    `iaxis` is later interpreted to determine the relative update speed (i.e.
    the stride) of each axis.
    """
    iaxis: int


class TensorProductOperatorAxisTag(
        DiscretizationEntityAxisTag,
        AxisIgnoredForPropagationTag
    ):
    """
    Signify an axis is part of a 1D operator applied to a tensor product
    discretization. No tags will be propagated to or along axes containing this
    tag.
    """
    pass


class TensorProductOperatorTag(Tag):
    """
    Used to tag an operator as one that acts on DOFs from a tensor-product
    discretization. Used to make decisions about how to handle prefetching and
    precomputing these operators.
    """
    pass


class TensorProductMassOperatorTag(TensorProductOperatorTag):
    """
    Tag an operator as being a reference mass operator. Used to realize an
    algebraic simplification of redundant mass-times-mass-inverse operations
    when using a tensor product discretization.
    """
    pass


class TensorProductMassInverseOperatorTag(TensorProductOperatorTag):
    """
    See `TensorProductMassOperatorTag`.
    """
    pass


class TensorProductDifferentiationOperatorTag(OperatorTag):
    """
    See `DifferentiationOperatorTag`.
    """


class TensorProductStiffnessOperatorTag(TensorProductOperatorTag):
    """
    Similar to `TensorProductMassOperatorTag`. Used to implement an
    associativity DAG transformation.
    """
    pass

# }}}
