# Reading 2: integer servings.
import subprocess, sys, os
here = os.path.dirname(os.path.abspath(__file__))
print(subprocess.run([sys.executable, os.path.join(here, "mamo_complex_lp-0025.py"), "int"], capture_output=True, text=True).stdout)
