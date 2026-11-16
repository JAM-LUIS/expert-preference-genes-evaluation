# Reading 2 (literal "visits two other cities"): start at city 1, visit exactly 2 of the other 3 cities, return.
# Full enumeration of all such tours.
import itertools
D = [[0, 10, 20, 12], [10, 0, 5, 10], [20, 5, 0, 8], [15, 12, 8, 0]]
best = None
for perm in itertools.permutations([1, 2, 3], 2):
    tour = (0,) + perm + (0,)
    L = sum(D[tour[k]][tour[k+1]] for k in range(len(tour)-1))
    print("tour", [c+1 for c in tour], L)
    if best is None or L < best[0]: best = (L, tour)
print("STATUS: Optimal")
print("FINAL_OBJECTIVE:", float(best[0]))
print("best tour:", [c+1 for c in best[1]])
