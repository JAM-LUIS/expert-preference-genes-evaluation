# Incremental (marginal) piecewise profit: each extra unit in a range earns that range's unit profit.
# Concave in a maximization -> exact LP via segment variables. Units integer (pieces).
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report, relax_and_solve
BIG = None
segA = [(40, 10), (60, 9), (50, 8), (BIG, 7)]
segB = [(50, 6), (50, 4), (BIG, 3)]
segC = [(100, 5), (BIG, 4)]
m = pulp.LpProblem("io0045", pulp.LpMaximize)
def segs(name, s):
    return [pulp.LpVariable(f"{name}_s{i}", lowBound=0, upBound=w) for i, (w, p) in enumerate(s)]
sA, sB, sC = segs("A", segA), segs("B", segB), segs("C", segC)
A = pulp.LpVariable("A", lowBound=0, cat="Integer"); B = pulp.LpVariable("B", lowBound=0, cat="Integer"); C = pulp.LpVariable("C", lowBound=0, cat="Integer")
m += A == pulp.lpSum(sA); m += B == pulp.lpSum(sB); m += C == pulp.lpSum(sC)
m += pulp.lpSum(v*p for v, (w, p) in zip(sA, segA)) + pulp.lpSum(v*p for v, (w, p) in zip(sB, segB)) + pulp.lpSum(v*p for v, (w, p) in zip(sC, segC))
m += 1*A + 2*B + 1*C <= 100
m += 10*A + 4*B + 5*C <= 700
m += 3*A + 2*B + 1*C <= 400
solve_report(m)
relax_and_solve(m)
