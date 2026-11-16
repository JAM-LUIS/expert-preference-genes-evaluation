# Reading 2: same lexicographic model; reported value = number of assigned people NOT in their preferred city.
import subprocess, sys, os, re
here = os.path.dirname(os.path.abspath(__file__))
out = subprocess.run([sys.executable, os.path.join(here, "industryor-0029.py")], capture_output=True, text=True).stdout
st = re.search(r"^STATUS: (.*)$", out, re.M).group(1)
ss = re.search(r"^SOLUTION_STATUS: (.*)$", out, re.M).group(1)
v = re.search(r"assigned not in preferred city: (\S+)", out).group(1)
print("STATUS:", st); print("SOLUTION_STATUS:", ss); print("FINAL_OBJECTIVE:", v)
