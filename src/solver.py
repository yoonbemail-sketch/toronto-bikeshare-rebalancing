"""Solver choice for every optimization model in the project.

Models are written once in PuLP, so they can be solved by either:
  - HiGHS  (default): open source, no licence, no model-size limit
  - Gurobi (option):  SOLVER=gurobi ./run_all.sh  (needs gurobipy and a licence;
                      the free restricted licence allows <= 2000 variables/constraints)
src/solver_check.py confirms both reach the same optimal objective.
"""
import os

import pulp

SOLVER = os.environ.get("SOLVER", "highs").lower()


def make(name=None, time_limit=None):
    name = (name or SOLVER).lower()
    if name == "highs":
        return pulp.HiGHS(msg=False, timeLimit=time_limit)
    if name == "gurobi":
        return pulp.GUROBI(msg=False, timeLimit=time_limit)
    raise SystemExit(f"Unknown SOLVER={name!r}; use 'highs' or 'gurobi'")


def available(name):
    try:
        return make(name).available()
    except Exception:
        return False


def solve(model, solver=None, time_limit=None):
    """Solve and return PuLP's stats (status, objective, best bound, size, time)."""
    stats = model.solve(solver or make(time_limit=time_limit))
    if not stats.has_solution:
        raise RuntimeError(f"{model.name}: no solution ({stats.status})")
    return stats


def gap(stats):
    """Relative MIP gap between the solution found and the best bound (0 = proven optimal)."""
    if stats.best_bound is None or stats.objective in (None, 0):
        return 0.0
    return abs(stats.objective - stats.best_bound) / abs(stats.objective)
