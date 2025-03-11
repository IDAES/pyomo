#  ___________________________________________________________________________
#
#  Pyomo: Python Optimization Modeling Objects
#  Copyright (c) 2008-2025
#  National Technology and Engineering Solutions of Sandia, LLC
#  Under the terms of Contract DE-NA0003525 with National Technology and
#  Engineering Solutions of Sandia, LLC, the U.S. Government retains certain
#  rights in this software.
#  This software is distributed under the 3-clause BSD License.
#  ___________________________________________________________________________

import enum
from pyomo.opt.results.container import MapContainer, ScalarType


#
# A coarse summary of how the solver terminated.
#
class SolverStatus(str, enum.Enum):
    ok = 'ok'  # Normal termination
    warning = 'warning'  # Termination with unusual condition
    error = 'error'  # Terminated internally with error
    aborted = 'aborted'  # Terminated due to external conditions
    #   (e.g. interrupts)
    unknown = 'unknown'  # An uninitialized value

    # Overloading __str__ is needed to match the behavior of the old
    # pyutilib.enum class (removed June 2020). There are spots in the
    # code base that expect the string representation for items in the
    # enum to not include the class name. New uses of enum shouldn't
    # need to do this.
    def __str__(self):
        return self.value


#
# A description of how the solver terminated
#
class TerminationCondition(str, enum.Enum):
    # UNKNOWN
    unknown = 'unknown'  # An uninitialized value
    # OK
    maxTimeLimit = 'maxTimeLimit'  # Exceeded maximum time limited allowed by user
    #    but having return a feasible solution
    maxIterations = 'maxIterations'  # Exceeded maximum number of iterations allowed
    #    by user (e.g., simplex iterations)
    minFunctionValue = (
        'minFunctionValue'  # Found solution smaller than specified function
    )
    #    value
    minStepLength = 'minStepLength'  # Step length is smaller than specified limit
    globallyOptimal = 'globallyOptimal'  # Found a globally optimal solution
    locallyOptimal = 'locallyOptimal'  # Found a locally optimal solution
    feasible = 'feasible'  # Found a solution that is feasible
    optimal = 'optimal'  # Found an optimal solution
    maxEvaluations = 'maxEvaluations'  # Exceeded maximum number of problem evaluations
    #    (e.g., branch and bound nodes)
    other = 'other'  # Other, uncategorized normal termination
    # WARNING
    unbounded = 'unbounded'  # Demonstrated that problem is unbounded
    infeasible = 'infeasible'  # Demonstrated that the problem is infeasible
    infeasibleOrUnbounded = (
        'infeasibleOrUnbounded'  # Problem is either infeasible or unbounded
    )
    invalidProblem = 'invalidProblem'  # The problem setup or characteristics are not
    #    valid for the solver
    intermediateNonInteger = (
        'intermediateNonInteger'  # A non-integer solution has been returned
    )
    noSolution = 'noSolution'  # No feasible solution found but infeasibility
    #    not proven
    # ERROR
    solverFailure = 'solverFailure'  # Solver failed to terminate correctly
    internalSolverError = 'internalSolverError'  # Internal solver error
    error = 'error'  # Other errors
    # ABORTED
    userInterrupt = 'userInterrupt'  # Interrupt signal generated by user
    resourceInterrupt = 'resourceInterrupt'  # Interrupt signal in resources used by
    #    optimizer
    licensingProblems = 'licensingProblems'  # Problem accessing solver license

    # Overloading __str__ is needed to match the behavior of the old
    # pyutilib.enum class (removed June 2020). There are spots in the
    # code base that expect the string representation for items in the
    # enum to not include the class name. New uses of enum shouldn't
    # need to do this.
    def __str__(self):
        return self.value

    @staticmethod
    def to_solver_status(tc):
        """Maps a TerminationCondition to SolverStatus based on enum value

        Parameters
        ----------
        tc: TerminationCondition

        Returns
        -------
        SolverStatus
        """
        if tc in {
            TerminationCondition.maxTimeLimit,
            TerminationCondition.maxIterations,
            TerminationCondition.minFunctionValue,
            TerminationCondition.minStepLength,
            TerminationCondition.globallyOptimal,
            TerminationCondition.locallyOptimal,
            TerminationCondition.feasible,
            TerminationCondition.optimal,
            TerminationCondition.maxEvaluations,
            TerminationCondition.other,
        }:
            return SolverStatus.ok
        if tc in {
            TerminationCondition.unbounded,
            TerminationCondition.infeasible,
            TerminationCondition.infeasibleOrUnbounded,
            TerminationCondition.invalidProblem,
            TerminationCondition.intermediateNonInteger,
            TerminationCondition.noSolution,
        }:
            return SolverStatus.warning
        if tc in {
            TerminationCondition.solverFailure,
            TerminationCondition.internalSolverError,
            TerminationCondition.error,
        }:
            return SolverStatus.error
        if tc in {
            TerminationCondition.userInterrupt,
            TerminationCondition.resourceInterrupt,
            TerminationCondition.licensingProblems,
        }:
            return SolverStatus.aborted
        return SolverStatus.unknown


def check_optimal_termination(results):
    """
    This function returns True if the termination condition for the solver
    is 'optimal', 'locallyOptimal', or 'globallyOptimal', and the status is 'ok'

    Parameters
    ----------
    results : Pyomo results object returned from solver.solve

    Returns
    -------
    `bool`
    """
    if results.solver.status == SolverStatus.ok and (
        results.solver.termination_condition == TerminationCondition.optimal
        or results.solver.termination_condition == TerminationCondition.locallyOptimal
        or results.solver.termination_condition == TerminationCondition.globallyOptimal
    ):
        return True
    return False


def assert_optimal_termination(results):
    """
    This function checks if the termination condition for the solver
    is 'optimal', 'locallyOptimal', or 'globallyOptimal', and the status is 'ok'
    and it raises a RuntimeError exception if this is not true.

    Parameters
    ----------
    results : Pyomo results object returned from solver.solve
    """
    if not check_optimal_termination(results):
        msg = (
            'Solver failed to return an optimal solution. '
            'Solver status: {}, Termination condition: {}'.format(
                results.solver.status, results.solver.termination_condition
            )
        )
        raise RuntimeError(msg)


class BranchAndBoundStats(MapContainer):
    def __init__(self):
        MapContainer.__init__(self)
        self.declare('number of bounded subproblems')
        self.declare('number of created subproblems')


class BlackBoxStats(MapContainer):
    def __init__(self):
        MapContainer.__init__(self)
        self.declare('number of function evaluations')
        self.declare('number of gradient evaluations')
        self.declare('number of iterations')


class SolverStatistics(MapContainer):
    def __init__(self):
        MapContainer.__init__(self)
        self.declare("branch_and_bound", value=BranchAndBoundStats(), active=False)
        self.declare("black_box", value=BlackBoxStats(), active=False)


class SolverInformation(MapContainer):
    def __init__(self):
        MapContainer.__init__(self)
        self.declare('name')
        self.declare('status', value=SolverStatus.ok)
        # Semantics: the integer return code from the shell in which the solver
        # is launched.
        self.declare('return_code')
        self.declare('message')
        self.declare('user_time', type=ScalarType.time)
        self.declare('system_time', type=ScalarType.time)
        self.declare('wallclock_time', type=ScalarType.time)
        # Semantics: The specific condition that caused the solver to
        # terminate.
        self.declare('termination_condition', value=TerminationCondition.unknown)
        # Semantics: A string printed by the solver that summarizes the
        # termination status.
        self.declare('termination_message')
        self.declare('statistics', value=SolverStatistics(), active=False)
