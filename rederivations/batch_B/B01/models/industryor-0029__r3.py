# Reading 3: demand deviations allowed in both directions (over-recruitment allowed); report d3-.
import subprocess, sys, os
here = os.path.dirname(os.path.abspath(__file__))
print(subprocess.run([sys.executable, os.path.join(here, "industryor-0029.py"), "overfill"], capture_output=True, text=True).stdout)
