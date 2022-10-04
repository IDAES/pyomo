"""
Abstract and pre-defined classes for representing uncertainty sets (or
uncertain parameter spaces) of two-stage nonlinear robust optimization
models.

Along with a ``ConcreteModel`` object representing a deterministic model
formulation, an uncertainty set object may be passed to the PyROS solver
to obtain a solution to the model's two-stage robust optimization
counterpart.

Classes
-------
``UncertaintySet``
    Abstract base class for a generic uncertainty set. All other set
    types defined in this module are subclasses.  A user may implement
    their own uncertainty set type as a custom-written subclass.

``EllipsoidalSet``
    A hyperellipsoid.

``AxisAlignedEllipsoidalSet``
    An axis-aligned hyperellipsoid.

``PolyhedralSet``
    A bounded convex polyhedron/polytope.

``BoxSet``
    A hyperrectangle.

``BudgetSet``
    A budget set.

``CardinalitySet``
    A cardinality set (or gamma set).

``DiscreteScenarioSet``
    A discrete set of finitely many points.

``FactorModelSet``
    A factor model set (or net-alpha model set).

``IntersectionSet``
    An intersection of two or more sets, each represented by an
    ``UncertaintySet`` object.
"""


import abc
import math
import functools
from collections.abc import Iterable, MutableSequence
from enum import Enum

from pyomo.common.dependencies import numpy as np, scipy as sp
from pyomo.core.base import ConcreteModel, Objective, maximize, minimize, Block
from pyomo.core.base.constraint import ConstraintList
from pyomo.core.base.var import Var, IndexedVar
from pyomo.core.expr.numvalue import value, native_numeric_types
from pyomo.opt.results import check_optimal_termination
from pyomo.contrib.pyros.util import add_bounds_for_uncertain_parameters


valid_num_types = tuple(native_numeric_types)


def validate_arg_type(
        arg_name,
        arg_val,
        valid_types,
        valid_type_desc=None,
        is_entry_of_arg=False,
        check_numeric_type_finite=True,
        ):
    """
    Perform type validation of an argument to a function/method.
    If type is not valid, raise a TypeError with an appropriate
    message.

    Parameters
    ----------
    arg_name : str
        Name of argument to be displayed in exception message.
    arg_val : object
        Value of argument to be checked.
    valid_types : type or tuple of types
        Valid types for the argument value.
    valid_type_desc : str or None, optional
        Description of valid types for the argument value;
        this description is included in the exception message.
    is_entry_of_arg : bool, optional
        Is the argument value passed an entry of the argument
        described by `arg_name` (such as entry of an array or list).
        This will be indicated in the exception message.
        The default is `False`.
    check_numeric_type_finite : bool, optional
        If the valid types comprise a sequence of numeric types,
        check that the argument value is finite (and also not NaN),
        as well. The default is `True`.

    Raises
    ------
    TypeError
        If the argument value is not a valid type.
    ValueError
        If the finiteness check on a numerical value returns
        a negative result.
    """
    if not isinstance(arg_val, valid_types):
        if valid_type_desc is not None:
            type_phrase = f"not {valid_type_desc}"
        else:
            valid_type_str = ", ".join(dtype.__name__ for dtype in valid_types)
            type_phrase = f"not of any of the valid types ({valid_type_str})"

        if is_entry_of_arg:
            raise TypeError(
                f"Entry '{arg_val}' of the argument `{arg_name}` "
                f"is {type_phrase} (provided type '{type(arg_val).__name__}')"
            )
        else:
            raise TypeError(
                f"Argument `{arg_name}` is {type_phrase} "
                f"(provided type '{type(arg_val).__name__}')"
            )

    # check for finiteness, if desired
    if check_numeric_type_finite:
        if isinstance(valid_types, type):
            numeric_types_required = valid_types in valid_num_types
        else:
            numeric_types_required = set(valid_types).issubset(valid_num_types)
        if numeric_types_required and (math.isinf(arg_val) or math.isnan(arg_val)):
            if is_entry_of_arg:
                raise ValueError(
                    f"Entry '{arg_val}' of the argument `{arg_name}` "
                    f"is not a finite numeric value"
                )
            else:
                raise ValueError(
                    f"Argument `{arg_name}` is not a finite numeric value "
                    f"(provided value '{arg_val}')"
                )


def is_ragged(arr, arr_types=None):
    """
    Determine whether an array-like (such as a list or Numpy ndarray)
    is ragged.

    NOTE: if Numpy ndarrays are considered to be arr types,
    then zero-dimensional arrays are not considered to be as such.
    """
    arr_types = (list, np.ndarray, tuple) if arr_types is None else arr_types

    is_zero_dim_arr = isinstance(arr, np.ndarray) and len(arr.shape) == 0
    if not isinstance(arr, arr_types) or is_zero_dim_arr:
        return False

    entries_are_seqs = []
    for entry in arr:
        if np.ndarray in arr_types and isinstance(entry, np.ndarray):
            # account for 0-D arrays (treat as non-arrays)
            entries_are_seqs.append(len(entry.shape) > 0)
        else:
            entries_are_seqs.append(isinstance(entry, arr_types))

    if not any(entries_are_seqs):
        return False
    if not all(entries_are_seqs):
        return True

    entries_ragged = [is_ragged(entry for entry in arr)]
    if any(entries_ragged):
        return True
    else:
        return any(
            np.array(arr[0]).shape != np.array(entry).shape for entry in arr
        )


def validate_dimensions(arr_name, arr, dim, display_value=False):
    """
    Validate dimension of an array-like object.
    Raise Exception if validation fails.
    """
    if is_ragged(arr):
        raise ValueError(
            f"Argument `{arr_name}` should not be a ragged array-like "
            "(nested sequence of lists, tuples, arrays of different shape)"
        )

    # check dimensions matched
    array = np.asarray(arr)
    if len(array.shape) != dim:
        val_str = f" from provided value {str(arr)}" if display_value else ""
        raise ValueError(
            f"Argument `{arr_name}` must be a "
            f"{dim}-dimensional array-like "
            f"(detected {len(array.shape)} dimensions{val_str})"
        )
    elif array.shape[-1] == 0:
        raise ValueError(
            f"Last dimension of argument `{arr_name}` must be non-empty "
            f"(detected shape {array.shape})"
        )


def validate_array(
        arr,
        arr_name,
        dim,
        valid_types,
        valid_type_desc=None,
        required_shape=None,
        ):
    """
    Validate shape and entry types of an array-like object.

    Parameters
    ----------
    arr : array_like
        Object to validate.
    arr_name : str
        A name/descriptor of the object to validate.
        Usually, this is the name of an object attribute
        to which the array is meant to be set.
    dim : int
        Required dimension of the array-like object.
    valid_types : set[type]
        Allowable type(s) for each entry of the array.
    valid_type_desc : str or None, optional
        Descriptor for the allowable types.
    required_shape : list or None, optional
        Specification of the length of the array in each dimension.
        If `None` is provided, no specifications are imposed.
        If a `list` is provided, then each entry of the listmust be
        an `int` specifying the required length in the dimension
        corresponding to the position of the entry
        or `None` (meaning no requirement for the length in the
        corresponding dimension).
    """
    np_arr = np.array(arr, dtype=object)
    validate_dimensions(arr_name, np_arr, dim, display_value=False)

    def generate_shape_str(shape, required_shape):
        shape_str = ""
        assert len(shape) == len(required_shape)
        for idx, (sval, rsval) in enumerate(zip(shape, required_shape)):
            if rsval is None:
                shape_str += "..."
            else:
                shape_str += f"{sval}"
            if idx < len(shape) - 1:
                shape_str += ","
        return "(" + shape_str + ")"

    # validate shape requirements
    if required_shape is not None:
        assert len(required_shape) == dim
        for idx, size in enumerate(required_shape):
            if size is not None and size != np_arr.shape[idx]:
                req_shape_str = generate_shape_str(
                    required_shape,
                    required_shape,
                )
                actual_shape_str = generate_shape_str(
                    np_arr.shape,
                    required_shape,
                )
                raise ValueError(
                    f"Attribute '{arr_name}' should be of shape "
                    f"{req_shape_str}, but detected shape "
                    f"{actual_shape_str}"
                )

    for val in np_arr.flat:
        validate_arg_type(
            arr_name,
            val,
            valid_types,
            valid_type_desc=valid_type_desc,
            is_entry_of_arg=True,
        )


def uncertainty_sets(obj):
    if not isinstance(obj, UncertaintySet):
        raise ValueError("Expected an UncertaintySet object, instead recieved %s" % (obj,))
    return obj


def column(matrix, i):
    # Get column i of a given multi-dimensional list
    return [row[i] for row in matrix]


class Geometry(Enum):
    """
    Geometry classifications for PyROS uncertainty set objects.
    """
    LINEAR = 1
    CONVEX_NONLINEAR = 2
    GENERAL_NONLINEAR = 3
    DISCRETE_SCENARIOS = 4


