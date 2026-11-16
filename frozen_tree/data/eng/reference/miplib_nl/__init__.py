"""PuLP translations of the MIPLIB-NL reference scripts (solve.py, gurobipy) of the selected instances (E22).

Each module exposes build(instance_dir) -> pulp.LpProblem. The translation keeps the variables, bounds, objective
and constraints of the instance's solve.py at the pinned commit; only the solver changes (CBC instead of Gurobi)
and pandas is replaced by the csv module. Solver-side options of solve.py (time limits, MIP focus, early stop
callbacks) are not part of the model and are not carried over. Isolation: gold material
(data/cases/README_ISOLATION.md).
"""
import csv
import json
import os


def load_instance(instance_dir):
    with open(os.path.join(instance_dir, "instance.json"), encoding="utf-8") as f:
        return json.load(f)


def data_path(instance_dir, inst, key):
    return os.path.normpath(os.path.join(instance_dir, inst["files"][key]["path"]))


def read_rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
