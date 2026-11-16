#!/usr/bin/env python3
# Reading 2: the extra cost applies to every raw pipe cut with that pattern
# (each pipe costs 1.1 under the most used pattern, 1.2 under the second, ...).
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _cut_common import run
run(per_pipe_surcharge=True)
