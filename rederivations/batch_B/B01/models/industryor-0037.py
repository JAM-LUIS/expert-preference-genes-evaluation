# Goals all attainable; model: maximize profit s.t. Process I time = 150 (capacity, exactly),
# Process II >= 70 (fully used, overtime allowed), A>=10, B>=15, profit>=10000. Units integer.
import pulp
from _common import solve_report
m = pulp.LpProblem("ior0037", pulp.LpMaximize)
A = pulp.LpVariable("A", lowBound=0, cat="Integer"); B = pulp.LpVariable("B", lowBound=0, cat="Integer")
m += 300*A + 450*B
m += 300*A + 450*B >= 10000
m += A >= 10
m += B >= 15
m += 4*A + 6*B == 150
m += 3*A + 2*B >= 70
solve_report(m, relax=True)
