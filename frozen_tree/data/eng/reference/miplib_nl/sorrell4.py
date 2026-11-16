"""sorrell4: translation of the instance's solve.py (largest set of n-bit words whose pairwise longest common
subsequence stays below the threshold)."""
import pulp

from . import load_instance


def lcs(a, b):
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            dp[i][j] = dp[i - 1][j - 1] + 1 if a[i - 1] == b[j - 1] else max(dp[i - 1][j], dp[i][j - 1])
    return dp[m][n]


def build(instance_dir):
    p = load_instance(instance_dir)["parameters"]
    nb, thr = p["n_bits"], p["lcs_threshold"]
    seqs = [format(i, f"0{nb}b") for i in range(2 ** nb)]
    prob = pulp.LpProblem("sorrell4", pulp.LpMaximize)
    x = [pulp.LpVariable(f"x_{i}", cat=pulp.LpBinary) for i in range(len(seqs))]
    prob += pulp.lpSum(x)
    for i in range(len(seqs)):
        for j in range(i + 1, len(seqs)):
            if lcs(seqs[i], seqs[j]) >= thr:
                prob += x[i] + x[j] <= 1, f"conflict_{i}_{j}"
    return prob
