# Input-output LP: production x_i, net exports e_i = x_i - internal use >= 0.
# GDP = value of exports at world prices - other imported goods. Labor in person-months.
import pulp
from _common import solve_report
G = ["steel","engine","elec","plastic"]
price = dict(zip(G,[500,1500,300,1200]))
# use[j][i] = units of good i needed per unit of good j
use = {"steel":{"engine":0.02,"plastic":0.01},
       "engine":{"steel":0.8,"elec":0.15,"plastic":0.11},
       "elec":{"steel":0.01,"engine":0.01,"plastic":0.05},
       "plastic":{"engine":0.03,"steel":0.2,"elec":0.05}}
imp = dict(zip(G,[250,300,50,300]))
lab = dict(zip(G,[6,12,6,24]))
m = pulp.LpProblem("ior0040", pulp.LpMaximize)
x = pulp.LpVariable.dicts("prod", G, lowBound=0)
e = pulp.LpVariable.dicts("export", G, lowBound=0)
m += pulp.lpSum(price[i]*e[i] for i in G) - pulp.lpSum(imp[j]*x[j] for j in G)
for i in G:
    m += e[i] == x[i] - pulp.lpSum(use[j].get(i,0)*x[j] for j in G)
m += x["engine"] <= 650000
m += x["plastic"] <= 60000
m += pulp.lpSum(lab[j]*x[j] for j in G) <= 830000
solve_report(m)
