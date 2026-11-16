"""LLMOPT anchor (engineering item E18).

  adapter.py         two-step messages, response extraction, solver redirect, objective from the solve record
  prompts.py         the pinned upstream prompts (kept in vendor/, which git ignores; never distributed)
  templates.py       the GGUF chat template (and the Ollama Modelfile template, for the record) as Python ports; the
                     rendered /completion prompt; the local token counter over the GGUF
  run.py             driver: prepare -> q2f -> f2c -> execute -> score, on llama-server's native /completion
  template_ref.py    regenerates the Go / Jinja reference renderings used by the tests (no model)
The llama-server start-up and identity checks are shared with the ORLM anchor (baselines/llamacpp_server.py).
"""
