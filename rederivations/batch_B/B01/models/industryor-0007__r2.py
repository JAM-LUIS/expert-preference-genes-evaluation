# Reading 2: cost of 30 EUR per km per container (truck capacity ignored for cost).
import pulp
from _common import solve_report
W = ["Verona","Perugia","Rome","Pescara","Taranto","Lamezia"]
P = ["Genoa","Venice","Ancona","Naples","Bari"]
sup = dict(zip(W, [10,12,20,24,18,40]))
dem = dict(zip(P, [20,15,25,33,21]))
D = {"Verona":[290,115,355,715,810],"Perugia":[380,340,165,380,610],"Rome":[505,530,285,220,450],
     "Pescara":[655,450,155,240,315],"Taranto":[1010,840,550,305,95],"Lamezia":[1072,1097,747,372,333]}
d = {(w,p): D[w][j] for w in W for j,p in enumerate(P)}
m = pulp.LpProblem("ior0007_r2", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", d.keys(), lowBound=0, cat="Integer")
m += pulp.lpSum(30 * d[k] * x[k] for k in d)
for w in W: m += pulp.lpSum(x[w,p] for p in P) <= sup[w]
for p in P: m += pulp.lpSum(x[w,p] for w in W) >= dem[p]
solve_report(m)
