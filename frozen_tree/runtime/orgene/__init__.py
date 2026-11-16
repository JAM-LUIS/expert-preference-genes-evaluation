"""ORgene v5 runtime — staged, resumable pipeline for LLM optimization-modeling experiments.

Stages (each one is a CLI subcommand, each writes files, every stage can be re-run):
  cases     raw benchmark file  -> data/cases/<source>.jsonl        (canonical case records)
  split     cases               -> data/splits/<source>/            (frozen dev/test ids)
  requests  cases + condition   -> experiments/<run>/requests.<cond>.jsonl   (runner input)
  [model]   ollama_runner.py / api_runner.py                        (generation, resumable)
  validate  runner outputs      -> validated.<cond>.round<n>.jsonl + final.<cond>.jsonl (+ repair requests)
  score     final artifacts     -> results.<cond>.jsonl + metrics.<cond>.json
  report    all conditions      -> report.md

Standard library only, except the generated programs which need `pulp` (with CBC).
"""

__version__ = "5.0.0"
