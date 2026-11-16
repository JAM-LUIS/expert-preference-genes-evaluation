#!/usr/bin/env python3
"""ORLM anchor adapter (engineering item E17): the published ORLM-LLaMA-3-8B checkpoint on the same cases, executor
and scoring script as the main configurations.

    python baselines/orlm_adapter.py requests --cases data/cases/<source>.jsonl --split-dir data/splits/<source> \
        --split dev --run experiments/<run>
    python baselines/orlm_adapter.py generate --run experiments/<run> --gguf <path to the F16 GGUF> --launch \
        [--allow-pending]            # llama-server started by the adapter with the registry entry's settings
    python baselines/orlm_adapter.py execute  --run experiments/<run>        # baselines interpreter, solve recorder
    python baselines/orlm_adapter.py score    --run experiments/<run> --cases data/cases/<source>.jsonl

What is taken from ORLM (github.com/Cardinal-Operations/ORLM at 33bc47d0a1d1710d24ab839118bdf4cb89b9e31b,
Apache License 2.0; the three pieces below are copied or re-implemented from it and marked where they appear):
  - the completion prompt TEMPLATE_q2mc_en and its use `TEMPLATE.replace("{Question}", q.strip()).strip()`
    (eval/generate.py lines 11-18 and 36); greedy decoding with stop "</s>" (lines 45-48);
  - the code extraction: the first ```python block, up to the next ``` (eval/execute.py lines 94-114), including
    its behaviour on an unclosed block (the slice then ends one character early);
  - the post-processing line ADD_SCRIPT (eval/execute.py line 10), run verbatim, and the official scoring: both
    values rounded to integers, relative error <= 0.05, "No Best Solution" matched as a string (lines 182-198, 287).

Generation. llama-server's native /completion (orgene.backends.llamacpp.LlamaCppCompletionBackend) sends the prompt
verbatim, greedy, with every setting of the registry entry `orlm-llama3-8b.anchor` (configs/model_registry.json).
Why llama-server and not Ollama's raw mode: the Ollama service on the run host keeps its KV cache in q8_0 with flash
attention for every model and cannot be reconfigured here, while llama-server is started per run with a 16-bit KV
cache (the official vLLM run keeps it in 16 bits); `cache_prompt: false` with one slot and no RAM prompt cache makes
every request evaluate its whole prompt without reloading the 16 GB model for each call (Ollama's keep_alive 0); and
the server echoes the sampling settings it applied, which are checked against what was sent. `--launch` starts the
server from the entry's `identity.server` block (context 8192, one slot, KV f16, ...), refuses when Ollama holds a
model, and stops the server afterwards. The GGUF is hashed at start and must equal the entry's digest.

Execution. The extracted program gets the harness HARNESS appended (it never calls a solver): it first runs the
official ADD_SCRIPT verbatim in the program's namespace, then prints one `ORGENE_HARNESS:` line and the protocol
lines of the other configurations, read from the solved COPT model (the global `model`, as ADD_SCRIPT assumes;
otherwise the only COPT model among the globals):
    STATUS: <COPT status mapped by COPT_STATUS_LABELS: Optimal, Infeasible, Unbounded, ...>
    FINAL_OBJECTIVE: <model.objval when the status is OPTIMAL, else NA>
The program runs with the baselines interpreter (ORGENE_BASELINES_PY, default ~/venvs/baselines/bin/python) under the
solve recorder (execute.run_program, 60 s as for every configuration).

Scoring. The main columns come from pipeline.score_condition, unchanged (same tolerance tiers, reference overrides
and misreport flags as every configuration). The ORLM official column is added to the same result rows
(`correct_orlm_official`, and `correct_orlm_official_original_ref` against the original reference) and to
metrics.ORLM.json under `orlm`.

Every stage passes the E21 test gate. A registry entry marked "status": "pending" (settings not yet fixed for the
freeze; model_registry.entry_pending) is used only with --allow-pending and never for sealed (test) cases. No stage
prints problem text.
"""
import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = os.path.join(ROOT, "runtime")
for _p in (RUNTIME, os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import llamacpp_server as LS  # noqa: E402  (server start-up and identity checks, shared with the LLMOPT anchor)

from orgene import configs as CF  # noqa: E402
from orgene import data as D  # noqa: E402
from orgene import freeze as FZ  # noqa: E402
from orgene import model_registry as MR  # noqa: E402
from orgene import pipeline as P  # noqa: E402
from orgene import refs as R  # noqa: E402
from orgene import runner as RN  # noqa: E402
from orgene import split as S  # noqa: E402
from orgene.backends.base import BackendError, now_iso  # noqa: E402
from orgene.backends.llamacpp import LlamaCppCompletionBackend  # noqa: E402
from orgene.conditions import read_jsonl, write_jsonl  # noqa: E402
from orgene.execute import run_program  # noqa: E402
from orgene.model_snapshot import DEFAULT_BASELINES_PY, baselines_env  # noqa: E402
from orgene.paths import rel, sanitize_argv  # noqa: E402

ADAPTER_SCHEMA = "orgene.r1.orlm_adapter.v1"
COND = "ORLM"
ANCHOR = "orlm"
DEFAULT_ENTRY = "orlm-llama3-8b.anchor"
DEFAULT_REGISTRY = os.path.join(ROOT, "configs", "model_registry.json")
BACKEND_KIND = "llamacpp_completion"
ORLM_SOURCE = "github.com/Cardinal-Operations/ORLM @ 33bc47d0a1d1710d24ab839118bdf4cb89b9e31b (Apache-2.0)"
EXEC_TIMEOUT = 60  # the executor timeout of every configuration (model registry: execution.timeout_s)

# ORLM eval/generate.py lines 11-18 (Apache-2.0), verbatim.
TEMPLATE_Q2MC_EN = r"""
Below is an operations research question. Build a mathematical model and corresponding python code using `coptpy` that appropriately addresses the question.

# Question:
{Question}

# Response:
"""
# ORLM eval/execute.py line 10 (Apache-2.0), verbatim.
ORLM_ADD_SCRIPT = '\nif model.status == COPT.OPTIMAL:\n    print(f"Just print the best solution: {model.objval}")\nelse:\n    print("No Best Solution")'
OFFICIAL_MARKER = "Just print the best solution:"
NO_BEST_SOLUTION = "No Best Solution"
ORLM_OFFICIAL_TOL = 0.05  # eval/execute.py line 287, --numerical_err_tolerance default

# COPT status constant -> the STATUS word printed. Words follow PuLP's vocabulary where one exists (Optimal, Infeasible,
# Unbounded); every word normalises (misreport.canonical_status) to the normalised constant name, so the printed status
# matches the solve recorder's record of the same solve (INF_OR_UNB through the recorder's alias).
COPT_STATUS_LABELS = (
    ("OPTIMAL", "Optimal"), ("INFEASIBLE", "Infeasible"), ("UNBOUNDED", "Unbounded"),
    ("INF_OR_UNB", "Infeasible or Unbounded"), ("UNSTARTED", "Unstarted"), ("NUMERICAL", "Numerical"),
    ("NODELIMIT", "Node Limit"), ("IMPRECISE", "Imprecise"), ("TIMEOUT", "Timeout"), ("UNFINISHED", "Unfinished"),
    ("INTERRUPTED", "Interrupted"), ("ITERLIMIT", "Iter Limit"), ("LOCAL_OPTIMAL", "Local Optimal"),
    ("LOCAL_INFEASIBLE", "Local Infeasible"),
)
HARNESS_MARKER = "ORGENE_HARNESS:"

_HARNESS_TEMPLATE = '''

# ---- appended by the evaluation harness (ORLM anchor, E17); not part of the model's answer ----
_ORGENE_ORLM_ADD_SCRIPT = __ADD_SCRIPT__
_ORGENE_COPT_STATUS_LABELS = __LABELS__


def _orgene_harness_report():
    import json as _json
    import sys as _sys
    _g = globals()
    _note = {"target": None, "official_add_script": None}

    def _is_copt_model(_o):
        _t = type(_o)
        # coptpy's classes are compiled into a module named `coptcore` (coptpy 8.0.7: Model.__module__ == "coptcore")
        return _t.__name__ == "Model" and str(getattr(_t, "__module__", "") or "").split(".")[0] in ("coptpy", "coptcore")

    # (1) the official ORLM post-processing, verbatim, in the program's own namespace
    try:
        exec(compile(_ORGENE_ORLM_ADD_SCRIPT, "<orlm-add-script>", "exec"), _g)
        _note["official_add_script"] = "ok"
    except Exception as _e:
        _note["official_add_script"] = type(_e).__name__
    # (2) the protocol lines of the other configurations, read from the solved COPT model (no solver call)
    _m = _g.get("model")
    if _is_copt_model(_m):
        _note["target"] = "model"
    else:
        _found = {}
        for _k, _v in list(_g.items()):
            if not _k.startswith("_orgene") and _is_copt_model(_v):
                _found.setdefault(id(_v), (_k, _v))
        if len(_found) == 1:
            (_k, _m), = _found.values()
            _note["target"] = "global:" + _k
        else:
            _m = None
            _note["target"] = "ambiguous" if _found else "none"
    _lines = []
    if _m is not None:
        try:
            _st = _m.status
            _copt = getattr(_sys.modules.get("coptpy"), "COPT", None)
            _codes = {}
            for _name, _label in _ORGENE_COPT_STATUS_LABELS:
                _v = getattr(_copt, _name, None)
                if isinstance(_v, int) and _v not in _codes:
                    _codes[_v] = (_name, _label)
            _name, _label = _codes.get(_st, (None, str(_st)))
            _note["status_code"] = _st if isinstance(_st, int) else None
            _obj = repr(float(_m.objval)) if _name == "OPTIMAL" else "NA"
            _lines = ["STATUS: " + _label, "FINAL_OBJECTIVE: " + _obj]
        except Exception as _e:
            _note["error"] = type(_e).__name__
            _lines = []
    print("ORGENE_HARNESS: " + _json.dumps(_note, sort_keys=True))
    for _l in _lines:
        print(_l)


try:
    _orgene_harness_report()
except Exception as _orgene_e:  # never let the harness change the program's exit status
    print("ORGENE_HARNESS: " + __import__("json").dumps({"error": type(_orgene_e).__name__}))
'''
HARNESS = (_HARNESS_TEMPLATE.replace("__ADD_SCRIPT__", repr(ORLM_ADD_SCRIPT))
           .replace("__LABELS__", repr(COPT_STATUS_LABELS)))

# llama-server launch settings the registry entry must fix (identity.server); see server_argv()
SERVER_KEYS = LS.SERVER_KEYS
# stdout / stderr of COPT when the problem exceeds the size limits of COPT's license-free mode
COPT_SIZE_LIMIT_TEXT = "size is limited to"
COPT_NO_LICENSE_TEXT = "No license found"


class Refused(SystemExit):
    """A stage refuses to run (nothing was sent to a model, nothing executed)."""

    def __init__(self, msg):
        super().__init__(f"[orlm] refused: {msg}")


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


file_sha256 = LS.file_sha256


TEMPLATE_SHA256 = sha256_text(TEMPLATE_Q2MC_EN)
ADD_SCRIPT_SHA256 = sha256_text(ORLM_ADD_SCRIPT)
HARNESS_SHA256 = sha256_text(HARNESS)


# ----------------------------------------------------------------------------------------------------- prompt / code


def orlm_prompt(question):
    """The official ORLM completion prompt for one problem text (eval/generate.py line 36)."""
    return TEMPLATE_Q2MC_EN.replace("{Question}", question.strip()).strip()


def extract_code(text):
    """The official extraction (eval/execute.py lines 94-114): the first ```python block up to the next ```.

    Returns (script or None, info). info: ok, reason (no_python_block | empty_python_block), block_closed (False when
    the block has no closing fence: the official slice then drops the answer's last character, kept as it is),
    n_python_fences (a second block is ignored, as officially)."""
    text = text or ""
    info = {"method": "orlm_official_first_python_block", "n_python_fences": text.count("```python")}
    start = text.find("```python")
    if start == -1:
        return None, dict(info, ok=False, reason="no_python_block", block_closed=None)
    end = text.find("```", start + 9)
    script = text[start:end].replace("```python", "")
    info["block_closed"] = end != -1
    if script.strip() == "":
        return None, dict(info, ok=False, reason="empty_python_block")
    return script, dict(info, ok=True, reason=None)


def build_program(script):
    """The program that is executed: the extracted script, then the harness (which never calls a solver)."""
    return script + HARNESS


def parse_harness(stdout):
    """The harness note (last `ORGENE_HARNESS:` line), or None when the harness did not run."""
    note = None
    for line in (stdout or "").splitlines():
        if line.startswith(HARNESS_MARKER):
            try:
                note = json.loads(line[len(HARNESS_MARKER):].strip())
            except ValueError:
                note = {"error": "unparsable_note"}
    return note


def copt_flags(ex):
    out = ((ex or {}).get("stdout_tail") or "") + "\n" + ((ex or {}).get("stderr_tail") or "")
    return {"size_limited": COPT_SIZE_LIMIT_TEXT in out, "no_license_notice": COPT_NO_LICENSE_TEXT in out}


# ----------------------------------------------------------------------------------------------------- official score


def official_prediction(ex, harness):
    """What ORLM's eval/execute.py would have read from this run: (prediction, state).

    prediction: the text after "Just print the best solution:" up to the line end, "No Best Solution", or None.
    A run that timed out or exited non-zero gives None (the official subprocess.run(check=True) fails); so does a run
    where ADD_SCRIPT itself raised (the harness caught it; appended officially, it would have ended the program).
    Only the kept stdout tail is searched; the ADD_SCRIPT line is always inside it (only the harness lines follow)."""
    if ex is None:
        return None, "failed:no_code"
    if ex.get("timed_out"):
        return None, "failed:timeout"
    if ex.get("returncode") != 0:
        return None, "failed:exit"
    if harness is not None and "official_add_script" in harness and harness["official_add_script"] != "ok":
        return None, "failed:add_script"
    out = ex.get("stdout_tail") or ""
    pos = out.find(OFFICIAL_MARKER)
    if pos != -1:
        val = out[pos:].replace(OFFICIAL_MARKER, "").strip()
        nl = val.find("\n")
        if nl != -1:
            val = val[:nl]
        return val, "best_solution"
    if NO_BEST_SOLUTION in out:
        return NO_BEST_SOLUTION, "no_best_solution"
    return None, "out_of_expectation"


def is_no_best_solution_reference(objective, status, raw=None):
    """A reference the official data would write as "No Best Solution" (no optimal value: infeasible / unbounded)."""
    if objective is not None:
        return False
    if status:
        return True
    return isinstance(raw, str) and raw.strip().lower() == NO_BEST_SOLUTION.lower()


def official_judge(pred, ref_objective, ref_status=None, ref_raw=None, tol=ORLM_OFFICIAL_TOL):
    """ORLM's pass@1 rule (eval/execute.py lines 182-198): (correct, reason).

    Both values are rounded to integers with Python's round(); correct when |p - g| / |g| <= tol, or |p| <= tol when
    g == 0. A "No Best Solution" reference is matched only by the string "No Best Solution"."""
    if is_no_best_solution_reference(ref_objective, ref_status, ref_raw):
        ok = pred == NO_BEST_SOLUTION
        return ok, "no_best_solution_match" if ok else "no_best_solution_mismatch"
    if ref_objective is None:
        return False, "reference_not_numeric"
    if pred is None:
        return False, "no_prediction"
    if pred == NO_BEST_SOLUTION:
        return False, "no_best_solution_predicted"
    try:
        p = round(float(pred))
        g = round(float(ref_objective))
    except (TypeError, ValueError, OverflowError):  # the official loop would have stopped with an exception here
        return False, "prediction_not_numeric"
    close = abs(p) <= tol if g == 0 else abs((p - g) / g) <= tol
    return close, "match" if close else "mismatch"


# ----------------------------------------------------------------------------------------------------- run record


def run_config_path(run):
    return os.path.join(run, "run_config.json")


def load_run(run):
    p = run_config_path(run)
    if not os.path.isfile(p):
        raise Refused(f"{rel(p)} not found: run the requests stage first")
    with open(p, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("adapter_schema") != ADAPTER_SCHEMA:
        raise Refused(f"{rel(p)} is not an ORLM adapter run")
    return cfg


def save_run(run, cfg):
    with open(run_config_path(run), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def requests_path(run):
    return os.path.join(run, f"requests.{COND}.jsonl")


def gen_dir(run):
    return os.path.join(run, f"gen.{COND}")


def gate(stage, run, case_ids, cfg):
    """E21 test gate for one stage (records itself in <run>/freeze_gate.jsonl when it applies)."""
    split_dir = cfg.get("split_dir")
    try:
        return FZ.gate_stage(stage, run_dir=run, case_ids=list(case_ids), split=cfg.get("split"),
                             split_dir=os.path.join(ROOT, split_dir) if split_dir else None)
    except FZ.GateRefused as e:
        raise SystemExit(f"[orlm] {stage} refused by the test gate: {e}") from None


def touches_sealed(cfg, case_ids):
    need, _, _ = FZ.gate_reason(ROOT, cfg.get("split"), list(case_ids))
    return need


def entry_is_pending(entry):
    """The registry's one pending marker, "status": "pending" (model_registry.entry_pending)."""
    return MR.entry_pending(entry)


def code_files():
    return [os.path.abspath(__file__)] + [os.path.join(RUNTIME, "orgene", *p) for p in
                                           (("backends", "llamacpp.py"), ("backends", "base.py"), ("runner.py",),
                                            ("execute.py",), ("solve_recorder.py",))]


# ----------------------------------------------------------------------------------------------------- stage: requests


def cmd_requests(a):
    reg = CF.load_registry(a.configs) if a.configs else CF.load_registry()
    ad = reg["adapters"].get(COND)
    if not ad or ad.get("adapter") != ANCHOR:
        raise Refused(f"the configuration registry has no adapter entry {COND!r} of kind {ANCHOR!r}")
    ids = S.load_split_ids(a.split_dir, a.split) if (a.split_dir and a.split) else None
    cases = D.load_cases(a.cases, ids)
    if a.limit:
        cases = cases[: a.limit]
    if not cases:
        raise Refused("no cases selected")
    cfg = {"adapter_schema": ADAPTER_SCHEMA, "cond": COND, "adapter": ANCHOR, "orlm_source": ORLM_SOURCE,
           "split": a.split, "split_dir": rel(a.split_dir) if a.split_dir else None,
           "cases_path": rel(a.cases), "cases_sha256": file_sha256(a.cases), "n_cases": len(cases),
           "prompt_template_sha256": TEMPLATE_SHA256, "add_script_sha256": ADD_SCRIPT_SHA256,
           "harness_sha256": HARNESS_SHA256, "configs_registry_sha256": reg["sha256"]}
    gate("requests", a.run, [c["case_id"] for c in cases], cfg)
    reqs = []
    for c in cases:
        prompt = orlm_prompt(c["text"])
        reqs.append({"request_id": f"{c['case_id']}.{COND}.rep0", "case_id": c["case_id"], "condition": COND,
                     "messages": [{"role": "user", "content": prompt}],
                     "meta": {"adapter": ANCHOR, "round": 0, "prompt_sha256": sha256_text(prompt),
                              "prompt_template_sha256": TEMPLATE_SHA256}})
    os.makedirs(a.run, exist_ok=True)
    rp = requests_path(a.run)
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in reqs)
    if os.path.exists(rp):
        with open(rp, "r", encoding="utf-8") as f:
            if f.read() != text:
                raise Refused(f"{rel(rp)} exists with different requests; use a new --run directory")
    with open(rp, "w", encoding="utf-8") as f:
        f.write(text)
    cfg.update({"created_at": now_iso(), "requests_sha256": file_sha256(rp),
                "stages": {"requests": {"at": now_iso(), "argv": sanitize_argv(a.argv_full)}}})
    save_run(a.run, cfg)
    print(f"[orlm] requests: {len(reqs)} ({rel(rp)})")
    return 0


# ----------------------------------------------------------------------------------------------------- stage: generate


def server_argv(entry, gguf_path, *, binary="llama-server", host="127.0.0.1", port=8080):
    """llama-server command line from the registry entry (baselines/llamacpp_server.py, shared with LLMOPT)."""
    return LS.server_argv(entry, gguf_path, binary=binary, host=host, port=port, prefix="[orlm]")


_get_json = LS._get_json
ollama_loaded = LS.ollama_loaded
check_server_identity = LS.check_server_identity


class LlamaServer(LS.LlamaServer):
    """llama-server started and stopped around the generate stage (baselines/llamacpp_server.py)."""

    prefix = "[orlm]"


def cmd_generate(a):
    cfg = load_run(a.run)
    rp = requests_path(a.run)
    if file_sha256(rp) != cfg.get("requests_sha256"):
        raise Refused(f"{rel(rp)} changed after the requests stage")
    reqs = RN.load_requests(rp, prefix="[orlm]")
    ids = [r["case_id"] for r in reqs]
    reg = MR.read(a.registry)
    entry, reg_rec = RN.load_registry_entry(a.registry, a.registry_entry, prefix="[orlm]")
    if entry.get("backend") != BACKEND_KIND:
        raise Refused(f"registry entry {a.registry_entry} is for backend {entry.get('backend')!r}, not {BACKEND_KIND}")
    sealed = touches_sealed(cfg, ids)
    if entry_is_pending(entry):
        if sealed:
            raise Refused(f"registry entry {a.registry_entry} is still pending (status); sealed (test) cases need the "
                          "decided entry")
        if not a.allow_pending:
            raise Refused(f"registry entry {a.registry_entry} is still pending (status); pass --allow-pending for a "
                          "dev rehearsal")
    if sealed and not a.launch:
        raise Refused("sealed (test) cases: the adapter must start llama-server itself (--launch), so that the "
                      "server settings are the entry's")
    gate("generate", a.run, ids, cfg)
    anchor = (reg.get("anchors") or {}).get(ANCHOR) or {}
    gguf_file = ((entry.get("identity") or {}).get("gguf_file"))
    if gguf_file != (anchor.get("gguf") or {}).get("file"):
        raise Refused("the entry's gguf_file differs from anchors.orlm.gguf.file")
    if not a.gguf or not os.path.isfile(a.gguf):
        raise Refused("--gguf must name the GGUF file the server loads")
    if os.path.basename(a.gguf) != gguf_file:
        raise Refused(f"--gguf is {os.path.basename(a.gguf)!r}, the registry names {gguf_file!r}")
    print(f"[orlm] hashing {os.path.basename(a.gguf)} ...", flush=True)
    digest = file_sha256(a.gguf)
    if digest != entry.get("digest"):
        raise Refused(f"GGUF sha256 {digest[:16]}... differs from the registry entry's digest")
    build = ((reg.get("baselines") or {}).get("llama_cpp") or {}).get("build")
    url = a.host or f"http://127.0.0.1:{a.port}"
    out = gen_dir(a.run)
    launch_rec = None
    server = None
    if a.launch:
        loaded = ollama_loaded(a.ollama_host)
        if loaded:
            raise Refused(f"Ollama holds {len(loaded)} model(s) in memory; wait until it is idle")
        argv = server_argv(entry, a.gguf, binary=a.llama_server, port=a.port)
        launch_rec = {"argv": sanitize_argv(argv), "started_at": now_iso()}
        server = LlamaServer(argv, url, os.path.join(out, "llama_server.log"), wait_s=a.server_wait)
    status = 0
    try:
        if server is not None:
            server.__enter__()
        backend = LlamaCppCompletionBackend(entry["model"], host=url, digest=digest, timeout=a.call_timeout,
                                            retry_sleep=a.retry_sleep)
        try:
            ident = backend.identity()
        except BackendError as e:
            raise Refused(str(e))
        problems = check_server_identity(ident, entry, gguf_file, build)
        if problems:
            raise Refused("llama-server differs from the registry entry: " + "; ".join(problems))
        status = RN.run_batch(backend, reqs, out, entry["opts"], repeat=1, requests_path=rp, registry=(entry, reg_rec),
                              argv=a.argv_full, code_files=code_files(), prefix="[orlm]",
                              note="ORLM anchor (E17): llama-server /completion, official prompt, greedy")
    finally:
        if server is not None:
            server.__exit__(None, None, None)
            launch_rec["stopped_at"] = now_iso()
    recs = P.read_gen_outputs(out)
    summary = {
        "n_calls": len(recs), "n_ok": sum(1 for r in recs if r.get("ok")),
        "stop_types": _counts(r.get("stop_type") for r in recs),
        "n_prompt_truncated": sum(1 for r in recs if r.get("prompt_truncated")),
        "n_settings_echo_mismatch": sum(1 for r in recs if r.get("settings_echo_mismatch")),
        "n_settings_echo_missing": sum(1 for r in recs if r.get("settings_echo_missing")),
    }
    cfg.setdefault("stages", {})["generate"] = {
        "at": now_iso(), "argv": sanitize_argv(a.argv_full), "registry": reg_rec, "entry_pending": entry_is_pending(entry),
        "gguf_file": gguf_file, "gguf_sha256": digest, "server_identity": backend.identity(),
        "server_launched_by_adapter": bool(a.launch), "launch": launch_rec,
        "launch_settings_verified": bool(a.launch), "summary": summary}
    save_run(a.run, cfg)
    print(f"[orlm] generate: {json.dumps(summary, sort_keys=True)}")
    if summary["n_prompt_truncated"] or summary["n_settings_echo_mismatch"] or summary["n_settings_echo_missing"]:
        print("[orlm] ERROR: the server truncated a prompt or did not apply the sent settings (see the call records)",
              file=sys.stderr)
        return 4
    return status


def _counts(values):
    out = {}
    for v in values:
        k = "none" if v is None else str(v)
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


# ----------------------------------------------------------------------------------------------------- stage: execute


def baselines_python(arg=None):
    return os.path.expanduser(arg or os.environ.get("ORGENE_BASELINES_PY") or DEFAULT_BASELINES_PY)


def execute_one(rec, python, timeout=EXEC_TIMEOUT):
    """One generation record -> the validated/final row of the pipeline format, plus the `orlm` block."""
    content = rec.get("content") or ""
    if rec.get("ok"):
        script, info = extract_code(content)
    else:
        script, info = None, {"method": "orlm_official_first_python_block", "ok": False, "reason": "generation_failed",
                              "block_closed": None, "n_python_fences": 0}
    ex, harness, program = None, None, None
    if script is not None:
        program = build_program(script)
        ex = run_program(program, timeout=timeout, python=python, record_solves=True)
        harness = parse_harness(ex.get("stdout_tail"))
    pred, state = official_prediction(ex, harness)
    meta = rec.get("meta") or {}
    k = int(meta.get("orig_repeat", rec.get("repeat", 0)))
    orlm = {"extraction": info, "script_sha256": sha256_text(script) if script is not None else None,
            "program_sha256": sha256_text(program) if program is not None else None,
            "harness": harness, "official_prediction": pred, "official_state": state, "copt": copt_flags(ex),
            "stop_type": rec.get("stop_type"), "prompt_truncated": rec.get("prompt_truncated"),
            "settings_echo_mismatch": rec.get("settings_echo_mismatch")}
    v = {"case_id": rec["case_id"], "repeat": k, "condition": COND, "round": 0, "request_id": rec.get("request_id"),
         "gen_ok": bool(rec.get("ok")), "done_reason": rec.get("done_reason"), "out_tokens": rec.get("eval_count"),
         "in_tokens": rec.get("prompt_eval_count"), "local_tokens": rec.get("local_tokens"),
         "gen_seconds": (rec.get("total_duration_ns") or 0) / 1e9 if rec.get("total_duration_ns") else rec.get("seconds"),
         "has_spec": False, "has_code": script is not None, "spec": None, "code": script, "exec": ex, "issues": [],
         "hard_failed_genes": [], "soft_failed_genes": [], "decision": "accepted", "repair_applied_genes": [],
         "repair_applications": {}, "max_rounds": 0, "validated_at": now_iso(), "orlm": orlm}
    return v


def cmd_execute(a):
    cfg = load_run(a.run)
    recs = P.read_gen_outputs(gen_dir(a.run))
    if not recs:
        raise Refused(f"no generation outputs in {rel(gen_dir(a.run))}")
    ids = [r["case_id"] for r in recs]
    gate("validate", a.run, ids, cfg)
    py = baselines_python(a.python)
    env = baselines_env(py, packages=("coptpy",))
    reg = MR.read(a.registry)
    want = (((reg.get("baselines") or {}).get("packages")) or {}).get("coptpy")
    got = (env.get("packages") or {}).get("coptpy") if env.get("observed") else None
    if got != want:
        raise Refused(f"coptpy in the baselines interpreter is {got!r}, the registry records {want!r}")
    rows = [execute_one(r, py, timeout=a.timeout) for r in sorted(recs, key=lambda r: (r["case_id"], r.get("repeat", 0)))]
    write_jsonl(os.path.join(a.run, f"validated.{COND}.round0.jsonl"), rows)
    final = []
    for v in rows:
        e = dict(v)
        e["rounds"] = [{"round": 0, "request_id": v["request_id"], "out_tokens": v["out_tokens"],
                        "in_tokens": v["in_tokens"], "hard_failed_genes": [], "soft_failed_genes": [],
                        "exec_ok": bool((v.get("exec") or {}).get("exec_ok")), "decision": "accepted",
                        "repair_applied_genes": []}]
        e["provisional"] = False
        final.append(e)
    write_jsonl(os.path.join(a.run, f"final.{COND}.jsonl"), final)
    summary = execution_summary(rows)
    cfg.setdefault("stages", {})["execute"] = {
        "at": now_iso(), "argv": sanitize_argv(a.argv_full), "python": rel(py),
        "python_version": env.get("python_version"), "coptpy": got, "copt_license_file_found":
            env.get("copt_license_file_found"), "timeout_s": a.timeout, "solve_recorder": True,
        "harness_sha256": HARNESS_SHA256, "summary": summary}
    save_run(a.run, cfg)
    print(f"[orlm] execute: {json.dumps(summary, sort_keys=True)}")
    return 0


def execution_summary(rows):
    o = [r.get("orlm") or {} for r in rows]
    return {
        "n": len(rows),
        "n_code": sum(1 for r in rows if r.get("has_code")),
        "extraction_failures": _counts((x.get("extraction") or {}).get("reason") for x in o
                                       if not (x.get("extraction") or {}).get("ok")),
        "n_block_unclosed": sum(1 for x in o if (x.get("extraction") or {}).get("block_closed") is False),
        "n_exec_ok": sum(1 for r in rows if (r.get("exec") or {}).get("exec_ok")),
        "n_protocol_ok": sum(1 for r in rows if (r.get("exec") or {}).get("protocol_ok")),
        "harness_targets": _counts((x.get("harness") or {}).get("target") for x in o if x.get("harness") is not None),
        "n_harness_missing": sum(1 for r, x in zip(rows, o) if r.get("has_code") and x.get("harness") is None),
        "official_add_script": _counts((x.get("harness") or {}).get("official_add_script") for x in o
                                       if x.get("harness") is not None),
        "official_states": _counts(x.get("official_state") for x in o),
        "n_copt_size_limited": sum(1 for x in o if (x.get("copt") or {}).get("size_limited")),
        "n_copt_no_license_notice": sum(1 for x in o if (x.get("copt") or {}).get("no_license_notice")),
        "done_reasons": _counts(r.get("done_reason") for r in rows),
    }


# ----------------------------------------------------------------------------------------------------- stage: score


def official_fields(v, reference):
    orlm = v.get("orlm") or {}
    pred = orlm.get("official_prediction")
    ok, why = official_judge(pred, reference.get("objective"), reference.get("status"), reference.get("raw"))
    o_obj = reference.get("original_objective", reference.get("objective"))
    o_st = reference.get("original_status", reference.get("status"))
    ok_o, _ = official_judge(pred, o_obj, o_st, reference.get("raw"))
    return {"orlm_official_prediction": pred, "orlm_official_state": orlm.get("official_state"),
            "correct_orlm_official": ok, "orlm_official_reason": why, "correct_orlm_official_original_ref": ok_o}


def official_summary(rows):
    n = len(rows)
    c = sum(1 for r in rows if r.get("correct_orlm_official"))
    co = sum(1 for r in rows if r.get("correct_orlm_official_original_ref"))
    return {"n": n, "n_correct": c, "accuracy": round(c / n, 4) if n else None, "n_correct_original_ref": co,
            "accuracy_original_ref": round(co / n, 4) if n else None,
            "reasons": _counts(r.get("orlm_official_reason") for r in rows)}


def cmd_score(a):
    cfg = load_run(a.run)
    if file_sha256(a.cases) != cfg.get("cases_sha256"):
        raise Refused(f"{rel(a.cases)} is not the cases file the requests were built from")
    final_path = os.path.join(a.run, f"final.{COND}.jsonl")
    if not os.path.isfile(final_path):
        raise Refused("no final.ORLM.jsonl: run the execute stage first")
    final = read_jsonl(final_path)
    rec = gate("score", a.run, [v["case_id"] for v in final], cfg)
    manifest = a.freeze_manifest
    if rec and manifest is None:
        manifest = os.path.join(ROOT, rec["manifest"])
    try:
        cases = {c["case_id"]: c for c in R.load_scoring_cases(a.cases, overrides=a.overrides, freeze_manifest=manifest,
                                                                expected_sha256=a.overrides_sha256)}
    except R.OverrideError as e:
        raise Refused(str(e))
    # the main columns: the scoring function of every configuration, unchanged
    m = P.score_condition(a.run, COND, cases, rel_tol=1e-4, abs_tol=1e-4)
    by_key = {(v["case_id"], v["repeat"]): v for v in final}
    res_path = os.path.join(a.run, f"results.{COND}.jsonl")
    rows = read_jsonl(res_path)
    for r in rows:
        r.update(official_fields(by_key[(r["case_id"], r["repeat"])], cases[r["case_id"]]["reference"]))
    write_jsonl(res_path, rows)
    by_source = {}
    for r in rows:
        by_source.setdefault(r.get("source"), []).append(r)
    m["orlm"] = {
        "adapter_schema": ADAPTER_SCHEMA, "orlm_source": ORLM_SOURCE, "prompt_template_sha256": TEMPLATE_SHA256,
        "add_script_sha256": ADD_SCRIPT_SHA256, "harness_sha256": HARNESS_SHA256,
        "official_rule": "round(pred) and round(ref) to integers; correct when |p-g|/|g| <= 0.05 (|p| <= 0.05 when "
                         "g == 0); 'No Best Solution' references matched by that string (ORLM eval/execute.py)",
        "official_tolerance": ORLM_OFFICIAL_TOL,
        "official": official_summary(rows),
        "official_by_source": {s: official_summary(v) for s, v in sorted(by_source.items(), key=lambda x: str(x[0]))},
        "execution": execution_summary(final),
    }
    with open(os.path.join(a.run, f"metrics.{COND}.json"), "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2, ensure_ascii=False)
    cfg.setdefault("stages", {})["score"] = {"at": now_iso(), "argv": sanitize_argv(a.argv_full)}
    save_run(a.run, cfg)
    o = m["orlm"]["official"]
    print(f"[orlm] score: n={m['n']} accuracy={m['accuracy']} ({m['n_correct']}/{m['n']}); "
          f"official column {o['accuracy']} ({o['n_correct']}/{o['n']})")
    return 0


# ----------------------------------------------------------------------------------------------------- CLI


def main(argv=None):
    ap = argparse.ArgumentParser(prog="orlm_adapter", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("requests", help="official ORLM prompts for the selected cases")
    p.add_argument("--cases", required=True)
    p.add_argument("--split-dir", default=None)
    p.add_argument("--split", choices=["dev", "test"], default=None)
    p.add_argument("--run", required=True)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--configs", default=None, help="configuration registry (default configs/r1_configs.json)")
    p.set_defaults(fn=cmd_requests)

    p = sub.add_parser("generate", help="greedy completions from llama-server with the registry entry's settings")
    p.add_argument("--run", required=True)
    p.add_argument("--registry", default=DEFAULT_REGISTRY)
    p.add_argument("--registry-entry", default=DEFAULT_ENTRY)
    p.add_argument("--gguf", required=True, help="the GGUF file the server loads (hashed; only its name is recorded)")
    p.add_argument("--launch", action="store_true", help="start and stop llama-server with the entry's settings")
    p.add_argument("--llama-server", default="llama-server", help="llama-server executable (with --launch)")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--host", default=None, help="URL of an already running server (without --launch)")
    p.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    p.add_argument("--server-wait", type=float, default=900.0)
    p.add_argument("--call-timeout", type=float, default=900.0)
    p.add_argument("--retry-sleep", type=float, default=5.0)
    p.add_argument("--allow-pending", action="store_true", help="use a registry entry that is still pending (status; dev rehearsal only)")
    p.set_defaults(fn=cmd_generate)

    p = sub.add_parser("execute", help="extract, append the harness, run under the solve recorder")
    p.add_argument("--run", required=True)
    p.add_argument("--python", default=None, help="baselines interpreter (default $ORGENE_BASELINES_PY or ~/venvs/baselines)")
    p.add_argument("--registry", default=DEFAULT_REGISTRY)
    p.add_argument("--timeout", type=int, default=EXEC_TIMEOUT)
    p.set_defaults(fn=cmd_execute)

    p = sub.add_parser("score", help="main columns (score_condition) plus the ORLM official column")
    p.add_argument("--run", required=True)
    p.add_argument("--cases", required=True)
    p.add_argument("--overrides", default="auto")
    p.add_argument("--overrides-sha256", default=None)
    p.add_argument("--freeze-manifest", default=None)
    p.set_defaults(fn=cmd_score)

    a = ap.parse_args(argv)
    a.argv_full = ["baselines/orlm_adapter.py"] + list(sys.argv[1:] if argv is None else argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
