#!/usr/bin/env python3
# Reading 1 (main, literal): each pattern in use incurs a one-off extra cost of rank/10 raw pipes
# (most used 0.1, second 0.2, ...). Cost unit = value of one raw pipe.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _cut_common import run
run(per_pipe_surcharge=False)