class UncertaintySet(object, metaclass=abc.ABCMeta):
    """
    An object representing an uncertainty set for a two-stage robust
    optimization model. Along with a `ConcreteModel` object
    representing the corresponding deterministic model formulation, the
    uncertainty set object may be passed to the PyROS solver to obtain a
    robust model solution.

    An `UncertaintySet` object should be viewed as merely a container
    for data needed to parameterize the set it represents, such that the
    object's attributes do not, in general, reference the
    components of a Pyomo modeling object.
    """

    @property
    @abc.abstractmethod
    def dim(self):
        """
        Dimension of the uncertainty set (number of uncertain
        parameters in a corresponding optimization model of interest).
        """
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def geometry(self):
        """
        Geometry of the uncertainty set. See the `Geometry` class
        documentation.
        """
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def parameter_bounds(self):
        """
        Bounds for the value of each uncertain parameter constrained
        by the set (i.e. bounds for each set dimension).
        """
        raise NotImplementedError

    def is_bounded(self, config):
        """
        Determine whether the uncertainty set is bounded.

        Parameters
        ----------
        config : ConfigDict
            PyROS solver configuration.

        Returns
        -------
        : bool
            True if the uncertainty set is certified to be bounded,
            and False otherwise.

        Notes
        -----
        This check is carried out by solving a sequence of maximization
        and minimization problems (in which the objective for each
        problem is the value of a single uncertain parameter). If any of
        the optimization models cannot be solved successfully to
        optimality, then False is returned.

        This method is invoked during the validation step of a PyROS
        solver call.
        """
        # === Determine bounds on all uncertain params
        bounding_model = ConcreteModel()
        bounding_model.util = Block() # So that boundedness checks work for Cardinality and FactorModel sets
        bounding_model.uncertain_param_vars = IndexedVar(range(len(config.uncertain_params)), initialize=1)
        for idx, param in enumerate(config.uncertain_params):
            bounding_model.uncertain_param_vars[idx].set_value(
                param.value, skip_validation=True)

        bounding_model.add_component("uncertainty_set_constraint",
                                     config.uncertainty_set.set_as_constraint(
                                         uncertain_params=bounding_model.uncertain_param_vars,
                                         model=bounding_model,
                                         config=config
                                     ))

        for idx, param in enumerate(list(bounding_model.uncertain_param_vars.values())):
            bounding_model.add_component("lb_obj_" + str(idx), Objective(expr=param, sense=minimize))
            bounding_model.add_component("ub_obj_" + str(idx), Objective(expr=param, sense=maximize))

        for o in bounding_model.component_data_objects(Objective):
            o.deactivate()

        for i in range(len(bounding_model.uncertain_param_vars)):
            for limit in ("lb", "ub"):
                getattr(bounding_model, limit + "_obj_" + str(i)).activate()
                res = config.global_solver.solve(bounding_model, tee=False)
                getattr(bounding_model, limit + "_obj_" + str(i)).deactivate()
                if not check_optimal_termination(res):
                    return False
        return True

    def is_nonempty(self, config):
        """
        Return True if the uncertainty set is nonempty, else False.
        """
        return self.is_bounded(config)

    def is_valid(self, config):
        """
        Return True if the uncertainty set is bounded and non-empty,
        else False.
        """
        return self.is_nonempty(config=config) and self.is_bounded(config=config)

    @abc.abstractmethod
    def set_as_constraint(self, **kwargs):
        """
        Construct a (sequence of) mathematical constraint(s)
        (represented by Pyomo `Constraint` objects) on the uncertain
        parameters to represent the uncertainty set for use in a
        two-stage robust optimization problem or subproblem (such as a
        PyROS separation subproblem).

        Parameters
        ----------
        **kwargs : dict
            Keyword arguments containing, at the very least, a sequence
            of `Param` or `Var` objects representing the uncertain
            parameters of interest, and any additional information
            needed to generate the constraints.
        """
        pass

    def point_in_set(self, point):
        """
        Determine whether a given point lies in the uncertainty set.

        Parameters
        ----------
        point : (N,) array-like
            Point (parameter value) of interest.

        Returns
        -------
        is_in_set : bool
            True if the point lies in the uncertainty set,
            False otherwise.

        Notes
        -----
        This method is invoked at the outset of a PyROS solver call to
        determine whether a user-specified nominal parameter realization
        lies in the uncertainty set.
        """

        # === Ensure point is of correct dimensionality as the uncertain parameters
        if len(point) != self.dim:
            raise AttributeError("Point must have same dimensions as uncertain parameters.")

        m = ConcreteModel()
        the_params = []
        for i in range(self.dim):
            m.add_component("x_%s" % i, Var(initialize=point[i]))
            the_params.append(getattr(m, "x_%s" % i))

        # === Generate constraint for set
        set_constraint = self.set_as_constraint(uncertain_params=the_params)

        # === value() returns True if the constraint is satisfied, False else.
        is_in_set = all(value(con.expr) for con in set_constraint.values())

        return is_in_set

    @staticmethod
    def add_bounds_on_uncertain_parameters(**kwargs):
        """
        Specify the numerical bounds for the uncertain parameters
        restricted by the set. Each uncertain parameter is represented
        by a Pyomo `Var` object in a model passed to this method,
        and the numerical bounds are specified by setting the
        `.lb()` and `.ub()` attributes of the `Var` object.

        Parameters
        ----------
        kwargs : dict
            Keyword arguments consisting of a Pyomo `ConfigDict` and a
            Pyomo `ConcreteModel` object, representing a PyROS solver
            configuration and the optimization model of interest.

        Notes
        -----
        This method is invoked in advance of a PyROS separation
        subproblem.
        """
        config = kwargs.pop('config')
        model = kwargs.pop('model')
        _set = config.uncertainty_set
        parameter_bounds = _set.parameter_bounds
        for i, p in enumerate(model.util.uncertain_param_vars.values()):
            p.setlb(parameter_bounds[i][0])
            p.setub(parameter_bounds[i][1])


class UncertaintySetList(MutableSequence):
    """
    List-like container for a(n ordered) sequence of uncertainty
    sets of an immutable common dimension.

    Parameters
    ----------
    iterable : Iterable
        Sequence of uncertainty sets to be contained within
        the list.
    name : str or None, optional
        Name of the uncertainty set list.
    min_length : int or None, optional
        Minimum length requirement for the set.
        If `None` is provided, then the set has a minimum
        length requirement of 0.
    """

    def __init__(self, iterable=[], name=None, min_length=None):
        self._name = name
        self._min_length = 0 if min_length is None else min_length

        # check minimum length requirement satisfied
        initlist = list(iterable)
        if len(initlist) < self._min_length:
            raise ValueError(
                f"Attempting to initialize uncertainty set list "
                f"{self._name!r} "
                f"of minimum required length {self._min_length} with an "
                f"iterable of length {len(initlist)}"
            )

        # validate first entry of initial list.
        # The common dimension is set to that of the entry
        # if validation is successful
        self._dim = None
        if initlist:
            self._validate(initlist[0])

        # now initialize the list
        self._list = []
        self.extend(initlist)

    def __len__(self):
        return len(self._list)

    def __repr__(self):
        return f"{self.__class__.__name__}({repr(self._list)})"

    def __getitem__(self, idx):
        return self._list[idx]

    def __setitem__(self, idx, value):
        self._validate(value)
        self._check_length_update(idx, value)
        self._list[idx] = value

    def __delitem__(self, idx):
        self._check_length_update(idx, [])
        del self._list[idx]

    def clear(self):
        self._check_length_update(slice(0, len(self)), [])
        self._list.clear()

    def insert(self, idx, value):
        self._validate(value, single_item=True)
        self._list.insert(idx, value)

    def _check_length_update(self, idx, value):
        """
        Check whether the update ``self[idx] = value`` reduces the
        length of self to a value smaller than the minimum length.

        Raises
        ------
        ValueError
            If minimum length requirement is violated by the update.
        """
        def default(val, def_val):
            return def_val if val is None else val

        if isinstance(idx, slice):
            slice_len = len(
                range(
                    default(idx.start, 0),
                    min(default(idx.stop, len(self)), len(self)),
                    default(idx.step, 1),
                )
            )
        else:
            slice_len = 1

        val_len = len(value) if isinstance(value, Iterable) else 1
        new_len = len(self) + val_len - slice_len
        if new_len < self._min_length:
            raise ValueError(
                f"Length of uncertainty set list {self._name!r} must "
                f"be at least {self._min_length}"
            )

    def _validate(self, value, single_item=False):
        """
        Validate item or sequence of items to be inserted into self.

        Parameters
        ----------
        value : object
            Object to validate.
        single_item : bool, optional
            Do not allow validation of iterables of objects
            (e.g. a list of ``UncertaintySet`` objects).
            The default is `False`.

        Raises
        ------
        TypeError
            If object passed is not of the appropriate type
            (``UncertaintySet``, or an iterable thereof).
        ValueError
            If object passed is (or contains) an ``UncertaintySet``
            whose dimension does not match that of other uncertainty
            sets in self.
        """
        if not single_item and isinstance(value, Iterable):
            for val in value:
                self._validate(val, single_item=True)
        else:
            validate_arg_type(
                self._name,
                value,
                UncertaintySet,
                "An `UncertaintySet` object",
                is_entry_of_arg=True,
            )
            if self._dim is None:
                # common dimension is now set
                self._dim = value.dim
            else:
                # ensure set added matches common dimension
                if value.dim != self._dim:
                    raise ValueError(
                        f"Uncertainty set list with name {self._name!r} "
                        f"contains UncertaintySet objects of dimension "
                        f"{self._dim}, but attempting to add set of dimension "
                        f"{value.dim}"
                    )

    @property
    def dim(self):
        """Dimension of all sets contained in self."""
        return self._dim


