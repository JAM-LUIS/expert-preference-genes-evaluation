#!/usr/bin/env python3
"""unit_runner.py — run (case, configuration, repeat) units against a local Ollama server (E06).

  $ORGENE_PY runtime/unit_runner.py --run experiments/<run> --cases data/cases/<x>.jsonl --split-dir <dir> --split dev \
      --cond C0 C3L C3E --registry configs/model_registry.json --registry-entry qwen3-8b.main [--repeat 1] [--limit N]

Before any call: the E21 test gate (stage "execute", once per process), the interpreter check, the E19 registry
check (`tools/model_registry.py check --quick --entry <id>`), the local token counter (E09, default on) and a render
check of every round-0 request. Units run in a fixed order with every round-0 source before the units that reuse it;
E07's plan/execute replaces the order (random, seeded) and calls the same orgene.unit_exec.run_unit.
Exit status: 0 all units complete; 4 some unit incomplete (re-run the same command to redo them); 3 the
server's model identity changed during the run; other: refused.
See orgene/unit_exec.py for the unit record and the files written.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orgene.unit_exec import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
