"""chromaticindex1024-7: the instance's solve.py is chromaticindex128-5's script (same graph generator, n = 1024)."""
from .chromaticindex128_5 import build as _build


def build(instance_dir):
    prob = _build(instance_dir)
    prob.name = "chromaticindex1024_7"
    return prob