class BoxSet(UncertaintySet):
    """
    A hyper-rectangle (a.k.a "box").

    Parameters
    ----------
    bounds : (N, 2) array_like
        Lower and upper bounds for each dimension of the set.
    """

    def __init__(self, bounds):
        """Initialize self (see class docstring).

        """
        self.bounds = bounds

    @property
    def type(self):
        """
        str : Brief description of the type of the uncertainty set.
        """
        return "box"

    @property
    def bounds(self):
        """
        (N, 2) numpy.ndarray : Lower and upper bounds for each dimension
        of the set.

        The bounds of a ``BoxSet`` instance can be changed, such that
        the dimension of the set remains unchanged.
        """
        return self._bounds

    @bounds.setter
    def bounds(self, val):
        validate_array(
            arr=val,
            arr_name="bounds",
            dim=2,
            valid_types=valid_num_types,
            valid_type_desc="a valid numeric type",
            required_shape=[None, 2],
        )

        bounds_arr = np.array(val)

        for lb, ub in bounds_arr:
            if lb > ub:
                raise ValueError(
                    f"Lower bound {lb} exceeds upper bound {ub}"
                )

        # box set dimension is immutable
        if hasattr(self, "_bounds") and bounds_arr.shape[0] != self.dim:
            raise ValueError(
                "Attempting to set bounds of a box set of dimension "
                f"{self.dim} to a value of dimension {bounds_arr.shape[0]}"
            )
        self._bounds = np.array(val)

    @property
    def dim(self):
        """
        int : Dimension of the box set.
        """
        return len(self.bounds)

    @property
    def geometry(self):
        """
        Geometry of the box set. See the `Geometry` class
        documentation.
        """
        return Geometry.LINEAR

    @property
    def parameter_bounds(self):
        """
        Uncertain parameter value bounds for the box set.

        Returns
        -------
        : list(tuple)
            Box set bounds.
        """
        return [tuple(bound) for bound in self.bounds]

    def set_as_constraint(self, uncertain_params, **kwargs):
        """
        Construct a list of box contraints on a given sequence
        of uncertain parameter objects.

        Parameters
        ----------
        uncertain_params : list of Param or list of Var
            Uncertain parameter objects upon which the constraints
            are imposed.
        **kwargs : dict, optional
            Additional arguments. These arguments are currently
            ignored.

        Returns
        -------
        conlist : ConstraintList
            The constraints on the uncertain parameters.
        """
        conlist = ConstraintList()
        conlist.construct()

        set_i = list(range(len(uncertain_params)))

        for i in set_i:
            conlist.add(uncertain_params[i] >= self.bounds[i][0])
            conlist.add(uncertain_params[i] <= self.bounds[i][1])

        return conlist


class CardinalitySet(UncertaintySet):
    """
    A cardinality-constrained (a.k.a. "gamma") set.

    Parameters
    ----------
    origin : (N,) array_like
        Origin of the set (e.g. nominal uncertain parameter values).
    positive_deviation : (N,) array_like
        Maximal non-negative coordinate deviation from the origin
        in each dimension.
    gamma : numeric type
        Upper bound for the number of uncertain parameters which
        may realize their maximal deviations from the origin
        simultaneously.
    """

    def __init__(self, origin, positive_deviation, gamma):
        """Initialize self (see class docstring).

        """
        self.origin = origin
        self.positive_deviation = positive_deviation
        self.gamma = gamma

    @property
    def type(self):
        """
        str : Brief description of the type of the uncertainty set.
        """
        return "cardinality"

    @property
    def origin(self):
        """
        (N,) numpy.ndarray : Origin of the cardinality set
        (e.g. nominal parameter values).
        """
        return self._origin

    @origin.setter
    def origin(self, val):
        validate_array(
            arr=val,
            arr_name="origin",
            dim=1,
            valid_types=valid_num_types,
            valid_type_desc="a valid numeric type",
        )

        # dimension of the set is immutable
        val_arr = np.array(val)
        if hasattr(self, "_origin"):
            if val_arr.size != self.dim:
                raise ValueError(
                    "Attempting to set attribute 'origin' of cardinality "
                    f"set of dimension {self.dim} "
                    f"to value of dimension {val_arr.size}"
                )

        self._origin = val_arr

    @property
    def positive_deviation(self):
        """
        (N,) numpy.ndarray : Maximal coordinate deviations from the
        origin in each dimension. All entries are nonnegative.
        """
        return self._positive_deviation

    @positive_deviation.setter
    def positive_deviation(self, val):
        validate_array(
            arr=val,
            arr_name="positive_deviation",
            dim=1,
            valid_types=valid_num_types,
            valid_type_desc="a valid numeric type",
        )

        for dev_val in val:
            if dev_val < 0:
                raise ValueError(
                    f"Entry {dev_val} of attribute 'positive_deviation' "
                    f"is negative value"
                )

        val_arr = np.array(val)

        # dimension of the set is immutable
        if hasattr(self, "_origin"):
            if val_arr.size != self.dim:
                raise ValueError(
                    "Attempting to set attribute 'positive_deviation' of "
                    f"cardinality set of dimension {self.dim} "
                    f"to value of dimension {val_arr.size}"
                )

        self._positive_deviation = val_arr

    @property
    def gamma(self):
        """
        numeric type : Upper bound for the number of uncertain
        parameters which may maximally deviate from their respective
        origin values simultaneously. Must be a numerical value ranging
        from 0 to the set dimension.

        Note that mathematically, setting `gamma` to 0 reduces the set
        to a singleton containing the center, while setting `gamma` to
        the set dimension reduces the set to a hyperrectangle with
        bounds ``[origin, origin + positive_deviation]``.
        """
        return self._gamma

    @gamma.setter
    def gamma(self, val):
        validate_arg_type(
            "gamma", val, valid_num_types,
            "a valid numeric type", False,
        )
        if val < 0 or val > self.dim:
            raise ValueError(
                "Cardinality set attribute "
                f"'gamma' must be a real number between 0 and dimension "
                f"{self.dim} "
                f"(provided value {val})"
            )

        self._gamma = val

    @property
    def dim(self):
        """
        int : Dimension of the cardinality set.
        """
        return len(self.origin)

    @property
    def geometry(self):
        """
        Geometry of the cardinality set. See the `Geometry` class
        documentation.
        """
        return Geometry.LINEAR

    @property
    def parameter_bounds(self):
        """
        Uncertain parameter value bounds for the cardinality set.

        Returns
        -------
        parameter_bounds : list of tuples
            A list of 2-tuples of numerical values. Each tuple specifies
            the uncertain parameter bounds for the corresponding set
            dimension.
        """
        nom_val = self.origin
        deviation = self.positive_deviation
        gamma = self.gamma
        parameter_bounds = [(nom_val[i], nom_val[i] + min(gamma, 1) * deviation[i]) for i in range(len(nom_val))]
        return parameter_bounds

    def set_as_constraint(self, uncertain_params, **kwargs):
        """
        Construct a list of cardinality set constraints on
        a sequence of uncertain parameter objects.

        Parameters
        ----------
        uncertain_params : list of Param or list of Var
            Uncertain parameter objects upon which the constraints
            are imposed.
        **kwargs : dict
            Additional arguments. This dictionary should consist
            of a `model` entry, which maps to a `ConcreteModel`
            object representing the model of interest (parent model
            of the uncertain parameter objects).

        Returns
        -------
        conlist : ConstraintList
            The constraints on the uncertain parameters.
        """
        # === Ensure dimensions
        if len(uncertain_params) != len(self.origin):
               raise AttributeError("Dimensions of origin and uncertain_param lists must be equal.")

        model = kwargs['model']
        set_i = list(range(len(uncertain_params)))
        model.util.cassi = Var(set_i, initialize=0, bounds=(0, 1))

        # Make n equality constraints
        conlist = ConstraintList()
        conlist.construct()
        for i in set_i:
            conlist.add(self.origin[i] + self.positive_deviation[i] * model.util.cassi[i] == uncertain_params[i])

        conlist.add(sum(model.util.cassi[i] for i in set_i) <= self.gamma)

        return conlist

    def point_in_set(self, point):
        """
        Determine whether a given point lies in the cardinality set.

        Parameters
        ----------
        point : (N,) array-like
            Point (parameter value) of interest.

        Returns
        -------
        : bool
            True if the point lies in the set, False otherwise.
        """
        cassis = []
        for i in range(self.dim):
            if self.positive_deviation[i] > 0:
                cassis.append((point[i] - self.origin[i])/self.positive_deviation[i])

        if sum(cassi for cassi in cassis) <= self.gamma and \
            all(cassi >= 0 and cassi <= 1 for cassi in cassis):
            return True
        else:
            return False


