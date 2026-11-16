#!/usr/bin/env python3
"""LLMOPT anchor driver (E18): prepare -> q2f -> f2c -> execute -> score, one run directory per (source, split).

  PY=/opt/homebrew/bin/python3
  $PY baselines/llmopt/run.py all --source industryor --split dev --gguf <LLMOPT-Qwen2.5-14B-Q8_0.gguf> --launch \
      [--out DIR] [--limit N]
  $PY baselines/llmopt/run.py {prepare|q2f|f2c|execute|score} --out DIR [...]

Run directory (default experiments/<UTC date>-llmopt-qwen25-14b-q8-<source>-<split>-LLMOPT):
  run_config.json        source, split, case ids, cases file hash, adapter / prompt / parser versions, registry entry,
                         the summary of each generation step
  requests.q2f.jsonl     step 1 requests: one user message each, the rendered prompt   (upstream prompt text: not for release)
  gen.q2f/               orgene.runner.run_batch output: config.json, outputs/, receipts.jsonl, metrics.json;
                         llama_server.log when the driver started the server
  extract.q2f.jsonl      per case: five elements found, their hash
  requests.f2c.jsonl     step 2 requests                                              (not for release)
  gen.f2c/
  exec_config.json       interpreter, Pyomo and CBC versions, timeout, prelude hash, environment check
  final.LLMOPT.jsonl     per case: the program, `exec` for the scorer, `llmopt` details
  results.LLMOPT.jsonl / metrics.LLMOPT.json   pipeline.score_condition (the R1 scorer, same tolerances)

Generation (since the wave2 merge, as for the ORLM anchor): llama-server's native /completion
(orgene.backends.llamacpp.LlamaCppCompletionBackend) with the registry entry (default llmopt-qwen25-14b-q8.anchor,
backend llamacpp_completion): KV cache f16, one slot, cache_prompt false, every sampler sent. Each request is exactly
one user message (templates.require_single_user_message), rendered here with the GGUF's own chat template
(templates.render_prompt) and sent verbatim, so no server-side template is involved. The GGUF is hashed and must be
the entry's digest; the running server must report the entry's model file, context, slot count and llama.cpp build;
`--launch` starts llama-server from the entry's identity.server block (only while Ollama holds no model) and stops it
afterwards; a sealed (test) run must use --launch. The local counter (templates.GgufCounter, llama-tokenize over the
same GGUF) counts every prompt; a prompt the server counts differently, a truncated prompt, or a setting the server
did not apply fails the step (exit status 4).

Stages that touch sealed cases pass the test gate (orgene.freeze.gate_stage); a test run is also refused while the
backup parser is not frozen (adapter.PARSER_FROZEN) or the registry entry is still marked `"status": "pending"`. The
model is not called by `prepare`, `execute` or `score`.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
for _p in (ROOT, os.path.join(ROOT, "runtime")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from baselines import llamacpp_server as LS  # noqa: E402
from baselines.llmopt import adapter as A  # noqa: E402
from baselines.llmopt import prompts as PR  # noqa: E402
from baselines.llmopt import templates as T  # noqa: E402
from orgene import data as D  # noqa: E402
from orgene import freeze as FZ  # noqa: E402
from orgene import model_registry as MR  # noqa: E402
from orgene import pipeline as P  # noqa: E402
from orgene import runner as RN  # noqa: E402
from orgene import tokcount as TC  # noqa: E402
from orgene.backends.base import BackendError  # noqa: E402
from orgene.backends.llamacpp import LlamaCppCompletionBackend  # noqa: E402
from orgene.execute import run_program  # noqa: E402
from orgene.paths import rel, resolve, sanitize_argv  # noqa: E402

RUN_SCHEMA = "orgene.r1.llmopt_run.v1"
ANCHOR = "llmopt"
BACKEND_KIND = "llamacpp_completion"
DEFAULT_REGISTRY = os.path.join(ROOT, "configs", "model_registry.json")
DEFAULT_ENTRY = "llmopt-qwen25-14b-q8.anchor"
DEFAULT_OLLAMA_HOST = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434")
DEFAULT_BASELINES_PY = os.environ.get("ORGENE_BASELINES_PY") or os.path.join(
    os.path.expanduser("~"), "venvs", "baselines", "bin", "python")
DEFAULT_CBC = os.environ.get("ORGENE_CBC") or "/opt/homebrew/bin/cbc"
NOT_FOR_RELEASE = ["requests.q2f.jsonl", "requests.f2c.jsonl"]
CODE_FILES = [os.path.join(HERE, f) for f in ("run.py", "adapter.py", "prompts.py", "templates.py")] + [
    os.path.join(ROOT, "baselines", "llamacpp_server.py"),
    os.path.join(ROOT, "runtime", "orgene", "backends", "llamacpp.py")]
STEP_CONDITION = {"q2f": "LLMOPT-Q2F", "f2c": "LLMOPT-F2C"}
ENV_CHECK_CODE = (
    "from pyomo.environ import ConcreteModel, Var, Objective, Constraint, NonNegativeReals, SolverFactory, minimize\n"
    "m = ConcreteModel()\nm.x = Var(within=NonNegativeReals)\nm.o = Objective(expr=m.x, sense=minimize)\n"
    "m.c = Constraint(expr=m.x >= 1)\nr = SolverFactory('glpk').solve(m)\nprint('Objective value:', m.o())\n")


class RunError(SystemExit):
    pass


def die(msg):
    raise RunError(f"[llmopt] {msg}")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_registry(path, entry_id):
    with open(path, "r", encoding="utf-8") as f:
        reg = json.load(f)
    entry, rec = RN.load_registry_entry(path, entry_id, prefix="[llmopt]")
    if entry.get("backend") != BACKEND_KIND or entry.get("model") != T.SERVER_ALIAS:
        die(f"registry entry {entry_id} is not the llama-server entry ({BACKEND_KIND}) of {T.SERVER_ALIAS}")
    return reg, entry, rec


# ---------------------------------------------------------------------------------------------- prepare


def default_out(source, split):
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return os.path.join(ROOT, "experiments", f"{day}-llmopt-qwen25-14b-q8-{source}-{split}-{A.CONDITION}")


def select_ids(a):
    if a.ids_file:
        with open(resolve(a.ids_file), encoding="utf-8") as f:
            ids = json.load(f)
    elif a.source == "smoke":
        ids = None
    else:
        p = os.path.join(ROOT, "data", "splits", a.source, f"{a.split}_ids.json")
        if not os.path.isfile(p):
            die(f"no id file {rel(p)}; give --ids-file")
        with open(p, encoding="utf-8") as f:
            ids = json.load(f)
    return ids


def gate(stage, out, cfg):
    try:
        return FZ.gate_stage(stage, run_dir=out, case_ids=cfg["case_ids"], split=cfg["split"],
                             split_dir=resolve(cfg["split_dir"]) if cfg.get("split_dir") else None)
    except FZ.GateRefused as e:
        die(f"{stage} refused by the test gate: {e}")


def sealed(cfg):
    return cfg["split"] in FZ.SEALED_SPLITS


def require_final(cfg, a):
    """A sealed split (test) needs the frozen backup parser and a registry entry that is no longer pending."""
    if not sealed(cfg):
        return
    if not A.PARSER_FROZEN:
        die(f"split {cfg['split']}: the backup parser {A.PARSER_VERSION} is not frozen (adapter.PARSER_FROZEN)")
    _, entry, _ = load_registry(a.registry, a.registry_entry)
    if MR.entry_pending(entry):
        die(f"split {cfg['split']}: registry entry {a.registry_entry} is still pending (status; settings not final)")


def step_request(case_id, step, messages, prompts):
    """One request of a step: the single user message rendered with the GGUF chat template (the /completion prompt)."""
    user = T.require_single_user_message(messages)[0]["content"]
    prompt = T.render_prompt(messages)
    return {"request_id": f"{case_id}.{step}", "case_id": case_id, "condition": STEP_CONDITION[step],
            "messages": [{"role": "user", "content": prompt}],
            "meta": {"step": step, "prompts_sha256": prompts.sha256, "prompt_template_sha256": T.GGUF_TEMPLATE_SHA256,
                     "user_text_sha256": hashlib.sha256(user.encode("utf-8")).hexdigest(),
                     "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}}


def cmd_prepare(a):
    cases_path = resolve(a.cases or os.path.join("data", "cases", f"{a.source}.jsonl"))
    ids = select_ids(a)
    cases = D.load_cases(cases_path, set(ids) if ids is not None else None)
    order = {c: i for i, c in enumerate(ids)} if ids is not None else None
    if order is not None:
        cases.sort(key=lambda c: order[c["case_id"]])
        missing = sorted(set(ids) - {c["case_id"] for c in cases})
        if missing:
            die(f"{len(missing)} case id(s) not in {rel(cases_path)}")
    if a.limit:
        cases = cases[:a.limit]
    split_dir = os.path.join("data", "splits", a.source) if a.source != "smoke" else None
    reg, entry, reg_rec = load_registry(a.registry, a.registry_entry)
    cfg = {"schema": RUN_SCHEMA, "condition": A.CONDITION, "source": a.source, "split": a.split,
           "split_dir": split_dir, "cases_path": rel(cases_path), "cases_sha256": sha256_file(cases_path),
           "case_ids": [c["case_id"] for c in cases], "n_cases": len(cases),
           "adapter_version": A.ADAPTER_VERSION, "parser_version": A.PARSER_VERSION, "parser_frozen": A.PARSER_FROZEN,
           "prompts": dict(PR.UPSTREAM), "registry": reg_rec,
           "templates": {"gguf": T.GGUF_TEMPLATE_SHA256, "renderer": T.RENDERER_ID,
                         "request_shape": "one user message, rendered locally with the GGUF chat template and sent "
                                          "verbatim to llama-server /completion"},
           "not_for_release": NOT_FOR_RELEASE}
    out = a.out or default_out(a.source, a.split)
    require_final(cfg, a)
    gate("prepare", out, cfg)
    prompts = PR.load()
    reqs = [step_request(c["case_id"], "q2f", A.q2f_messages(c["text"], prompts), prompts) for c in cases]
    os.makedirs(out, exist_ok=True)
    cfg_path = os.path.join(out, "run_config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            prev = json.load(f)
        keep = ("source", "split", "cases_sha256", "case_ids", "adapter_version", "prompts", "registry", "templates")
        differ = [k for k in keep if prev.get(k) != cfg.get(k)]
        if differ:
            die(f"{rel(out)} holds another run ({', '.join(differ)} differ); use a new --out")
        cfg["created_at"] = prev.get("created_at")
        cfg["stages"] = prev.get("stages") or {}
    cfg.setdefault("created_at", now_iso())
    cfg["argv"] = sanitize_argv(sys.argv)
    write_json(cfg_path, cfg)
    write_jsonl(os.path.join(out, "requests.q2f.jsonl"), reqs)
    print(f"[llmopt] prepared {len(reqs)} case(s) in {rel(out)}", flush=True)
    return out


def load_cfg(out):
    p = os.path.join(out, "run_config.json")
    if not os.path.isfile(p):
        die(f"{rel(out)} has no run_config.json; run `prepare` first")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------------------------- generation


def make_counter(a, gguf_path, digest):
    """templates.GgufCounter over the GGUF the server loads (None with --no-local-tokens)."""
    if a.no_local_tokens:
        return None
    try:
        return T.GgufCounter(gguf_path, digest)
    except Exception as e:  # noqa: BLE001
        die(f"local token counts unavailable: {type(e).__name__}: {e} (or pass --no-local-tokens)")


def _receipts_complete(gen_dir, request_ids):
    p = os.path.join(gen_dir, "receipts.jsonl")
    done = {(r["request_id"]) for r in read_jsonl(p)} if os.path.isfile(p) else set()
    return set(request_ids) <= done


def check_requests(step, requests):
    """Every request is one user message holding a prompt the GGUF template rendered from one user message."""
    for r in requests:
        try:
            T.require_single_user_message(r["messages"])
        except T.TemplateError as e:
            die(f"{step} request {r.get('request_id')} refused: {e}")
        if T.user_text_of(r["messages"][0]["content"]) is None:
            die(f"{step} request {r.get('request_id')} refused: its content is not a prompt rendered with the GGUF "
                "chat template from one user message")


def _counts(values):
    out = {}
    for v in values:
        k = "none" if v is None else str(v)
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def step_summary(recs):
    """What a step must satisfy after its calls: every prompt evaluated whole (no truncation), counted by the server as
    the local counter counts it, and every sent setting applied (echoed back)."""
    counted = [r for r in recs if r.get("ok") and isinstance(r.get("local_tokens"), dict)]
    return {
        "n_calls": len(recs), "n_ok": sum(1 for r in recs if r.get("ok")),
        "stop_types": _counts(r.get("stop_type") for r in recs),
        "n_prompt_truncated": sum(1 for r in recs if r.get("prompt_truncated")),
        "n_settings_echo_mismatch": sum(1 for r in recs if r.get("settings_echo_mismatch")),
        "n_settings_echo_missing": sum(1 for r in recs if r.get("settings_echo_missing")),
        "n_local_counted": len(counted),
        "n_prompt_tokens_mismatch": sum(1 for r in counted
                                        if r.get("prompt_eval_count") != r["local_tokens"].get("rendered_prompt")),
        "max_prompt_tokens": max((r.get("prompt_eval_count") or 0 for r in recs), default=0),
    }


def run_step(a, out, cfg, step, requests):
    reg, entry, reg_rec = load_registry(a.registry, a.registry_entry)
    if reg_rec != cfg.get("registry"):
        die("the registry entry changed since `prepare` (entry hash differs); use a new run directory")
    check_requests(step, requests)
    if sealed(cfg) and not a.launch:
        die("sealed (test) cases: the driver must start llama-server itself (--launch), so that the server settings "
            "are the entry's")
    gate(f"generate:{step}", out, cfg)
    if not requests:
        print(f"[llmopt] {step}: no requests", flush=True)
        return 0
    anchor = (reg.get("anchors") or {}).get(ANCHOR) or {}
    gguf_file = (entry.get("identity") or {}).get("gguf_file")
    if not gguf_file or gguf_file != (anchor.get("gguf") or {}).get("file"):
        die(f"the entry's identity.gguf_file differs from anchors.{ANCHOR}.gguf.file")
    if not a.gguf or not os.path.isfile(a.gguf):
        die("--gguf must name the GGUF file the server loads")
    if os.path.basename(a.gguf) != gguf_file:
        die(f"--gguf is {os.path.basename(a.gguf)!r}, the registry names {gguf_file!r}")
    print(f"[llmopt {step}] hashing {gguf_file} ...", flush=True)
    digest = TC.sha256_file(a.gguf)  # cached per process: the local counter's check does not hash it again
    if digest != entry.get("digest"):
        die(f"GGUF sha256 {digest[:16]}... differs from the registry entry's digest")
    build = ((reg.get("baselines") or {}).get("llama_cpp") or {}).get("build")
    counter = make_counter(a, a.gguf, digest)
    url = a.host or f"http://127.0.0.1:{a.port}"
    gen = os.path.join(out, f"gen.{step}")
    server, launch_rec = None, None
    if a.launch:
        loaded = LS.ollama_loaded(a.ollama_host)
        if loaded:
            die(f"Ollama holds {len(loaded)} model(s) in memory; wait until it is idle")
        argv = LS.server_argv(entry, a.gguf, binary=a.llama_server, port=a.port, prefix="[llmopt]")
        launch_rec = {"argv": sanitize_argv(argv), "started_at": now_iso()}
        server = LS.LlamaServer(argv, url, os.path.join(gen, "llama_server.log"), wait_s=a.server_wait,
                                prefix="[llmopt]")
    try:
        if server is not None:
            server.__enter__()
        backend = LlamaCppCompletionBackend(entry["model"], host=url, digest=digest, timeout=a.call_timeout,
                                            retry_sleep=a.retry_sleep, token_counter=counter,
                                            token_counter_id="baselines.llmopt.templates:GgufCounter" if counter else None)
        try:
            ident = backend.identity()
        except BackendError as e:
            die(str(e))
        problems = LS.check_server_identity(ident, entry, gguf_file, build)
        if problems:
            die("llama-server differs from the registry entry: " + "; ".join(problems))
        req_path = os.path.join(out, f"requests.{step}.jsonl")
        status = RN.run_batch(backend, requests, gen, dict(entry["opts"]), repeat=1, requests_path=req_path,
                              argv=sys.argv, code_files=CODE_FILES, note=f"LLMOPT anchor, step {step}",
                              registry=(entry, reg_rec), require_local_tokens=not a.no_local_tokens,
                              prefix=f"[llmopt {step}]")
    finally:
        if server is not None:
            server.__exit__(None, None, None)
            launch_rec["stopped_at"] = now_iso()
    summary = step_summary(P.read_gen_outputs(gen))
    cfg = load_cfg(out)
    cfg.setdefault("stages", {})[f"generate:{step}"] = {
        "at": now_iso(), "registry": reg_rec, "entry_pending": MR.entry_pending(entry), "gguf_file": gguf_file,
        "gguf_sha256": digest, "server_identity": backend.identity(), "server_launched_by_driver": bool(a.launch),
        "launch": launch_rec, "local_tokens": counter is not None, "summary": summary}
    write_json(os.path.join(out, "run_config.json"), cfg)
    print(f"[llmopt {step}] {json.dumps(summary, sort_keys=True)}", flush=True)
    if summary["n_prompt_truncated"] or summary["n_settings_echo_mismatch"] or summary["n_settings_echo_missing"] \
            or summary["n_prompt_tokens_mismatch"]:
        print(f"[llmopt {step}] ERROR: the server truncated a prompt, counted a prompt differently from the local "
              "tokenizer, or did not apply the sent settings (see the call records)", file=sys.stderr)
        return 4
    return status


def cmd_q2f(a):
    out = a.out
    cfg = load_cfg(out)
    require_final(cfg, a)
    reqs = read_jsonl(os.path.join(out, "requests.q2f.jsonl"))
    return run_step(a, out, cfg, "q2f", reqs)


def _outputs(gen_dir):
    recs = {}
    d = os.path.join(gen_dir, "outputs")
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".r0.json"):
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    r = json.load(f)
                recs[r["case_id"]] = r
    return recs


def build_f2c(out, cfg, prompts):
    q2f_ids = [f"{c}.q2f" for c in cfg["case_ids"]]
    if not _receipts_complete(os.path.join(out, "gen.q2f"), q2f_ids):
        die("step q2f is not complete; run `q2f` first")
    outs = _outputs(os.path.join(out, "gen.q2f"))
    reqs, extract = [], []
    for cid in cfg["case_ids"]:
        rec = outs.get(cid) or {}
        five = A.extract_five_elements(rec.get("content")) if rec.get("ok") else None
        extract.append({"case_id": cid, "q2f_ok": bool(rec.get("ok")), "five_elements_found": five is not None,
                        "five_elements_sha256": hashlib.sha256(five.encode("utf-8")).hexdigest() if five is not None else None})
        if five is not None:
            reqs.append(step_request(cid, "f2c", A.f2c_messages(five, prompts), prompts))
    write_jsonl(os.path.join(out, "extract.q2f.jsonl"), extract)
    return reqs


def cmd_f2c(a):
    out = a.out
    cfg = load_cfg(out)
    require_final(cfg, a)
    prompts = PR.load()
    reqs = build_f2c(out, cfg, prompts)
    req_path = os.path.join(out, "requests.f2c.jsonl")
    if os.path.exists(req_path) and read_jsonl(req_path) != reqs:
        die("requests.f2c.jsonl differs from what the q2f outputs give now; use a new run directory")
    write_jsonl(req_path, reqs)
    return run_step(a, out, cfg, "f2c", reqs)


# ---------------------------------------------------------------------------------------------- execution


def cbc_version(cbc):
    try:
        p = subprocess.run([cbc, "-quit"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        die(f"cannot run CBC ({rel(cbc)}): {type(e).__name__}")
    for line in (p.stdout or "").splitlines():
        if line.strip().lower().startswith("version"):
            return line.split(":", 1)[1].strip()
    return None


def exec_env(a, reg):
    """Check the execution environment against the registry and the redirect; returns exec_config."""
    cbc = os.path.realpath(a.cbc)
    if not (os.path.isfile(cbc) and os.access(cbc, os.X_OK)):
        die(f"CBC not found at {rel(a.cbc)} (set --cbc or ORGENE_CBC)")
    want_cbc = (reg.get("execution") or {}).get("cbc_version")
    got_cbc = cbc_version(cbc)
    if got_cbc != want_cbc:
        die(f"CBC version {got_cbc} is not the registry's {want_cbc}")
    os.environ["PATH"] = os.path.dirname(os.path.abspath(a.cbc)) + os.pathsep + os.environ.get("PATH", "")
    py = a.python
    try:
        p = subprocess.run([py, "-I", "-c", "import sys, pyomo.version as v; print(sys.version.split()[0], v.version)"],
                           capture_output=True, text=True, timeout=120)
        py_version, pyomo_version = p.stdout.split()
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        die(f"baseline interpreter {rel(py)} cannot import pyomo: {type(e).__name__}")
    want_pyomo = ((reg.get("baselines") or {}).get("packages") or {}).get("pyomo")
    if pyomo_version != want_pyomo:
        die(f"Pyomo {pyomo_version} is not the registry's {want_pyomo}")
    prog, _ = A.with_solver_redirect(ENV_CHECK_CODE)
    ex = run_program(prog, timeout=120, python=py)
    d = A.derive_result(ex)
    ok = d["objective_source"] == "solve_record" and d["objective"] == 1.0 and d["record_solver"] == A.REDIRECT_TARGET
    if not ok:
        seen = {k: d[k] for k in ("status", "objective", "objective_source", "record_solver", "failure")}
        die(f"environment check failed: a glpk request did not come back as a CBC solve with objective 1 ({seen})")
    timeout = int((reg.get("execution") or {}).get("timeout_s") or 60)
    return {"python": rel(py), "python_version": py_version, "pyomo_version": pyomo_version, "cbc": rel(a.cbc),
            "cbc_version": got_cbc, "timeout_s": timeout, "prelude_sha256": hashlib.sha256(
                A.SOLVER_PRELUDE.encode("utf-8")).hexdigest(), "prelude_lines": A.PRELUDE_LINES,
            "redirect_target": A.REDIRECT_TARGET, "env_check": "a glpk request solved by CBC, objective 1.0",
            "adapter_version": A.ADAPTER_VERSION, "parser_version": A.PARSER_VERSION, "checked_at": now_iso()}


def _tokens(rec):
    return (rec or {}).get("eval_count") or 0, (rec or {}).get("prompt_eval_count") or 0


def final_row(cid, q2f, f2c, ex_cfg, python):
    """One final.LLMOPT.jsonl row (runs the program when there is one)."""
    five = A.extract_five_elements(q2f.get("content")) if (q2f or {}).get("ok") else None
    code = A.extract_code(f2c.get("content")) if (f2c or {}).get("ok") else None
    details = {"adapter_version": A.ADAPTER_VERSION, "q2f_ok": bool((q2f or {}).get("ok")),
               "five_elements_found": five is not None, "f2c_ok": bool((f2c or {}).get("ok")),
               "code_found": code is not None,
               "done_reason": {"q2f": (q2f or {}).get("done_reason"), "f2c": (f2c or {}).get("done_reason")},
               "stop_type": {"q2f": (q2f or {}).get("stop_type"), "f2c": (f2c or {}).get("stop_type")},
               "requested_solvers": A.requested_solvers(code) if code is not None else None,
               "redirected_to": A.REDIRECT_TARGET}
    if code is None:
        failure = ("q2f_call_failed" if not details["q2f_ok"] else "no_five_elements" if five is None
                   else "f2c_call_failed" if not details["f2c_ok"] else "no_code")
        ex, derived = dict(A.NO_EXEC), None
        details.update({"failure": failure})
    else:
        program, after = A.with_solver_redirect(code)
        raw = run_program(program, timeout=ex_cfg["timeout_s"], python=python)  # output already neutral (E12)
        derived = A.derive_result(raw)
        ex = A.exec_for_scoring(raw, derived)
        details.update({k: v for k, v in derived.items() if k not in ("status", "objective")})
        details.update({"program_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
                        "executed_program_sha256": hashlib.sha256(program.encode("utf-8")).hexdigest(),
                        "prelude_after_line": after})
    o1, i1 = _tokens(q2f)
    o2, i2 = _tokens(f2c)
    n_calls = (1 if q2f else 0) + (1 if f2c else 0)
    return {"case_id": cid, "repeat": 0, "condition": A.CONDITION, "program": code, "exec": ex,
            "rounds": [{"round": 0, "hard_failed_genes": [], "soft_failed_genes": [], "out_tokens": o1 + o2,
                        "in_tokens": i1 + i2, "n_model_calls": n_calls}],
            "hard_failed_genes": [], "soft_failed_genes": [], "n_model_calls": n_calls, "llmopt": details}


def cmd_execute(a):
    out = a.out
    cfg = load_cfg(out)
    require_final(cfg, a)
    gate("execute", out, cfg)
    f2c_path = os.path.join(out, "requests.f2c.jsonl")
    if not os.path.isfile(f2c_path):
        die("step f2c has not been prepared; run `f2c` first")
    f2c_ids = [r["request_id"] for r in read_jsonl(f2c_path)]
    if f2c_ids and not _receipts_complete(os.path.join(out, "gen.f2c"), f2c_ids):
        die("step f2c is not complete; run `f2c` first")
    reg, _, _ = load_registry(a.registry, a.registry_entry)
    ex_cfg = exec_env(a, reg)
    write_json(os.path.join(out, "exec_config.json"), ex_cfg)
    q2f, f2c = _outputs(os.path.join(out, "gen.q2f")), _outputs(os.path.join(out, "gen.f2c"))
    rows = []
    for i, cid in enumerate(cfg["case_ids"], 1):
        rows.append(final_row(cid, q2f.get(cid), f2c.get(cid), ex_cfg, a.python))
        r = rows[-1]
        print(f"[llmopt execute] {i}/{len(cfg['case_ids'])} {cid} source={r['exec'].get('objective_source')} "
              f"status={r['exec'].get('status')} failure={r['llmopt'].get('failure')}", flush=True)
    write_jsonl(os.path.join(out, f"final.{A.CONDITION}.jsonl"), rows)
    return 0


def cmd_score(a):
    from orgene import refs as R
    out = a.out
    cfg = load_cfg(out)
    rec = gate("score", out, cfg)
    fm = os.path.join(ROOT, rec["manifest"]) if rec else None
    try:
        rows = R.load_scoring_cases(resolve(cfg["cases_path"]), ids=set(cfg["case_ids"]), freeze_manifest=fm)
        cases = {c["case_id"]: c for c in rows}
    except R.OverrideError as e:
        die(f"score refused: {e}")
    m = P.score_condition(out, A.CONDITION, cases)
    print(f"[llmopt score] n={m['n']} exec_rate={m['exec_rate']} accuracy={m['accuracy']} ({m['n_correct']}/{m['n']})")
    return 0


def cmd_all(a):
    a.out = cmd_prepare(a)
    for fn in (cmd_q2f, cmd_f2c):
        st = fn(a)
        if st:
            return st
    cmd_execute(a)
    return cmd_score(a)


def build_parser():
    ap = argparse.ArgumentParser(prog="llmopt run", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("prepare", "q2f", "f2c", "execute", "score", "all"):
        p = sub.add_parser(name)
        p.add_argument("--out", required=name not in ("prepare", "all"))
        p.add_argument("--registry", default=DEFAULT_REGISTRY)
        p.add_argument("--registry-entry", default=DEFAULT_ENTRY)
        if name in ("prepare", "all"):
            p.add_argument("--source", required=True, choices=("mamo_complex_lp", "industryor", "smoke"))
            p.add_argument("--split", required=True, choices=("dev", "test", "smoke"))
            p.add_argument("--cases", help="cases file (default data/cases/<source>.jsonl)")
            p.add_argument("--ids-file", help="JSON list of case ids (default data/splits/<source>/<split>_ids.json)")
            p.add_argument("--limit", type=int, default=0)
        if name in ("q2f", "f2c", "all"):
            p.add_argument("--gguf", required=True,
                           help="the GGUF file llama-server loads (hashed; only its name is recorded)")
            p.add_argument("--launch", action="store_true", help="start and stop llama-server with the entry's settings")
            p.add_argument("--llama-server", default="llama-server", help="llama-server executable (with --launch)")
            p.add_argument("--port", type=int, default=8080)
            p.add_argument("--host", default=None, help="URL of an already running llama-server (without --launch)")
            p.add_argument("--ollama-host", default=DEFAULT_OLLAMA_HOST,
                           help="Ollama, which must hold no model when --launch starts llama-server")
            p.add_argument("--server-wait", type=float, default=900.0)
            p.add_argument("--call-timeout", type=float, default=900.0)
            p.add_argument("--retry-sleep", type=float, default=5.0)
            p.add_argument("--no-local-tokens", action="store_true",
                           help="do not count the prompts locally (the prompt-count check is then skipped)")
        if name in ("execute", "all"):
            p.add_argument("--python", default=DEFAULT_BASELINES_PY, help="baseline interpreter with Pyomo")
            p.add_argument("--cbc", default=DEFAULT_CBC)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    fn = {"prepare": cmd_prepare, "q2f": cmd_q2f, "f2c": cmd_f2c, "execute": cmd_execute, "score": cmd_score,
          "all": cmd_all}[a.cmd]
    if getattr(a, "out", None):
        a.out = resolve(a.out)
    r = fn(a)
    return r if isinstance(r, int) else 0


if __name__ == "__main__":
    sys.exit(main())
