#!/usr/bin/env python3
# Reading 2: extra cost charged once per pattern used (k/10 for the k-th most used pattern).
import runpy, sys, os
sys.argv = [sys.argv[0], "onetime"]
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "industryor-0096.py"), run_name="__main__")