class PolyhedralSet(UncertaintySet):
    """
    A bounded convex polyhedron or polytope.

    Parameters
    ----------
    lhs_coefficients_mat : (M, N) array_like
        Left-hand side coefficients for the linear
        inequality constraints defining the polyhedral set.
    rhs_vec : (M,) array_like
        Right-hand side values for the linear inequality
        constraints defining the polyhedral set.
    """

    def __init__(self, lhs_coefficients_mat, rhs_vec):
        """Initialize self (see class docstring).

        """
        # set attributes to copies of the originals
        self.coefficients_mat = lhs_coefficients_mat
        self.rhs_vec = rhs_vec

        # validate nonemptiness and boundedness here.
        # This check is only performed at construction.
        self._validate()

    def _validate(self):
        """
        Check polyhedral set attributes are such that set is nonempty
        and bounded. Currently, this method is invoked only at
        construction.

        Raises
        ------
        ValueError
            If set is empty, unbounded, or the check was not
            successfully completed due to numerical issues.
        """
        # solve LP to verify set is nonempty and bounded; check results
        res = sp.optimize.linprog(
            c=np.zeros(self.coefficients_mat.shape[1]),
            A_ub=self.coefficients_mat,
            b_ub=self.rhs_vec,
            method="simplex",
            bounds=(None, None),
        )
        if res.status == 1 or res.status == 4:
            raise ValueError(
                "Could not verify nonemptiness of the "
                "polyhedral set (`scipy.optimize.linprog(method=simplex)` "
                f" status {res.status}) "
            )
        elif res.status == 2:
            raise ValueError(
                "PolyhedralSet defined by 'coefficients_mat' and "
                "'rhs_vec' is empty. Check arguments"
            )
        elif res.status == 3:
            raise ValueError(
                "PolyhedralSet defined by 'coefficients_mat' and "
                "'rhs_vec: is unbounded. Check arguments"
            )

    @property
    def type(self):
        """
        str : Brief description of the type of the uncertainty set.
        """
        return "polyhedral"

    @property
    def coefficients_mat(self):
        """
        (M, N) numpy.ndarray : Coefficient matrix for the (linear)
        inequality constraints defining the polyhedral set.

        In tandem with the `rhs_vec` attribute, this matrix should
        be such that the polyhedral set is nonempty and bounded.
        Such a check is performed only at instance construction.
        """
        return self._coefficients_mat

    @coefficients_mat.setter
    def coefficients_mat(self, val):
        validate_array(
            arr=val,
            arr_name="coefficients_mat",
            dim=2,
            valid_types=valid_num_types,
            valid_type_desc="a valid numeric type",
            required_shape=None,
        )

        lhs_coeffs_arr = np.array(val)

        # check no change in set dimension
        if hasattr(self, "_coefficients_mat"):
            if lhs_coeffs_arr.shape[1] != self.dim:
                raise ValueError(
                    f"Polyhedral set attribute 'coefficients_mat' must have "
                    f"{self.dim} columns to match set dimension "
                    f"(provided matrix with {lhs_coeffs_arr.shape[1]} columns)"
                )

        # check shape match with rhs vector
        if hasattr(self, "_rhs_vec"):
            if lhs_coeffs_arr.shape[0] != self.rhs_vec.size:
                raise ValueError(
                    "PolyhedralSet attribute 'coefficients_mat' "
                    f"must have {self.rhs_vec.size} rows "
                    f"to match shape of attribute 'rhs_vec' "
                    f"(provided {lhs_coeffs_arr.shape[0]} rows)"
                )

        # === Matrix is not all zeros
        if np.all(np.isclose(lhs_coeffs_arr, 0)):
            raise ValueError(
                "PolyhedralSet attribute 'coefficients_mat' must have"
                "at least one nonzero entry"
            )

        self._coefficients_mat = lhs_coeffs_arr

    @property
    def rhs_vec(self):
        """
        (M,) numpy.ndarray : Right-hand side values (upper bounds) for
        the (linear) inequality constraints defining the polyhedral set.
        """
        return self._rhs_vec

    @rhs_vec.setter
    def rhs_vec(self, val):
        validate_array(
            arr=val,
            arr_name="rhs_vec",
            dim=1,
            valid_types=valid_num_types,
            valid_type_desc="a valid numeric type",
            required_shape=None,
        )

        rhs_vec_arr = np.array(val)

        # ensure shape of coefficients matrix
        # and rhs vec match
        if hasattr(self, "_coefficients_mat"):
            if len(val) != self.coefficients_mat.shape[0]:
                raise ValueError(
                    "PolyhedralSet attribute 'rhs_vec' "
                    f"must have {self.coefficients_mat.shape[0]} entries "
                    f"to match shape of attribute 'coefficients_mat' "
                    f"(provided {rhs_vec_arr.size} entries)"
                )

        self._rhs_vec = rhs_vec_arr

    @property
    def dim(self):
        """
        int : Dimension of the cardinality set.
        """
        return len(self.coefficients_mat[0])

    @property
    def geometry(self):
        """
        Geometry of the polyhedral set. See the `Geometry` class
        documentation.
        """
        return Geometry.LINEAR

    @property
    def parameter_bounds(self):
        """
        Uncertain parameter value bounds for the polyhedral set.

        Currently, an empty list, as the bounds cannot, in general,
        be computed without access to an optimization solver.
        """
        return []

    def set_as_constraint(self, uncertain_params, **kwargs):
        """
        Construct a list of polyhedral contraints on a given sequence
        of uncertain parameter objects.

        Parameters
        ----------
        uncertain_params : list of Param or list of Var
            Uncertain parameter objects upon which the constraints
            are imposed.
        **kwargs : dict, optional
            Additional arguments. These arguments are currently
            ignored.

        Returns
        -------
        conlist : ConstraintList
            The constraints on the uncertain parameters.
        """

        # === Ensure valid dimensions of lhs and rhs w.r.t uncertain_params
        if np.asarray(self.coefficients_mat).shape[1] != len(uncertain_params):
            raise AttributeError("Columns of coefficients_mat matrix "
                                 "must equal length of uncertain parameters list.")

        set_i = list(range(len(self.coefficients_mat)))

        conlist = ConstraintList()
        conlist.construct()

        for i in set_i:
            constraint = 0
            for j in range(len(uncertain_params)):
                constraint += float(self.coefficients_mat[i][j]) * uncertain_params[j]
            conlist.add(constraint <= float(self.rhs_vec[i]))

        return conlist

    @staticmethod
    def add_bounds_on_uncertain_parameters(model, config):
        """
        Specify the numerical bounds for each of a sequence of uncertain
        parameters, represented by Pyomo `Var` objects, in a modeling
        object. The numerical bounds are specified through the `.lb()`
        and `.ub()` attributes of the `Var` objects.

        Parameters
        ----------
        model : ConcreteModel
            Model of interest (parent model of the uncertain parameter
            objects for which to specify bounds).
        config : ConfigDict
            PyROS solver config.

        Notes
        -----
        This method is invoked in advance of a PyROS separation
        subproblem.
        """
        add_bounds_for_uncertain_parameters(model=model, config=config)


