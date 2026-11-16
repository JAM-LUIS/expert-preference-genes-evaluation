#!/usr/bin/env python3
# Minimum number of courses covering 2 math, 2 OR, 2 CS with prerequisites.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import report
C = ["Calculus", "OperationsResearch", "DataStructures", "ManagementStatistics",
     "ComputerSimulation", "ComputerProgramming", "Forecasting"]
math_ = ["Calculus", "OperationsResearch", "DataStructures", "ManagementStatistics", "Forecasting"]
or_ = ["OperationsResearch", "ManagementStatistics", "ComputerSimulation", "Forecasting"]
cs_ = ["DataStructures", "ComputerSimulation", "ComputerProgramming"]
m = pulp.LpProblem("ior0055", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", C, cat="Binary")
m += pulp.lpSum(x[c] for c in C)
m += pulp.lpSum(x[c] for c in math_) >= 2
m += pulp.lpSum(x[c] for c in or_) >= 2
m += pulp.lpSum(x[c] for c in cs_) >= 2
m += x["ComputerSimulation"] <= x["ComputerProgramming"]
m += x["DataStructures"] <= x["ComputerProgramming"]
m += x["ManagementStatistics"] <= x["Calculus"]
m += x["Forecasting"] <= x["ManagementStatistics"]
report(m)
