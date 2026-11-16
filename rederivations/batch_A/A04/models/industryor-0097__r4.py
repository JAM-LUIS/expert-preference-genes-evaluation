#!/usr/bin/env python3
# Reading 4: both prices 9.15; demand must be met exactly.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pool0097 import main
main({"PA": 9.15, "PB": 9.15}, demand_equal=True)