class BudgetSet(UncertaintySet):
    """
    A budget set.

    Parameters
    ----------
    budget_membership_mat : (M, N) array_like
        Incidence matrix of the budget constraints.
        Each row corresponds to a single budget constraint,
        and defines which uncertain parameters
        (which dimensions) participate in that row's constraint.
    rhs_vec : (N,) array_like
        Right-hand side values for the budget constraints.
    """

    def __init__(self, budget_membership_mat, rhs_vec):
        """Initialize self (see class docstring).

        """
        self.budget_membership_mat = budget_membership_mat
        self.budget_rhs_vec = rhs_vec

    @property
    def type(self):
        """
        str : Brief description of the type of the uncertainty set.
        """
        return "budget"

    @property
    def coefficients_mat(self):
        """
        (M + N, N) numpy.ndarray : Coefficient matrix of all polyhedral
        constraints defining the budget set. Composed from the incidence
        matrix used for defining the budget constraints and a
        coefficient matrix for individual uncertain parameter
        nonnegativity constraints.

        This attribute cannot be set. The budget constraint
        incidence matrix may be altered through the
        `budget_membership_mat` attribute.
        """
        neg_identity = -1 * np.identity(self.dim)

        return np.append(self.budget_membership_mat, neg_identity, axis=0)

    @property
    def rhs_vec(self):
        """
        (M + N,) numpy.ndarray : Right-hand side vector for polyhedral
        constraints defining the budget set. This also includes entries
        for nonnegativity constraints on the uncertain parameters.

        This attribute cannot be set. The right-hand
        sides for the budget constraints may be modified/accessed
        through the `budget_rhs_vec` attribute.
        """
        return np.append(self.budget_rhs_vec, np.zeros(self.dim))

    @property
    def budget_membership_mat(self):
        """
        (M, N) numpy.ndarray : Incidence matrix of the budget
        constraints.  Each row corresponds to a single budget
        constraint, and defines which uncertain parameters (which
        dimensions) participate in that row's constraint.
        """
        return self._budget_membership_mat

    @budget_membership_mat.setter
    def budget_membership_mat(self, val):
        validate_array(
            arr=val,
            arr_name="budget_membership_mat",
            dim=2,
            valid_types=valid_num_types,
            valid_type_desc="a valid numeric type",
            required_shape=None,
        )

        lhs_coeffs_arr = np.array(val)

        # check dimension match
        if hasattr(self, "_budget_membership_mat"):
            if lhs_coeffs_arr.shape[1] != self.dim:
                raise ValueError(
                    f"BudgetSet attribute 'budget_membership_mat' "
                    "must have "
                    f"{self.dim} columns to match set dimension "
                    f"(provided matrix with {lhs_coeffs_arr.shape[1]} columns)"
                )

        # check shape match with rhs vector
        if hasattr(self, "_budget_rhs_vec"):
            if lhs_coeffs_arr.shape[0] != self.budget_rhs_vec.size:
                raise ValueError(
                    "BudgetSet attribute 'budget_membership_mat' "
                    f"must have {self.budget_rhs_vec.size} rows "
                    f"to match shape of attribute 'budget_rhs_vec' "
                    f"(provided {lhs_coeffs_arr.shape[0]} rows)"
                )

        # validate entry values
        for row in lhs_coeffs_arr:
            if np.allclose(row, 0):
                raise ValueError(
                   "Each row of argument `budget_membership_mat` should "
                   "have at least one nonzero entry"
                )

            for entry in row:
                if not np.any(np.isclose(entry, [0, 1])):
                    raise ValueError(
                        f"Entry {entry} of argument `budget_membership_mat`"
                        " is not 0 or 1"
                    )

        self._budget_membership_mat = lhs_coeffs_arr

    @property
    def budget_rhs_vec(self):
        """
        (M,) numpy.ndarray : Right-hand side values (upper bounds) for
        the budget constraints.
        """
        return self._budget_rhs_vec

    @budget_rhs_vec.setter
    def budget_rhs_vec(self, val):
        validate_array(
            arr=val,
            arr_name="budget_rhs_vec",
            dim=1,
            valid_types=valid_num_types,
            valid_type_desc="a valid numeric type",
            required_shape=None,
        )

        rhs_vec_arr = np.array(val)

        # ensure shape of coefficients matrix
        # and rhs vec match
        if hasattr(self, "_budget_membership_mat"):
            if len(val) != self.budget_membership_mat.shape[0]:
                raise ValueError(
                    "Budget set attribute 'budget_rhs_vec' "
                    f"must have {self.budget_membership_mat.shape[0]} entries "
                    f"to match shape of attribute 'budget_membership_mat' "
                    f"(provided {rhs_vec_arr.size} entries)"
                )

        # ensure all entries are nonnegative
        for entry in rhs_vec_arr:
            if entry < 0:
                raise ValueError(
                    f"Entry {entry} of argument 'rhs_vec' is negative. "
                    "Ensure all entries are nonnegative"
                )

        self._budget_rhs_vec = rhs_vec_arr

    @property
    def dim(self):
        """
        int : Dimension of the budget set.
        """
        return self.budget_membership_mat.shape[1]

    @property
    def geometry(self):
        """
        Geometry of the budget set. See the `Geometry` class
        documentation.
        """
        return Geometry.LINEAR

    @property
    def parameter_bounds(self):
        """
        Uncertain parameter value bounds for the budget set.

        Returns
        -------
        parameter_bounds : list of tuples
            A list of 2-tuples of numerical values. Each tuple specifies
            the uncertain parameter bounds for the corresponding set
            dimension.
        """
        membership_mat = np.asarray(self.coefficients_mat)
        rhs_vec = self.rhs_vec
        parameter_bounds = []
        for i in range(membership_mat.shape[1]):
            col = column(membership_mat, i)
            ub = min(list(col[j] * rhs_vec[j] for j in range(len(rhs_vec))))
            lb = 0
            parameter_bounds.append((lb, ub))
        return parameter_bounds

    def set_as_constraint(self, uncertain_params, **kwargs):
        """
        Construct a list of budget contraints on a given sequence
        of uncertain parameter objects.

        Parameters
        ----------
        uncertain_params : list of Param or list of Var
            Uncertain parameter objects upon which the constraints
            are imposed.
        **kwargs : dict, optional
            Additional arguments. These arguments are currently
            ignored.

        Returns
        -------
        conlist : ConstraintList
            The constraints on the uncertain parameters.
        """

        # === Ensure matrix cols == len uncertain params
        if np.asarray(self.coefficients_mat).shape[1] != len(uncertain_params):
               raise AttributeError("Budget membership matrix must have compatible "
                                    "dimensions with uncertain parameters vector.")

        conlist = PolyhedralSet.set_as_constraint(self, uncertain_params)
        return conlist

    @staticmethod
    def add_bounds_on_uncertain_parameters(model, config):
        """
        Specify the numerical bounds for each of a sequence of uncertain
        parameters, represented by Pyomo `Var` objects, in a modeling
        object. The numerical bounds are specified through the `.lb()`
        and `.ub()` attributes of the `Var` objects.

        Parameters
        ----------
        model : ConcreteModel
            Model of interest (parent model of the uncertain parameter
            objects for which to specify bounds).
        config : ConfigDict
            PyROS solver config.

        Notes
        -----
        This method is invoked in advance of a PyROS separation
        subproblem.
        """
        # In this case, we use the UncertaintySet class method
        # because we have numerical parameter_bounds
        UncertaintySet.add_bounds_on_uncertain_parameters(model=model, config=config)


