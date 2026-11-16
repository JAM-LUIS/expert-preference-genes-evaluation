# Reading 2: exactly two methods are chosen and each chosen method makes at least one trip.
import subprocess, sys, os
here = os.path.dirname(os.path.abspath(__file__))
print(subprocess.run([sys.executable, os.path.join(here, "industryor-0039.py"), "exact"], capture_output=True, text=True).stdout)
