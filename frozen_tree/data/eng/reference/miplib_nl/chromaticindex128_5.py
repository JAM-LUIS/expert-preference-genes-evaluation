"""chromaticindex128-5: translation of the instance's solve.py (edge colouring with at most 4 colours of the graph
the script generates from n; minimise the number of colours used)."""
import pulp

from . import load_instance


def edges_of(n):
    edges = []

    def add(u, v):
        edges.append((u, v) if u < v else (v, u))

    for k in range(n):
        base = 12 * k
        c7 = [0, 1, 2, 3, 4, 5, 6]
        for i in range(len(c7)):
            add(base + c7[i], base + c7[(i + 1) % len(c7)])
        c5 = [7, 9, 11, 8, 10]
        for i in range(len(c5)):
            add(base + c5[i], base + c5[(i + 1) % len(c5)])
        for a, b in [(0, 7), (2, 8), (5, 10), (6, 11)]:
            add(base + a, base + b)
        if k == 0:
            add(base + 4, base + 9)
        else:
            add(base + 3, base + 9)
        if k > 0:
            add(base + 4, 12 * (k - 1) + 1)
    return sorted(set(edges))


def build(instance_dir):
    inst = load_instance(instance_dir)
    edges = edges_of(inst["parameters"]["n"])
    adj = {}
    for e in edges:
        adj.setdefault(e[0], []).append(e)
        adj.setdefault(e[1], []).append(e)
    colors = range(4)
    prob = pulp.LpProblem("chromaticindex128_5", pulp.LpMinimize)
    x = {(e, c): pulp.LpVariable(f"x_{e[0]}_{e[1]}_{c}", cat=pulp.LpBinary) for e in edges for c in colors}
    u = {c: pulp.LpVariable(f"u_{c}", cat=pulp.LpBinary) for c in colors}
    prob += pulp.lpSum(u.values())
    for e in edges:
        prob += pulp.lpSum(x[e, c] for c in colors) == 1, f"edge_color_{e[0]}_{e[1]}"
    for v in adj:
        for c in colors:
            prob += pulp.lpSum(x[e, c] for e in adj[v]) <= u[c], f"vertex_{v}_color_{c}"
    return prob