class FactorModelSet(UncertaintySet):
    """
    A factor model (a.k.a "net-alpha" model) set.

    Parameters
    ----------
    origin : (N,) array_like
        Uncertain parameter values around which deviations are
        restrained.
    number_of_factors : int
        Natural number representing the dimensionality of the
        space to which the set projects.
    psi_mat : (N, `number_of_factors`) array_like
        Matrix with nonnegative entries designating each
        uncertain parameter's contribution to each factor.
        Each row is associated with a separate uncertain parameter.
        Each column is associated with a separate factor.
    beta : numeric type
        Real value between 0 and 1 specifying the fraction of the
        independent factors that can simultaneously attain
        their extreme values.
    """

    def __init__(self, origin, number_of_factors, psi_mat, beta):
        """Initialize self (see class docstring).

        """
        self.origin = origin
        self.number_of_factors = number_of_factors
        self.beta = beta
        self.psi_mat = psi_mat

    @property
    def type(self):
        """
        str : Brief description of the type of the uncertainty set.
        """
        return "factor_model"

    @property
    def origin(self):
        """
        (N,) numpy.ndarray : Uncertain parameter values around which
        deviations are restrained.
        """
        return self._origin

    @origin.setter
    def origin(self, val):
        validate_array(
            arr=val,
            arr_name="origin",
            dim=1,
            valid_types=valid_num_types,
            valid_type_desc="a valid numeric type",
        )

        # dimension of the set is immutable
        val_arr = np.array(val)
        if hasattr(self, "_origin"):
            if val_arr.size != self.dim:
                raise ValueError(
                    "Attempting to set attribute 'origin' of cardinality "
                    f"set of dimension {self.dim} "
                    f"to value of dimension {val_arr.size}"
                )

        self._origin = val_arr

    @property
    def number_of_factors(self):
        """
        int : Natural number representing the dimensionality of the
        space to which the set projects.

        This attribute is immutable, and may only be set at
        object construction. Typically, the number of factors
        is significantly less than the set dimension, but no
        restriction to that end is imposed here.
        """
        return self._number_of_factors

    @number_of_factors.setter
    def number_of_factors(self, val):
        if hasattr(self, "_number_of_factors"):
            raise AttributeError("Attribute 'number_of_factors' is immutable")
        else:
            # validate type and value
            validate_arg_type("number_of_factors", val, int)
            if val < 1:
                raise ValueError(
                    "Attribute 'number_of_factors' must be a positive int"
                    f"(provided value {val})"
                )
        self._number_of_factors = val

    @property
    def psi_mat(self):
        """
        (N, `number_of_factors`) numpy.ndarray : Matrix designating each
        uncertain parameter's contribution to each factor. Each row is
        associated with a separate uncertain parameter. Each column with
        a separate factor.  Every entry of the matrix must be
        nonnegative.
        """
        return self._psi_mat

    @psi_mat.setter
    def psi_mat(self, val):
        validate_array(
            arr=val,
            arr_name="psi_mat",
            dim=2,
            valid_types=valid_num_types,
            valid_type_desc="a valid numeric type",
            required_shape=None,
        )

        psi_mat_arr = np.array(val)

        # validate shape (check it matches set dimensions)
        # origin and number of factors already set
        if psi_mat_arr.shape != (self.dim, self.number_of_factors):
            raise ValueError(
                "Psi matrix for factor model set "
                f"should be of shape {self.dim, self.number_of_factors} "
                f"to match the set and factor model space dimensions "
                f"(provided shape {psi_mat_arr.shape})"
            )

        # check values acceptable
        for column in psi_mat_arr.T:
            if np.allclose(column, 0):
                raise ValueError(
                    "Each column of attribute 'psi_mat' should have at least "
                    "one nonzero entry"
                )

            for entry in column:
                if entry < 0:
                    raise ValueError(
                        f"Entry {entry} of attribute 'psi_mat' is negative. "
                        "Ensure all entries are nonnegative"
                    )

        self._psi_mat = psi_mat_arr

    @property
    def beta(self):
        """
        numeric type : Real number ranging from 0 to 1 representing the
        fraction of the independent factors that can simultaneously
        attain their extreme values.

        Note that mathematically, setting `beta = 0` will enforce
        that as many factors will be above 0 as there will be below 0
        (i.e., "zero-net-alpha" model). Setting `beta = 1` produces the
        hyper-rectangle ``[origin - psi @ e, origin + psi @ e]``, where
        `e` is a vector of ones.
        """
        return self._beta

    @beta.setter
    def beta(self, val):
        if val > 1 or val < 0:
            raise ValueError(
                "Beta parameter must be a real number between 0 "
                f"and 1 inclusive (provided value {val})"
            )

        self._beta = val

    @property
    def dim(self):
        """
        int : Dimension of the factor model set.
        """
        return len(self.origin)

    @property
    def geometry(self):
        """
        Geometry of the factor model set. See the `Geometry` class
        documentation.
        """
        return Geometry.LINEAR

    @property
    def parameter_bounds(self):
        """
        Uncertain parameter value bounds for the factor model set.

        Returns
        -------
        parameter_bounds : list of tuples
            A list of 2-tuples of numerical values. Each tuple specifies
            the uncertain parameter bounds for the corresponding set
            dimension.
        """
        nom_val = self.origin
        psi_mat = self.psi_mat

        F = self.number_of_factors
        beta_F = self.beta * F
        floor_beta_F = math.floor(beta_F)
        parameter_bounds = []
        for i in range(len(nom_val)):
            non_decreasing_factor_row = sorted(psi_mat[i], reverse=True)
            # deviation = sum_j=1^floor(beta F) {psi_if_j} + (beta F - floor(beta F)) psi_{if_{betaF +1}}
            # because indexing starts at 0, we adjust the limit on the sum and the final factor contribution
            if beta_F - floor_beta_F == 0:
                deviation = sum(non_decreasing_factor_row[j] for j in range(floor_beta_F - 1))
            else:
                deviation = sum(non_decreasing_factor_row[j] for j in range(floor_beta_F - 1)) + (
                            beta_F - floor_beta_F) * psi_mat[i][floor_beta_F]
            lb = nom_val[i] - deviation
            ub = nom_val[i] + deviation
            if lb > ub:
                raise AttributeError("The computed lower bound on uncertain parameters must be less than or equal to the upper bound.")
            parameter_bounds.append((lb, ub))
        return parameter_bounds

    def set_as_constraint(self, uncertain_params, **kwargs):
        """
        Construct a list of factor model contraints on a given sequence
        of uncertain parameter objects.

        Parameters
        ----------
        uncertain_params : list of Param or list of Var
            Uncertain parameter objects upon which the constraints
            are imposed.
        **kwargs : dict
            Additional arguments. This dictionary should consist
            of a `model` entry, which maps to a `ConcreteModel`
            object representing the model of interest (parent model
            of the uncertain parameter objects).

        Returns
        -------
        conlist : ConstraintList
            The constraints on the uncertain parameters.
        """
        model = kwargs['model']

        # === Ensure dimensions
        if len(uncertain_params) != len(self.origin):
                raise AttributeError("Dimensions of origin and uncertain_param lists must be equal.")

        # Make F-dim cassi variable
        n = list(range(self.number_of_factors))
        model.util.cassi = Var(n, initialize=0, bounds=(-1, 1))

        conlist = ConstraintList()
        conlist.construct()

        disturbances = [sum(self.psi_mat[i][j] * model.util.cassi[j] for j in n)
                        for i in range(len(uncertain_params))]

        # Make n equality constraints
        for i in range(len(uncertain_params)):
            conlist.add(self.origin[i] + disturbances[i] == uncertain_params[i])
        conlist.add(sum(model.util.cassi[i] for i in n) <= +self.beta * self.number_of_factors)
        conlist.add(sum(model.util.cassi[i] for i in n) >= -self.beta * self.number_of_factors)
        return conlist


    def point_in_set(self, point):
        """
        Determine whether a given point lies in the factor model set.

        Parameters
        ----------
        point : (N,) array-like
            Point (parameter value) of interest.

        Returns
        -------
        : bool
            True if the point lies in the set, False otherwise.
        """
        inv_psi = np.linalg.pinv(self.psi_mat)
        diff = np.asarray(list(point[i] - self.origin[i] for i in range(len(point))))
        cassis = np.dot(inv_psi, np.transpose(diff))

        if abs(sum(cassi for cassi in cassis)) <= self.beta * self.number_of_factors and \
            all(cassi >= -1 and cassi <= 1 for cassi in cassis):
            return True
        else:
            return False


class AxisAlignedEllipsoidalSet(UncertaintySet):
    """
    An axis-aligned ellipsoid.

    Parameters
    ----------
    center : (N,) array_like
        Center of the ellipsoid.
    half_lengths : (N,) aray_like
        Semi-axis lengths of the ellipsoid.
    """

    def __init__(self, center, half_lengths):
        """Initialize self (see class docstring).

        """
        self.center = center
        self.half_lengths = half_lengths

    @property
    def type(self):
        """
        str : Brief description of the type of the uncertainty set.
        """
        return "ellipsoidal"

    @property
    def center(self):
        """
        (N,) numpy.ndarray : Center of the ellipsoid.
        """
        return self._center

    @center.setter
    def center(self, val):
        validate_array(
            arr=val,
            arr_name="center",
            dim=1,
            valid_types=valid_num_types,
            valid_type_desc="a valid numeric type",
            required_shape=None,
        )

        val_arr = np.array(val)

        # dimension of the set is immutable
        if hasattr(self, "_center"):
            if val_arr.size != self.dim:
                raise ValueError(
                    "Attempting to set attribute 'center' of "
                    f"AxisAlignedEllipsoidalSet of dimension {self.dim} "
                    f"to value of dimension {val_arr.size}"
                )

        self._center = val_arr

    @property
    def half_lengths(self):
        """
        (N,) numpy.ndarray : Semi-axis lengths.
        """
        return self._half_lengths

    @half_lengths.setter
    def half_lengths(self, val):
        validate_array(
            arr=val,
            arr_name="half_lengths",
            dim=1,
            valid_types=valid_num_types,
            valid_type_desc="a valid numeric type",
            required_shape=None,
        )

        val_arr = np.array(val)

        # dimension of the set is immutable
        if hasattr(self, "_center"):
            if val_arr.size != self.dim:
                raise ValueError(
                    "Attempting to set attribute 'half_lengths' of "
                    f"AxisAlignedEllipsoidalSet of dimension {self.dim} "
                    f"to value of dimension {val_arr.size}"
                )

        # ensure half-lengths are non-negative
        for half_len in val_arr:
            if half_len < 0:
                raise ValueError(
                    f"Entry {half_len} of 'half_lengths' "
                    "is negative. All half-lengths must be nonnegative"
                )

        self._half_lengths = val_arr

    @property
    def dim(self):
        """
        int : Dimension of the axis-aligned ellipsoidal set.
        """
        return len(self.center)

    @property
    def geometry(self):
        """
        Geometry of the axis-aligned ellipsoidal set.
        See the `Geometry` class documentation.
        """
        return Geometry.CONVEX_NONLINEAR

    @property
    def parameter_bounds(self):
        """
        Uncertain parameter value bounds for the axis-aligned
        ellipsoidal set.

        Returns
        -------
        parameter_bounds : list of tuples
            A list of 2-tuples of numerical values. Each tuple specifies
            the uncertain parameter bounds for the corresponding set
            dimension.
        """
        nom_value = self.center
        half_length =self.half_lengths
        parameter_bounds = [(nom_value[i] - half_length[i], nom_value[i] + half_length[i]) for i in range(len(nom_value))]
        return parameter_bounds

    def set_as_constraint(self, uncertain_params, model=None, config=None):
        """
        Construct a list of ellipsoidal constraints on a given sequence
        of uncertain parameter objects.

        Parameters
        ----------
        uncertain_params : {IndexedParam, IndexedVar, list of Param/Var}
            Uncertain parameter objects upon which the constraints
            are imposed. Indexed parameters are accepted, and
            are unpacked for constraint generation.
        **kwargs : dict, optional
            Additional arguments. These arguments are currently
            ignored.

        Returns
        -------
        conlist : ConstraintList
            The constraints on the uncertain parameters.
        """
        all_params = list()

        # expand all uncertain parameters to a list.
        # this accounts for the cases in which `uncertain_params`
        # consists of indexed model components,
        # or is itself a single indexed component
        if not isinstance(uncertain_params, (tuple, list)):
            uncertain_params = [uncertain_params]

        all_params = []
        for uparam in uncertain_params:
            all_params.extend(uparam.values())

        if len(all_params) != len(self.center):
            raise AttributeError(
                f"Center of ellipsoid is of dimension {len(self.center)},"
                f" but vector of uncertain parameters is of dimension"
                f" {len(all_params)}"
            )

        zip_all = zip(all_params, self.center, self.half_lengths)
        diffs_squared = list()

        # now construct the constraints
        conlist = ConstraintList()
        conlist.construct()
        for param, ctr, half_len in zip_all:
            if half_len > 0:
                diffs_squared.append((param - ctr) ** 2 / (half_len) ** 2)
            else:
                # equality constraints for parameters corresponding to
                # half-lengths of zero
                conlist.add(param == ctr)

        conlist.add(sum(diffs_squared) <= 1)

        return conlist


