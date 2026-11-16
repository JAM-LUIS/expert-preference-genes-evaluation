#!/usr/bin/env python3
"""Short CPU-only process-topology probe; never opens model/data endpoints."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

time.sleep(0.2)  # allow caffeinate's helper to appear before the single process snapshot
pid, parent = os.getpid(), os.getppid()
rows = []
for line in subprocess.check_output(["ps", "ax", "-o", "pid=,ppid=,command="], text=True).splitlines():
    fields = line.strip().split(None, 2)
    if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
        child, ppid = int(fields[0]), int(fields[1])
        if child in (pid, parent) or ppid == pid:
            rows.append({"pid": child, "ppid": ppid, "executable": Path(fields[2].split()[0]).name,
                         "is_caffeinate": Path(fields[2].split()[0]).name == "caffeinate"})
out = {"driver_pid": pid, "driver_parent": parent, "related_processes": rows, "model_calls": 0}
Path(sys.argv[1]).write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out))
