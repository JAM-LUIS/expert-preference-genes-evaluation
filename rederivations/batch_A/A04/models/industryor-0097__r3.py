#!/usr/bin/env python3
# Reading 3: prices 9 and 15; demand must be met exactly (100 t and 200 t).
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pool0097 import main
main({"PA": 9.0, "PB": 15.0}, demand_equal=True)