class EllipsoidalSet(UncertaintySet):
    """
    A general ellipsoid.

    Parameters
    ----------
    center : (N,) array-like
        Center of the ellipsoid.
    shape_matrix : (N, N) array-like
        A positive definite matrix characterizing the shape
        and orientation of the ellipsoid.
    scale : numeric type, optional
        Square of the factor by which to scale the semi-axes
        of the ellipsoid (i.e. the eigenvectors of the shape
        matrix). The default is `1`.
    """

    def __init__(self, center, shape_matrix, scale=1):
        """Initialize self (see class docstring).

        """
        self.center = center
        self.shape_matrix = shape_matrix
        self.scale = scale

    @property
    def type(self):
        """
        str : Brief description of the type of the uncertainty set.
        """
        return "ellipsoidal"

    @property
    def center(self):
        """
        (N,) numpy.ndarray : Center of the ellipsoid.
        """
        return self._center

    @center.setter
    def center(self, val):
        validate_array(
            arr=val,
            arr_name="center",
            dim=1,
            valid_types=valid_num_types,
            valid_type_desc="a valid numeric type",
            required_shape=None,
        )

        val_arr = np.array(val)

        # dimension of the set is immutable
        if hasattr(self, "_center"):
            if val_arr.size != self.dim:
                raise ValueError(
                    "Attempting to set attribute 'center' of "
                    f"AxisAlignedEllipsoidalSet of dimension {self.dim} "
                    f"to value of dimension {val_arr.size}"
                )

        self._center = val_arr

    @staticmethod
    def _verify_positive_definite(matrix):
        """
        Verify that a given symmetric square matrix is positive
        definite. An exception is raised at any point this
        verificiation ro

        Parameters
        ----------
        matrix : (N, N) array_like
            Candidate matrix.

        Raises
        ------
        ValueError
            If matrix is not symmetirc, not positive definite,
            or the square roots of the diagonal entries are
            not accessible.
        LinAlgError
            If matrix is not invertible.
        """
        matrix = np.array(matrix)

        if not np.allclose(matrix, matrix.T, atol=1e-8):
            raise ValueError("Shape matrix must be symmetric.")

        # Numpy raises LinAlgError if not invertible
        np.linalg.inv(matrix)

        # check positive semi-definite.
        # since also invertible, means positive definite
        eigvals = np.linalg.eigvals(matrix)
        if np.min(eigvals) < 0:
            raise ValueError(
                "Non positive-definite shape matrix "
                f"(detected eigenvalues {eigvals})"
            )

        # check roots of diagonal entries accessible
        # (should theoretically be true if positive definite)
        for diag_entry in np.diagonal(matrix):
            if np.isnan(np.power(diag_entry, 0.5)):
                raise ValueError(
                    "Cannot evaluate square root of the diagonal entry "
                    f"{diag_entry} of argument `shape_matrix`. "
                    "Check that this entry is nonnegative"
                )

    @property
    def shape_matrix(self):
        """
        (N, N) numpy.ndarray : A positive definite matrix characterizing
        the shape and orientation of the ellipsoid.
        """
        return self._shape_matrix

    @shape_matrix.setter
    def shape_matrix(self, val):
        validate_array(
            arr=val,
            arr_name="shape_matrix",
            dim=2,
            valid_types=valid_num_types,
            valid_type_desc="a valid numeric type",
            required_shape=None,
        )

        shape_mat_arr = np.array(val)

        # check matrix shape matches set dimension
        if hasattr(self, "_center"):
            if not all(size == self.dim for size in shape_mat_arr.shape):
                raise ValueError(
                    f"EllipsoidalSet attribute 'shape_matrix' "
                    f"must be a square matrix of size "
                    f"{self.dim} to match set dimension "
                    f"(provided matrix with shape {shape_mat_arr.shape})"
                )

        self._verify_positive_definite(shape_mat_arr)
        self._shape_matrix = shape_mat_arr

    @property
    def scale(self):
        """
        numeric type : Square of the factor by which to scale the
        semi-axes of the ellipsoid (i.e. the eigenvectors of the shape
        matrix).
        """
        return self._scale

    @scale.setter
    def scale(self, val):
        validate_arg_type(
            "scale", val, valid_num_types,
            "a valid numeric type", False,
        )
        if val < 0:
            raise ValueError(
                "EllipsoidalSet attribute "
                f"'scale' must be a non-negative real "
                f"(provided value {val})"
            )

        self._scale = val

    @property
    def dim(self):
        """
        int : Dimension of the ellipsoidal set.
        """
        return len(self.center)

    @property
    def geometry(self):
        """
        Geometry of the ellipsoidal set.
        See the `Geometry` class documentation.
        """
        return Geometry.CONVEX_NONLINEAR

    @property
    def parameter_bounds(self):
        """
        Uncertain parameter value bounds for the ellipsoidal
        set.

        Returns
        -------
        parameter_bounds : list of tuples
            A list of 2-tuples of numerical values. Each tuple specifies
            the uncertain parameter bounds for the corresponding set
            dimension.
        """
        scale = self.scale
        nom_value = self.center
        P = self.shape_matrix
        parameter_bounds = [(nom_value[i] - np.power(P[i][i] * scale, 0.5),
                             nom_value[i] + np.power(P[i][i] * scale, 0.5)) for i in range(self.dim)]
        return parameter_bounds

    def set_as_constraint(self, uncertain_params, **kwargs):
        """
        Construct a list of ellipsoidal constraints on a given sequence
        of uncertain parameter objects.

        Parameters
        ----------
        uncertain_params : {IndexedParam, IndexedVar, list of Param/Var}
            Uncertain parameter objects upon which the constraints
            are imposed. Indexed parameters are accepted, and
            are unpacked for constraint generation.
        **kwargs : dict, optional
            Additional arguments. These arguments are currently
            ignored.

        Returns
        -------
        conlist : ConstraintList
            The constraints on the uncertain parameters.
        """
        inv_covar = np.linalg.inv(self.shape_matrix)

        if len(uncertain_params) != len(self.center):
               raise AttributeError("Center of ellipsoid must be same dimensions as vector of uncertain parameters.")

        # Calculate row vector of differences
        diff = []
        # === Assume VarList uncertain_param_vars
        for idx, i in enumerate(uncertain_params):
            if uncertain_params[idx].is_indexed():
                for index in uncertain_params[idx]:
                    diff.append(uncertain_params[idx][index] - self.center[idx])
            else:
                diff.append(uncertain_params[idx] - self.center[idx])

        # Calculate inner product of difference vector and covar matrix
        product1 = [sum([x * y for x, y in zip(diff, column(inv_covar, i))]) for i in range(len(inv_covar))]
        constraint = sum([x * y for x, y in zip(product1, diff)])

        conlist = ConstraintList()
        conlist.construct()
        conlist.add(constraint <= self.scale)
        return conlist


class DiscreteScenarioSet(UncertaintySet):
    """
    A discrete set of finitely many uncertain parameter realizations
    (or scenarios).

    Parameters
    ----------
    scenarios : (M, N) array_like
        A sequence of M distinct uncertain parameter realizations.
    """

    def __init__(self, scenarios):
        """Initialize self (see class docstring).

        """
        # Standardize to list of tuples
        self.scenarios = scenarios

    @property
    def type(self):
        """
        str : Brief description of the type of the uncertainty set.
        """
        return "discrete"

    @property
    def scenarios(self):
        """
        list(tuple) : Uncertain parameter realizations comprising the
        set.  Each tuple is an uncertain parameter realization.

        Note that the `scenarios` attribute may be modified, but
        only such that the dimension of the set remains unchanged.
        """
        return self._scenarios

    @scenarios.setter
    def scenarios(self, val):
        validate_array(
            arr=val,
            arr_name="scenarios",
            dim=2,
            valid_types=valid_num_types,
            valid_type_desc="a valid numeric type",
            required_shape=None,
        )

        scenario_arr = np.array(val)
        if hasattr(self, "_scenarios"):
            if scenario_arr.shape[1] != self.dim:
                raise ValueError(
                    f"DiscreteScenarioSet attribute 'scenarios' must have "
                    f"{self.dim} columns to match set dimension "
                    f"(provided array-like with {scenario_arr.shape[1]} "
                    "columns)"
                )

        self._scenarios = [tuple(s) for s in val]

    @property
    def dim(self):
        """
        int : Dimension of the discrete scenario set.
        """
        return len(self.scenarios[0])

    @property
    def geometry(self):
        """
        Geometry of the discrete scenario set.
        See the `Geometry` class documentation.
        """
        return Geometry.DISCRETE_SCENARIOS

    @property
    def parameter_bounds(self):
        """
        Uncertain parameter value bounds for the discrete
        scenario set.

        Returns
        -------
        parameter_bounds : list of tuples
            A list of 2-tuples of numerical values. Each tuple specifies
            the uncertain parameter bounds for the corresponding set
            dimension.
        """
        parameter_bounds = [(min(s[i] for s in self.scenarios),
                             max(s[i] for s in self.scenarios)) for i in range(self.dim)]
        return parameter_bounds

    def is_bounded(self, config):
        """
        Return True if the uncertainty set is bounded, and False
        otherwise.

        By default, the discrete scenario set is bounded,
        as the entries of all uncertain parameter scenarios
        are finite.
        """
        return True

    def set_as_constraint(self, uncertain_params, **kwargs):
        """
        Construct a list of contraints on a given sequence
        of uncertain parameter objects.

        Parameters
        ----------
        uncertain_params : list of Param or list of Var
            Uncertain parameter objects upon which the constraints
            are imposed.
        **kwargs : dict, optional
            Additional arguments. These arguments are currently
            ignored.

        Returns
        -------
        conlist : ConstraintList
            The constraints on the uncertain parameters.
        """
        # === Ensure point is of correct dimensionality as the uncertain parameters
        dim = len(uncertain_params)
        if any(len(d) != dim for d in self.scenarios):
                raise AttributeError("All scenarios must have same dimensions as uncertain parameters.")

        conlist = ConstraintList()
        conlist.construct()

        for n in list(range(len(self.scenarios))):
            for i in list(range(len(uncertain_params))):
                conlist.add(uncertain_params[i] == self.scenarios[n][i])

        conlist.deactivate()
        return conlist

    def point_in_set(self, point):
        """
        Determine whether a given point lies in the discrete
        scenario setset.

        Parameters
        ----------
        point : (N,) array-like
            Point (parameter value) of interest.

        Returns
        -------
        : bool
            True if the point lies in the set, False otherwise.
        """
        # Round all double precision to a tolerance
        num_decimals = 8
        rounded_scenarios = list(list(round(num, num_decimals) for num in d) for d in self.scenarios)
        rounded_point = list(round(num, num_decimals) for num in point)

        return any(rounded_point==rounded_d for rounded_d in rounded_scenarios)


