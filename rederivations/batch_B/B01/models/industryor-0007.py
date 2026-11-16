# Main reading: cost is per truck-km (30 EUR/km), each truck carries up to 2 containers.
import pulp
from _common import solve_report
W = ["Verona","Perugia","Rome","Pescara","Taranto","Lamezia"]
P = ["Genoa","Venice","Ancona","Naples","Bari"]
sup = dict(zip(W, [10,12,20,24,18,40]))
dem = dict(zip(P, [20,15,25,33,21]))
D = {"Verona":[290,115,355,715,810],"Perugia":[380,340,165,380,610],"Rome":[505,530,285,220,450],
     "Pescara":[655,450,155,240,315],"Taranto":[1010,840,550,305,95],"Lamezia":[1072,1097,747,372,333]}
d = {(w,p): D[w][j] for w in W for j,p in enumerate(P)}
m = pulp.LpProblem("ior0007", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", d.keys(), lowBound=0, cat="Integer")
y = pulp.LpVariable.dicts("trucks", d.keys(), lowBound=0, cat="Integer")
m += pulp.lpSum(30 * d[k] * y[k] for k in d)
for w in W: m += pulp.lpSum(x[w,p] for p in P) <= sup[w]
for p in P: m += pulp.lpSum(x[w,p] for w in W) >= dem[p]
for k in d: m += x[k] <= 2 * y[k]
solve_report(m, relax=True)