class IntersectionSet(UncertaintySet):
    """
    An intersection of a sequence of uncertainty sets, each of which
    is represented by an ``UncertaintySet`` object.

    Parameters
    ----------
    **uncertainty_sets : dict
        PyROS ``UncertaintySet`` objects of which to construct
        an intersection. At least two uncertainty sets must
        be provided. All sets must be of the same dimension.
    """

    def __init__(self, **unc_sets):
        """Initialize self (see class docstring).

        """
        self.all_sets = unc_sets

    @property
    def type(self):
        """
        str : Brief description of the type of the uncertainty set.
        """
        return "intersection"

    @property
    def all_sets(self):
        """
        UncertaintySetList :
            List of the uncertainty sets of which to take the
            intersection. Must be of minimum length 2.

        This attribute may be set through any iterable of
        `UncertaintySet` objects, and exhibits similar behavior
        to a ``list``.
        """
        return self._all_sets

    @all_sets.setter
    def all_sets(self, val):
        if isinstance(val, dict):
            the_sets = val.values()
        else:
            the_sets = list(val)

        # type validation, ensure all entries have same dimension
        all_sets = UncertaintySetList(
            iterable=the_sets,
            name="all_sets",
            min_length=2,
        )

        # set dimension is immutable
        if hasattr(self, "_all_sets"):
            if all_sets.dim != self.dim:
                raise ValueError(
                    "Attempting to set attribute 'all_sets' of an "
                    f"IntersectionSet of dimension {self.dim} to a sequence "
                    f"of sets of dimension {all_sets[0].dim}"
                )

        self._all_sets = all_sets

    @property
    def dim(self):
        """Dimension of the intersection set.

        """
        return self.all_sets[0].dim

    @property
    def geometry(self):
        """
        Geometry of the intersection set.
        See the `Geometry` class documentation.
        """
        return max(self.all_sets[i].geometry.value for i in range(len(self.all_sets)))

    @property
    def parameter_bounds(self):
        """
        Uncertain parameter value bounds for the intersection
        set.

        Currently, an empty list, as the bounds cannot, in general,
        be computed without access to an optimization solver.
        """
        return []

    def point_in_set(self, point):
        """
        Determine whether a given point lies in the intersection set.

        Parameters
        ----------
        point : (N,) array-like
            Point (parameter value) of interest.

        Returns
        -------
        : bool
            True if the point lies in the set, False otherwise.
        """
        if all(a_set.point_in_set(point=point) for a_set in self.all_sets):
            return True
        else:
            return False

    def is_empty_intersection(self, uncertain_params, nlp_solver):
        """
        Determine if intersection is empty.

        Arguments
        ---------
        uncertain_params : list of Param or list of Var
            List of uncertain parameter objects.
        nlp_solver : Pyomo SolverFactory object
            NLP solver.

        Returns
        -------
        is_empty_intersection : bool
            True if the intersection is certified to be empty,
            and False otherwise.
        """

        # === Non-emptiness check for the set intersection
        is_empty_intersection = True
        if any(a_set.type == "discrete" for a_set in self.all_sets):
            disc_sets = (a_set for a_set in self.all_sets if a_set.type == "discrete")
            disc_set = min(disc_sets, key=lambda x: len(x.scenarios))  # minimum set of scenarios
            # === Ensure there is at least one scenario from this discrete set which is a member of all other sets
            for scenario in disc_set.scenarios:
                if all(a_set.point_in_set(point=scenario) for a_set in self.all_sets):
                    is_empty_intersection = False
                    break
        else:
            # === Compile constraints and solve NLP
            m = ConcreteModel()
            m.obj = Objective(expr=0) # dummy objective required if using baron
            m.param_vars = Var(uncertain_params.index_set())
            for a_set in self.all_sets:
                m.add_component(a_set.type + "_constraints", a_set.set_as_constraint(uncertain_params=m.param_vars))
            try:
                res = nlp_solver.solve(m)
            except:
                raise ValueError("Solver terminated with an error while checking set intersection non-emptiness.")
            if check_optimal_termination(res):
                is_empty_intersection = False
        return is_empty_intersection

    # === Define pairwise intersection function
    @staticmethod
    def intersect(Q1, Q2):
        """
        Obtain the intersection of two uncertainty sets.

        Parameters
        ----------
        Q1, Q2 : UncertaintySet
            Operand uncertainty sets.

        Returns
        -------
        : DiscreteScenarioSet or IntersectionSet
            Intersection of the sets. A `DiscreteScenarioSet` is
            returned if both operand sets are `DiscreteScenarioSet`
            instances; otherwise, an `IntersectionSet` is returned.
        """
        constraints = ConstraintList()
        constraints.construct()

        for set in (Q1, Q2):
            other = Q1 if set is Q2 else Q2
            if set.type == "discrete":
                intersected_scenarios = []
                for point in set.scenarios:
                    if other.point_in_set(point=point):
                        intersected_scenarios.append(point)
                return DiscreteScenarioSet(scenarios=intersected_scenarios)

        # === This case is if both sets are continuous
        return IntersectionSet(set1=Q1, set2=Q2)

        return

    def set_as_constraint(self, uncertain_params, **kwargs):
        """
        Construct a list of contraints on a given sequence
        of uncertain parameter objects. In advance of constructing
        the constraints, a check is performed to determine whether
        the set is empty.

        Parameters
        ----------
        uncertain_params : list of Param or list of Var
            Uncertain parameter objects upon which the constraints
            are imposed.
        **kwargs : dict
            Additional arguments. Must contain a `config` entry,
            which maps to a `ConfigDict` containing an entry
            entitled `global_solver`. The `global_solver`
            key maps to an NLP solver, purportedly with global
            optimization capabilities.

        Returns
        -------
        conlist : ConstraintList
            The constraints on the uncertain parameters.

        Raises
        ------
        AttributeError
            If the intersection set is found to be empty.
        """
        try:
            nlp_solver = kwargs["config"].global_solver
        except:
            raise AttributeError("set_as_constraint for SetIntersection requires access to an NLP solver via"
                                 "the PyROS Solver config.")
        is_empty_intersection = self.is_empty_intersection(uncertain_params=uncertain_params, nlp_solver=nlp_solver)

        def _intersect(Q1, Q2):
            return self.intersect(Q1, Q2)

        if not is_empty_intersection:
            Qint = functools.reduce(_intersect, self.all_sets)

            if Qint.type == "discrete":
                return Qint.set_as_constraint(uncertain_params=uncertain_params)
            else:
                conlist = ConstraintList()
                conlist.construct()
                for set in Qint.all_sets:
                    for con in list(set.set_as_constraint(uncertain_params=uncertain_params).values()):
                        conlist.add(con.expr)
                return conlist
        else:
            raise AttributeError("Set intersection is empty, cannot proceed with PyROS robust optimization.")

    @staticmethod
    def add_bounds_on_uncertain_parameters(model, config):
        """
        Specify the numerical bounds for each of a sequence of uncertain
        parameters, represented by Pyomo `Var` objects, in a modeling
        object. The numerical bounds are specified through the `.lb()`
        and `.ub()` attributes of the `Var` objects.

        Parameters
        ----------
        model : ConcreteModel
            Model of interest (parent model of the uncertain parameter
            objects for which to specify bounds).
        config : ConfigDict
            PyROS solver config.

        Notes
        -----
        This method is invoked in advance of a PyROS separation
        subproblem.
        """

        add_bounds_for_uncertain_parameters(model=model, config=config)
        return
