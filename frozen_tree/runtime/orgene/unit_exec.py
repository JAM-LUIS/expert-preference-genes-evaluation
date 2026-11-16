"""(case, configuration) unit executor with shared round 0 (E06).

v5 ran one configuration at a time, one round at a time, over all cases (generate -> validate -> repair requests ->
generate ...). Here the unit of work is (case, configuration, repeat): round 0 (generated, or reused from another
configuration's unit), pre-execution checks, execution under the solve recorder (E12), post-execution checks and
repair, up to the configuration's max_rounds, all in one go. That is what random scheduling (E07) and shared round 0
need. The per-answer work is pipeline.validate_one(), which the batch path (pipeline.validate_round) shares, so the
two paths write byte-identical final rows for the same answers.

ENTRY POINTS
  run_unit(case, config, repeat, backend, ctx, *, schedule=None) -> unit record (dict)
      config:   a configuration of the registry (configs.get_config), used as given
      backend:  orgene.backends Backend (make_backend(...)); a local token counter hangs on backend.token_counter
      ctx:      UnitContext (run directory, registries, gene library, lexicon, templates, model registry entry)
      schedule: optional dict stored verbatim as unit["schedule"] (E07: planned_index, plan sha256, order, ...)
      A complete unit is skipped (its record is returned; its final row is re-synced). A running or incomplete unit is
      run again from round 0. Raises UnitRefused (and subclasses ReuseError, PipelineNotImplemented) for anything
      that must stop the executor; a failed call ends the unit as `incomplete` without raising.
      A sealed case (an id in data/splits*/**/{test,eng_holdout}_ids.json) runs only when ctx.gate holds the record
      of this process's freeze.gate_stage(...) pass (E21); the entry point (main below, E07's execute) sets it.
      Every call of repeat k sends seed = base + k, repair rounds included (the batch path, run_condition.sh, sends
      repair rounds with repeat index 0, i.e. the base seed; the two agree for repeat 0).
  build_context(run_dir, ...) -> UnitContext;  derive_ladder(unit, k);  rebuild_final / export_validated;
  unit_messages(unit, rnd, i);  preflight_registry_check;  attach_local_counter;  precheck_render;  main (CLI).

FILES (in the run directory)
  units/setup.json                    run-level setup; a later call with another setup is refused (new run directory)
  units/<case>.<config>.r<k>.json     one record per unit (schema below), written atomically after every round, as
                                      compact JSON (no indentation, one line)
  final.<config>.jsonl                v5 format, one row per complete unit, sorted by (case_id, repeat), rewritten
                                      atomically when a unit completes; pipeline.score_condition reads it unchanged.
                                      Incomplete units have no row.
  validated.<config>.round<r>.jsonl   only on request (export_validated), for tools that read the batch layout

UNIT RECORD (schema orgene.r1.unit.v1)
  unit_id, case_id, config_id, repeat, run_id, source
  status             running | complete | incomplete
  stop_reason        (complete) accepted | observe_only | rounds_exhausted | no_repair_left | token_cap |
                     context_exceeded
  error              (incomplete) {kind: call_failed | backend_exception | context_exceeded | refused | exception,
                     stage, round, message}
  pipeline           standard | ora
  config             the registry entry of the configuration, verbatim
  setup_sha256       sha256 of units/setup.json's setup block
  model              {backend, model, digest};  model_registry {path, entry_id, entry_sha256} | None
  opts               the settings sent for this repeat (seed = base + repeat, for every call of the unit)
  local_tokenizer    identity of backend.token_counter | None
  features_sha256    problem features of the case (None without a lexicon)
  activation         {gene_scope, mode, impl, active_genes, gene_set_digest, trace}
  inapplicable_genes spec genes recorded as not applicable (answers that were not asked for a spec)
  c1_matching        None (not the C1 prompt) | how the C1 prompt was length-matched (see C1 LENGTH MATCHING)
  round0             {source: own | reuse:<id>, reused_from: None | {unit_id, config_id, run, request_sha256,
                      content_sha256, call_sha256}}
  rounds             [{round, calls: [call entry], validated: v (pipeline.validate_one), repair_text,
                      repair_applied_genes}]
     call entry      {stage, round, request_id, messages (round 0: full; later: only the two appended messages, see
                      unit_messages), meta, call: the backend call record (content, request_sha256, messages_sha256,
                      sent_opts, started_at, finished_at, token counts, local_tokens, ...), reused (bool)}
  pending_calls      calls made after the last validated round (incomplete units)
  applications       {geneId: repairs applied}
  tokens             {prompt, completion, total, n_calls, n_calls_reused, local: {rendered_prompt, completion,
                      n_calls_missing}}
  token_cap, token_cap_counts, budget_stop ({round, tokens_used, token_cap, hard_failed_genes} | None)
  exec_timeout_s     seconds per program execution (model registry execution.timeout_s unless given explicitly)
  context_check      {rule, num_ctx, num_predict, checked, unchecked, max_prompt_plus_predict}: the check before every
                     call after round 0 (see CONTEXT WINDOW)
  context_exceeded   None | {round, request_id, local_prompt_tokens, num_predict, num_ctx, prompt_plus_predict,
                     local_tokens_counter}: the call that was not made
  timing             {wall_seconds, gen_wall_seconds, server_seconds, queue_wait_seconds, exec_seconds}
  final_row          (complete) the final.<config>.jsonl row
  schedule, started_at, finished_at, code_sha256

TOKEN CAP (registry field token_cap, per unit): the total counts prompt_eval_count + eval_count as reported by the
server over every call of the unit, round 0 included (also when round 0 is reused: it is part of what the method
costs). A call is made only while the total is below the cap; the answer of the call that crosses it is still
checked and kept, and no repair is asked for after it. When that stops a repair that would otherwise have been
requested, the unit ends with stop_reason token_cap and budget_stop records it. The final row is then an ordinary
accepted row (like the last round of a run capped at max_rounds).

CONTEXT WINDOW (repair rounds): a repair request carries the whole conversation, so for long problems it can outgrow
num_ctx. Before every call after round 0 the rendered prompt is counted with the local tokenizer (backend.token_counter,
E09) and the call is made only if prompt + num_predict <= num_ctx (the rule of analysis/repair_prompt_budget.py). When
the next repair does not fit, only this unit stops: the call is not made, the unit is complete with stop_reason
context_exceeded, and the answer of the last round is its result, counted like a repair that failed (decision
accepted, no genes applied, like a unit whose repairs ran out). The validated record, the final row and the unit record
carry `context_exceeded` {round (the repair round not sent), request_id, local_prompt_tokens, num_predict, num_ctx,
prompt_plus_predict}, so these units can be counted separately (ladder.convergence reports them as context_exceeded).
The batch path (run_condition.sh, R0 regression only) keeps stopping the whole run. Without a local counter, or when
the settings carry no num_ctx/num_predict, or when counting fails, the call is not checked (context_check.unchecked).
A pipeline function that calls u.generate() for a round >= 1 without u.context_overflow() first gets the same check
inside generate(): an overflowing call is not made and the unit ends incomplete (error kind context_exceeded).

EXECUTION TIMEOUT: build_context(timeout=None) and the command line take the timeout from the model registry's
execution.timeout_s (E19; E22's reexec.execution_timeouts() reads the same field and is used when present). The value
is part of units/setup.json and of every unit record (exec_timeout_s).

C1 LENGTH MATCHING (E11): the C1 prompt is built the way `orgene_cli.py requests` builds it, through the same
c1match.RequestsC1, so both paths send the same C1 for the same report. c1_match_mode "tokens" (the default, as for
requests): target and token measure come from the C1 matching report (conditions/c1_matching_report.json unless
c1_report names another), which must be ok and current (gene library, lexicon, templates, C3 configuration, dev set,
tolerance, tokenizer, dev C3 prompts), and the replayed matching must give the prompt the report records. "chars":
the v5 rule (release 1.0 regression, and runs before 1D that ask for it explicitly). A C1 that cannot be built refuses
the unit (UnitRefused) before anything of it is written. Mode, tokenizer and report path are part of units/setup.json;
a C1 unit records what it used in c1_matching ({match_mode, tokenizer, report, report_sha256, target, sha256 of the C1
prompt, identity_sha256 of the tokenizer, variant}; chars: {match_mode, rule}). Under the test gate the report is one
of the inputs that must be frozen (gate_inputs).

SHARED ROUND 0 (round0 reuse:<source>): the unit reads the source configuration's unit for the same case and repeat
(ctx.round0_run_dir, default the run directory). It must be complete; the source round-0 content must hash to the
content_sha256 recorded at generation time; the request this unit would send (its own round-0 messages, built from
its own configuration, with its own settings) must hash to the source call's request_sha256; model and digest must
match. The call is then copied (no model call) and its tokens count for this unit too. The request meta stored with
the unit is the reusing configuration's own (config_id, gene scope, activation trace), never the source's.

PIPELINES: config["pipeline"] selects the function that drives a unit. "standard" is run_standard below. "ora" (the
three-stage agent baseline, E15) is looked up as agent_baseline.run_ora(u) (see PIPELINE_IMPLS); until that module
exists the unit is refused with PipelineNotImplemented before anything is written. A pipeline function receives the
UnitRun `u` and uses its hooks: u.generate(), u.check(), u.execute(), u.repair_message(), u.add_round(),
u.over_budget(), u.tokens_used(), u.note_budget_stop(), u.context_overflow(), u.stop_for_context(); it returns the stop
reason.
"""
import argparse
import contextlib
import copy
import fcntl
import glob
import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time

from . import c1match as C1M
from . import conditions as C
from . import configs as CF
from . import features as F
from . import genes as G
from . import ladder as L
from . import pipeline as P
from .backends.base import (OptionsError, RegistryMismatch, canonical_json, now_iso, registry_guard, request_sha256,
                            scrub_paths, sha256_hex)
from .conditions import read_jsonl
from .paths import ROOT, rel

UNIT_SCHEMA = "orgene.r1.unit.v1"
SETUP_SCHEMA = "orgene.r1.unit_setup.v1"
UNITS_DIR = "units"
SETUP_FILE = "setup.json"
RUNNING, COMPLETE, INCOMPLETE = "running", "complete", "incomplete"
STOP_REASONS = ("accepted", "observe_only", "rounds_exhausted", "no_repair_left", "token_cap", "context_exceeded")
TOKEN_CAP_COUNTS = ("server-reported prompt_eval_count + eval_count over every call of the unit, round 0 included "
                    "(reused round 0 too); a call is made only while the total is below the cap")
CONTEXT_RULE = "local count of the rendered prompt + num_predict <= num_ctx, before every call after round 0"
DEFAULT_EXEC_TIMEOUT_S = 60  # v5 execute.run_program; used only when the model registry has no execution block
CODE_FILES = ("predicates_it0.py", "unit_exec.py", "pipeline.py", "genes.py", "conditions.py", "configs.py", "execute.py",
              "solve_recorder.py", "extract.py", "features.py", "c1match.py", "tokcount.py", "tokcount_harmony.py",
              "gguf_vocab.py", "backends/base.py", "backends/ollama.py")
# pipeline name -> (module in this package, function); "standard" is implemented here
PIPELINE_IMPLS = {"ora": ("agent_baseline", "run_ora")}
DEFAULT_MODEL_REGISTRY = os.path.join(ROOT, "configs", "model_registry.json")


class UnitError(RuntimeError):
    """Base class of the unit executor's errors."""


class UnitRefused(UnitError):
    """The unit (or the whole run) cannot run as set up; raised before any model call of the unit. Stops the
    executor: a setup or registry problem is not something to skip over."""


class ReuseError(UnitRefused):
    """Shared round 0 cannot be used: the source unit is missing or incomplete, its content does not hash to the
    recorded content_sha256 (tampered), or it answered another request (other messages, settings or model)."""


class PipelineNotImplemented(UnitRefused):
    """config["pipeline"] names a pipeline whose module does not exist yet (ora before E15)."""


class UnitIncomplete(UnitError):
    """A model call failed or raised: the unit ends `incomplete` and gets no final row."""

    def __init__(self, message, kind="call_failed", stage=None, rnd=None):
        super().__init__(message)
        self.kind, self.stage, self.round = kind, stage, rnd


# ----------------------------------------------------------------------------------------------------- small helpers


def unit_id(case_id, config_id, repeat):
    return f"{case_id}.{config_id}.r{int(repeat)}"


def unit_path(run_dir, case_id, config_id, repeat):
    return os.path.join(run_dir, UNITS_DIR, unit_id(case_id, config_id, repeat) + ".json")


def _sha_obj(obj):
    return sha256_hex(canonical_json(obj))


def _sha_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _atomic_write(path, text):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def _jsonl_text(rows):
    """Same bytes as conditions.write_jsonl."""
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def read_unit(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_units(run_dir, config_id=None, status=None):
    """Unit records of a run directory (optionally one configuration, one status), sorted by (case_id, repeat)."""
    out = []
    for p in glob.glob(os.path.join(run_dir, UNITS_DIR, "*.json")):
        if os.path.basename(p) == SETUP_FILE:
            continue
        u = read_unit(p)
        if u.get("schema_version") != UNIT_SCHEMA:
            continue
        if config_id is not None and u.get("config_id") != config_id:
            continue
        if status is not None and u.get("status") != status:
            continue
        out.append(u)
    out.sort(key=lambda u: (u["case_id"], u["config_id"], int(u["repeat"])))
    return out


@contextlib.contextmanager
def _run_lock(run_dir):
    """One writer at a time for the shared files of a run (final.<config>.jsonl)."""
    d = os.path.join(run_dir, UNITS_DIR)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, ".lock"), "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def upsert_final(run_dir, config_id, key, row):
    """Set (row) or remove (row None) the final.<config>.jsonl row of unit key (case_id, repeat); rows sorted by key,
    written atomically in the batch path's serialisation."""
    path = os.path.join(run_dir, f"final.{config_id}.jsonl")
    with _run_lock(run_dir):
        exists = os.path.exists(path)
        rows = {(r["case_id"], int(r["repeat"])): r for r in read_jsonl(path)} if exists else {}
        if row is None:
            if key not in rows:
                return False
            rows.pop(key)
        else:
            if rows.get(key) == row:
                return False
            rows[key] = row
        _atomic_write(path, _jsonl_text([rows[k] for k in sorted(rows)]))
        return True


def rebuild_final(run_dir, config_id):
    """Rewrite final.<config>.jsonl from the complete unit records (recovery; normally kept in step by run_unit)."""
    units = load_units(run_dir, config_id, COMPLETE)
    rows = {(u["case_id"], int(u["repeat"])): u["final_row"] for u in units}
    with _run_lock(run_dir):
        _atomic_write(os.path.join(run_dir, f"final.{config_id}.jsonl"), _jsonl_text([rows[k] for k in sorted(rows)]))
    return len(rows)


def export_validated(run_dir, config_id):
    """Write validated.<config>.round<r>.jsonl from the complete units, for tools that read the batch layout
    (analysis/dev_failures.py, analysis/r1/activation_report.py --validated, analysis/derive_repair_ladder.py).
    Rows are sorted by (case_id, repeat). Returns {round: n rows}."""
    by_round = {}
    for u in load_units(run_dir, config_id, COMPLETE):
        for r in u["rounds"]:
            by_round.setdefault(r["round"], []).append(r["validated"])
    for rnd, rows in by_round.items():
        rows.sort(key=lambda v: (v["case_id"], int(v["repeat"])))
        _atomic_write(os.path.join(run_dir, f"validated.{config_id}.round{rnd}.jsonl"), _jsonl_text(rows))
    return {r: len(v) for r, v in sorted(by_round.items())}


def unit_messages(unit, rnd, index=-1):
    """The full messages of call `index` of round `rnd` (round 0 stores them whole; a repair call stores the two
    messages it appends to the previous round's answer call)."""
    rounds = {r["round"]: r for r in unit["rounds"]}
    entry = rounds[rnd]["calls"][index]
    if "messages" in entry:
        return copy.deepcopy(entry["messages"])
    return unit_messages(unit, rnd - 1, -1) + copy.deepcopy(entry["messages_appended"])


def derive_ladder(unit, k):
    """"At most k repair rounds" from one complete unit record: the final row (ladder.cut_entry, the same rule as
    ladder.derive_run) and the cost of the calls it keeps. No model call and no re-execution."""
    if unit.get("status") != COMPLETE:
        raise ValueError(f"{unit.get('unit_id')}: only complete units have a ladder")
    key = (unit["case_id"], int(unit["repeat"]))
    validated = {r["round"]: {key: r["validated"]} for r in unit["rounds"]}
    row, was_cut = L.cut_entry(unit["final_row"], validated, k)
    calls = [c["call"] for r in unit["rounds"] if r["round"] <= k for c in r["calls"]]
    prompt = sum(c.get("prompt_eval_count") or 0 for c in calls)
    completion = sum(c.get("eval_count") or 0 for c in calls)
    return {"final_row": row, "cut": was_cut, "max_repair_rounds": k,
            "cost": {"n_calls": len(calls), "prompt": prompt, "completion": completion, "total": prompt + completion}}


# ----------------------------------------------------------------------------------------------------- context


class UnitContext:
    """Run-level settings shared by every unit of a run directory. Build it with build_context()."""

    def __init__(self, run_dir, *, registry, store, genes_path, lexicon=None, cond_dir=None, tolerance=0.05,
                 timeout=60, python=None, model_entry=None, model_entry_record=None, opts=None, round0_run_dir=None,
                 run_id=None, c1_match_mode="tokens", c1_report=None, c1_tokenizer="qwen", tools_root=None,
                 c1_make_counter=None):
        if (model_entry is None) == (opts is None):
            raise UnitRefused("give exactly one of a model registry entry (study runs) or explicit opts")
        if c1_match_mode not in C1M.MATCH_MODES or c1_tokenizer not in C1M.TOKENIZERS:
            raise UnitRefused(f"C1 match mode must be one of {C1M.MATCH_MODES} and the C1 tokenizer one of "
                              f"{C1M.TOKENIZERS}")
        self.run_dir = run_dir
        self.run_id = run_id or os.path.basename(os.path.abspath(run_dir))
        self.registry = registry
        self.store = store
        self.genes_path = genes_path
        self.lexicon = F.load_lexicon(lexicon) if lexicon is not None else None
        self.cond_dir = cond_dir or C.DEFAULT_COND_DIR
        self.tolerance = tolerance
        self.timeout = timeout
        self.python = python
        self.model_entry = model_entry
        self.model_entry_record = model_entry_record
        self.base_opts = dict(opts) if opts is not None else None
        self.round0_run_dir = round0_run_dir or run_dir
        self.gate = None     # the freeze gate record of this process (freeze.gate_stage), set by the entry point
        self._sealed = None  # sealed case ids (test, eng_holdout), read once
        self._templates, self._c1_target, self._setup_ok = {}, {}, {}
        # C1 length matching (module doc): the same c1match.RequestsC1 as `orgene_cli.py requests`, built on first use
        self.c1_match_mode, self.c1_tokenizer, self.tools_root = c1_match_mode, c1_tokenizer, tools_root
        self.c1_report = c1_report or C1M.DEFAULT_REPORT
        self._c1_make_counter = c1_make_counter
        self._c1 = None
        self.registry_ids = CF.all_ids(registry)
        self.genes_sha256 = _sha_file(genes_path)
        CF.check_registry_against_store(registry, store)

    # -- settings ----------------------------------------------------------------------------------------------
    def opts_for(self, repeat):
        """What every call of repeat k sends: the registry entry's settings with seed = base + k (seed rule base+k)."""
        if self.model_entry is not None:
            from .model_registry import expected_opts
            return expected_opts(self.model_entry, repeat)
        o = dict(self.base_opts)
        if o.get("seed") is not None:
            o["seed"] = int(o["seed"]) + int(repeat)
        return o

    def guard_for(self, backend, repeat):
        return registry_guard(self.model_entry, backend=backend, repeat_index=repeat) if self.model_entry else None

    def check_config(self, cfg):
        """The configuration's generation limits must be the ones the registry entry sends (E03 registry fields)."""
        o = self.opts_for(0)
        bad = [f"{k}: configuration {cfg[k]!r}, model settings {o[k]!r}" for k in ("num_predict", "num_ctx")
               if k in o and o[k] != cfg[k]]
        if bad:
            raise UnitRefused(f"configuration {cfg['id']} does not match the model settings: " + "; ".join(bad))

    def templates(self, variant):
        if variant not in self._templates:
            self._templates[variant] = C.load_templates(self.cond_dir, variant)
        return self._templates[variant]

    def c1_target(self, variant):
        """The v5 C1 target (characters of the all-active C3 prompt); used in c1_match_mode "chars" only."""
        if variant not in self._c1_target:
            self._c1_target[variant] = C.c1_default_target(self.templates(variant), self.store)
        return self._c1_target[variant]

    def c1_setup(self):
        """The C1 matching settings of the run (part of units/setup.json)."""
        if self.c1_match_mode == "chars":
            return {"match_mode": "chars"}
        return {"match_mode": "tokens", "tokenizer": self.c1_tokenizer, "report": rel(self.c1_report)}

    def c1_matching(self):
        """c1match.RequestsC1 over the registry's C1 configurations, built once (in "tokens" mode it loads the matching
        report, checks that it is ok and current and builds the tokenizer). Any problem refuses the run."""
        if self._c1 is None:
            cfgs = [c for c in self.registry["configs"].values() if c.get("prompt") == "C1"]
            lex = self.lexicon if self.lexicon is not None else F.load_lexicon(None)  # as requests: the default lexicon
            try:
                self._c1 = C1M.RequestsC1(self.registry, cfgs, self.store, self.genes_path, self.cond_dir,
                                          self.tolerance, lex.sha256, match_mode=self.c1_match_mode,
                                          report_path=self.c1_report, tokenizer=self.c1_tokenizer, local_tokens="auto",
                                          tools_root=self.tools_root,
                                          make_counter=self._c1_make_counter or C1M.MAKE_COUNTER, lexicon=lex)
            except C.C1MatchError as e:
                raise UnitRefused(f"C1: {e}") from None
            except Exception as e:  # noqa: BLE001 - TokenizerError and friends: say what is missing
                raise UnitRefused(f"C1: local tokenizer unavailable: {type(e).__name__}: {scrub_paths(str(e))}") from None
        return self._c1

    def c1_kwargs(self, cfg):
        """conditions.build_request keyword arguments of a C1 configuration: the report's target and token measure
        ("tokens"), or the v5 character target ("chars")."""
        if self.c1_match_mode == "chars":
            return {"c1_target": self.c1_target(cfg.get("variant"))}
        try:
            return self.c1_matching().kwargs(cfg)
        except C.C1MatchError as e:
            raise UnitRefused(f"{cfg['id']}: {e}") from None

    def c1_check(self, cfg, req):
        """After a C1 request is built: in "tokens" mode its system prompt must be the one the report records (the
        replayed matching; c1match.RequestsC1.record). Returns the unit record's c1_matching block."""
        rc = self.c1_matching()
        if self.c1_match_mode == "chars":
            return rc.run_info()
        try:
            rc.record(cfg, [req], {})
        except C.C1MatchError as e:
            raise UnitRefused(f"{cfg['id']}: {e}") from None
        info = rc.run_info()
        return dict({k: info[k] for k in ("match_mode", "tokenizer", "report", "report_sha256")},
                    **rc.by_config[cfg["id"]])

    def features_for(self, case):
        return F.extract_features(case["text"], self.lexicon) if self.lexicon is not None else None

    def require_gate(self, case_id):
        """A sealed case (test or eng_holdout id) runs only after this process passed the E21 freeze gate (the entry
        point calls freeze.gate_stage once and stores the record in ctx.gate). Defence in depth for library callers."""
        if self._sealed is None:
            from .freeze import sealed_ids
            self._sealed = sealed_ids(ROOT)
        if case_id in self._sealed and not self.gate:
            raise UnitRefused(f"{case_id} is a sealed case; this process has not passed the freeze gate "
                              "(freeze.gate_stage('execute', ...) and ctx.gate = its record)")

    # -- run-level setup ---------------------------------------------------------------------------------------------
    def setup_record(self, backend):
        ident = backend.identity()
        o = self.opts_for(0)
        tok = backend.token_counter_identity() if backend.token_counter is not None else None
        return {
            "config_registry": {"path": self.registry.get("path"), "sha256": self.registry.get("sha256")},
            "gene_store": {"path": rel(self.genes_path), "file_sha256": self.genes_sha256},
            "lexicon": ({"path": self.lexicon.path, "sha256": self.lexicon.sha256} if self.lexicon else None),
            "cond_dir": rel(self.cond_dir),
            "templates_sha256": {k: v["sha256"] for k, v in self.templates(None)["files"].items()},
            "c1_tolerance": self.tolerance,
            "c1_matching": self.c1_setup(),
            "model": {"backend": backend.kind, "model": backend.model, "digest": ident.get("digest")},
            "model_registry": self.model_entry_record,
            "opts": {k: v for k, v in o.items() if k != "seed"},
            "seed_base": o.get("seed"),
            "exec_timeout": self.timeout,
            "local_tokens_counter": backend.token_counter_id,
            "local_tokenizer_sha256": _sha_obj(tok) if tok is not None else None,
            "round0_run": rel(self.round0_run_dir),
        }

    def check_setup(self, backend):
        """units/setup.json: written by the first unit of a run; a later unit under another setup is refused."""
        if id(backend) in self._setup_ok:
            return self._setup_ok[id(backend)]
        setup = self.setup_record(backend)
        path = os.path.join(self.run_dir, UNITS_DIR, SETUP_FILE)
        with _run_lock(self.run_dir):
            if os.path.exists(path):
                prev = read_unit(path).get("setup") or {}
                differ = sorted(k for k in set(prev) | set(setup) if prev.get(k) != setup.get(k))
                if differ:
                    raise UnitRefused(f"run directory {rel(self.run_dir)} was set up differently ({', '.join(differ)}); "
                                      "use a new run directory")
            else:
                _atomic_write(path, json.dumps({"schema_version": SETUP_SCHEMA, "created_at": now_iso(),
                                                "setup": setup}, ensure_ascii=False, indent=1) + "\n")
        sha = _sha_obj(setup)
        self._setup_ok[id(backend)] = sha
        return sha


def execution_timeout(registry_path=None):
    """Seconds per program execution: the model registry's execution.timeout_s (E19), default 60 when the registry has
    no execution block. E22's reexec.execution_timeouts() reads the same field with the same checks; once that module
    is on the branch it is used, so both paths read one function (until then this reader is equivalent)."""
    path = registry_path or DEFAULT_MODEL_REGISTRY
    try:
        from .reexec import execution_timeouts
    except ModuleNotFoundError as e:
        if e.name != f"{__package__}.reexec":
            raise
        execution_timeouts = None
    try:
        if execution_timeouts is not None:
            return execution_timeouts(path)["timeout_s"]
        ex = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                ex = json.load(f).get("execution") or {}
        t = ex.get("timeout_s", DEFAULT_EXEC_TIMEOUT_S)
        if not isinstance(t, int) or isinstance(t, bool) or t < 1:
            raise ValueError("execution.timeout_s must be a positive integer")
        return t
    except ValueError as e:
        raise UnitRefused(f"model registry {rel(path)}: {e}") from None


def load_model_entry(path, entry_id):
    """(entry, record) from the model registry (E19), record = {path, entry_id, entry_sha256} as the runners write it."""
    from . import runner as RN
    return RN.load_registry_entry(path, entry_id, prefix="[units]")


def build_context(run_dir, *, configs_path=None, genes_path=None, lexicon="default", cond_dir=None, tolerance=0.05,
                  timeout=None, python=None, model_registry=None, entry_id=None, opts=None, round0_run_dir=None,
                  c1_match_mode="tokens", c1_report=None, c1_tokenizer="qwen", tools_root=None, c1_make_counter=None):
    """UnitContext from files: configuration registry, gene library (checked with the lexicon), lexicon ("default" =
    genes/activation_lexicon.v1.json; None = no problem features, so per_problem configurations are refused), and
    either a model registry entry (model_registry + entry_id; study runs) or explicit opts. timeout None = the model
    registry's execution.timeout_s (execution_timeout). c1_match_mode / c1_report / c1_tokenizer / tools_root: the C1
    length matching, as the options of `orgene_cli.py requests` (module doc); c1_make_counter replaces the tokenizers
    (tests; default c1match.MAKE_COUNTER)."""
    from .env import orgene_python
    if timeout is None:
        timeout = execution_timeout(model_registry or DEFAULT_MODEL_REGISTRY)
    reg = CF.load_registry(configs_path)
    genes_path = genes_path or os.path.join(ROOT, "genes", "genes.r1.jsonl")
    python = python or orgene_python()
    lex = F.load_lexicon(None) if lexicon == "default" else (F.load_lexicon(lexicon) if lexicon is not None else None)
    store = G.load_store(genes_path, lexicon=lex)
    entry = record = None
    if entry_id is not None:
        entry, record = load_model_entry(model_registry or DEFAULT_MODEL_REGISTRY, entry_id)
    return UnitContext(run_dir, registry=reg, store=store, genes_path=genes_path, lexicon=lex, cond_dir=cond_dir,
                       tolerance=tolerance, timeout=timeout, python=python, model_entry=entry,
                       model_entry_record=record, opts=opts, round0_run_dir=round0_run_dir,
                       c1_match_mode=c1_match_mode, c1_report=c1_report, c1_tokenizer=c1_tokenizer,
                       tools_root=tools_root, c1_make_counter=c1_make_counter)


# ----------------------------------------------------------------------------------------------------- one unit


_CODE_SHA = {}


def _code_sha256():
    """sha256 of the code a unit runs through (recorded per unit; a change is recorded, not refused, as in the runner)."""
    if not _CODE_SHA:
        here = os.path.dirname(os.path.abspath(__file__))
        _CODE_SHA.update({rel(os.path.join(here, f)): _sha_file(os.path.join(here, f)) for f in CODE_FILES
                          if os.path.exists(os.path.join(here, f))})
    return dict(_CODE_SHA)


class UnitRun:
    """One (case, configuration, repeat) while it runs: its state and the hooks a pipeline function uses.

    Hooks (the interface for pipeline functions, including E15's run_ora):
      generate(messages, *, request_id, stage, rnd, meta=None) -> call record   one model call with this unit's
          settings (registry guard, seed = base + repeat); its tokens count against the cap; a failed call raises
          UnitIncomplete (the unit ends incomplete)
      check(call, rnd, request_id) -> (v, repair_text, applied)   pipeline.validate_one with this configuration's
          genes, repair kind, closing and max_rounds; repair is suppressed once the token cap is spent
      execute(code) -> exec dict             run_program under the solve recorder (what check() runs)
      repair_message(issues, exec_result) -> (text, applied)   genes.repair_turn with the registry's repair/closing and
          this unit's maxApplications bookkeeping (the generic template for repair "generic")
      add_round(v, repair_text, applied)     record a validated round (takes the calls made since the last round)
      tokens_used(), over_budget(), note_budget_stop(rnd, v)
      context_overflow(messages, rnd, request_id=None) -> None | context_exceeded record   the context window check
          of a call after round 0 (generate() repeats it for a call it has not seen checked)
      stop_for_context(v, info) -> (v, None, [])   end the unit at this round because the next repair does not fit
    """

    def __init__(self, ctx, case, config, repeat, backend, schedule=None):
        self.ctx, self.case, self.cfg, self.k, self.backend = ctx, case, config, int(repeat), backend
        self.schedule = schedule
        self.uid = unit_id(case["case_id"], config["id"], repeat)
        self.path = unit_path(ctx.run_dir, case["case_id"], config["id"], repeat)
        ctx.check_config(config)
        self.features = ctx.features_for(case)
        scope, mode = config["gene_scope"], config["activation"]
        if mode == "per_problem" and self.features is None:
            # E04: per-problem activation is evaluated on the problem's features; without them it is refused, never
            # silently replaced by activating every gene
            raise UnitRefused(f"{self.uid}: activation per_problem needs the problem features (no lexicon in the "
                              "unit context)")
        if scope is not None and mode != "none":
            self.active, self.trace, self.impl = C.activate_for(ctx.store, scope, mode, self.features)
        else:
            self.active, self.trace, self.impl = [], [], "none"
        self.inapplicable = CF.inapplicable_genes(config, ctx.registry, self.active) if self.active else []
        self.opts = ctx.opts_for(self.k)
        self.guard = ctx.guard_for(backend, self.k)
        self.act = config["repair"] != "none"
        # checklist repair (D12): the frozen checklist text, read once and checked against the C1 pool
        self.checklist = (C.review_checklist(C.load_templates(ctx.cond_dir, config.get("variant")))
                          if config["repair"] == "gene_generic" else None)
        self.force_review = bool(config.get("force_review", False))
        self.applications = {}
        self.rounds, self._pending = [], []
        self.tokens = {"prompt": 0, "completion": 0, "n_calls": 0, "n_calls_reused": 0,
                       "local": {"rendered_prompt": 0, "completion": 0, "n_calls_missing": 0}}
        self.timing = {"gen_wall_seconds": 0.0, "server_seconds": 0.0, "queue_wait_seconds": 0.0, "exec_seconds": 0.0}
        self.budget_stop = None
        self.context_exceeded = None
        self.context_check = {"rule": CONTEXT_RULE, "num_ctx": self.opts.get("num_ctx"),
                              "num_predict": self.opts.get("num_predict"), "checked": 0, "unchecked": 0,
                              "max_prompt_plus_predict": None}
        self._context_seen = {}  # sha256 of checked messages -> None (fits or unchecked) | context_exceeded record
        self.reuse_source = CF.reuse_source(config)
        self.reused_from = None
        self.src_entry = None  # (source unit, its round-0 call entry) once load_round0_source() has checked it
        self.request0 = None
        self.c1_matching = None  # how the C1 prompt was length-matched (C1 configurations only)
        self.started_at, self._t0 = None, None

    # -- round 0 request and shared round 0 --------------------------------------------------------------------------
    def round0_request(self):
        """This configuration's own round-0 request (conditions.build_request: messages [system, user], meta with the
        configuration's own config_id, activation trace, prompt and contract hashes). A C1 prompt is length-matched as
        `orgene_cli.py requests` matches it (module doc, C1 LENGTH MATCHING)."""
        if self.request0 is None:
            ctx, cfg = self.ctx, self.cfg
            variant = cfg.get("variant")
            kw = {"cond_dir": ctx.cond_dir, "templates": ctx.templates(variant), "tolerance": ctx.tolerance}
            if cfg["prompt"] == "C1":
                kw.update(ctx.c1_kwargs(cfg))
            try:
                req = C.build_request(cfg, self.case, ctx.store, ctx.run_id, features=self.features,
                                      registry_ids=ctx.registry_ids, **kw)
            except C.C1MatchError as e:
                raise UnitRefused(f"{self.uid}: {e}") from None
            if cfg["prompt"] == "C1":
                self.c1_matching = ctx.c1_check(cfg, req)
            got = [(g["geneId"], g["version"]) for g in self.active]
            want = [(g["geneId"], g["version"]) for g in req["meta"]["active_genes"]]
            if got != want:  # the genes a request was built with are the genes its answer is checked with
                raise UnitRefused(f"{self.uid}: request genes {len(want)} != validation genes {len(got)}")
            self.request0 = req
        return self.request0

    def load_round0_source(self):
        """Check the source unit of a shared round 0 (see the module doc); returns (source unit, its round-0 call)."""
        req = self.round0_request()
        src_id = self.reuse_source
        path = unit_path(self.ctx.round0_run_dir, self.case["case_id"], src_id, self.k)
        where = f"{self.uid} reuses the round 0 of {unit_id(self.case['case_id'], src_id, self.k)}"
        if not os.path.exists(path):
            raise ReuseError(f"{where}: that unit has not run (no record in {rel(os.path.dirname(path))})")
        src = read_unit(path)
        if src.get("status") != COMPLETE:
            raise ReuseError(f"{where}: that unit is {src.get('status')}, not complete")
        if (src.get("case_id"), src.get("config_id"), int(src.get("repeat", -1))) != \
                (self.case["case_id"], src_id, self.k):
            raise ReuseError(f"{where}: the record names another unit")
        entry = src["rounds"][0]["calls"][-1]
        call = entry["call"]
        content = call.get("content") or ""
        if not call.get("ok") or sha256_hex(content.encode("utf-8")) != call.get("content_sha256"):
            raise ReuseError(f"{where}: its round-0 content does not hash to the content_sha256 recorded when it was "
                             "generated (changed after generation)")
        if sha256_hex(canonical_json(req["messages"])) != call.get("messages_sha256") or \
                canonical_json(entry.get("messages")) != canonical_json(req["messages"]):
            raise ReuseError(f"{where}: its round-0 messages are not this configuration's round-0 messages")
        mine = request_sha256(self.backend.build_body(req["messages"], self.opts))
        if mine != call.get("request_sha256"):
            raise ReuseError(f"{where}: it answered another request (model or settings differ; request sha256 "
                             f"{str(call.get('request_sha256'))[:12]} vs {mine[:12]})")
        if call.get("model") != self.backend.model or call.get("digest") != self.backend.digest():
            raise ReuseError(f"{where}: it was generated by another model ({call.get('model')} "
                             f"{str(call.get('digest'))[:12]})")
        if src.get("model_registry") != self.ctx.model_entry_record:
            raise ReuseError(f"{where}: it ran under another model registry entry")
        return src, entry

    def reuse_round0(self, src_entry=None):
        """Take the source unit's round-0 call as this unit's round 0 (no model call)."""
        req = self.round0_request()
        src, entry = src_entry or self.src_entry or self.load_round0_source()
        call = copy.deepcopy(entry["call"])
        self.reused_from = {"unit_id": src["unit_id"], "config_id": src["config_id"],
                            "run": rel(self.ctx.round0_run_dir), "request_sha256": call["request_sha256"],
                            "content_sha256": call["content_sha256"], "call_sha256": _sha_obj(entry["call"])}
        self._pending.append({"stage": "round0", "round": 0, "request_id": req["request_id"],
                              "messages": req["messages"], "meta": req["meta"], "call": call, "reused": True})
        self._count(call, reused=True)
        return call

    # -- hooks ---------------------------------------------------------------------------------------------------
    def generate(self, messages, *, request_id, stage, rnd, meta=None, appended=None):
        """One model call. `appended` (the messages added to the previous call's conversation) is stored instead of the
        full messages for calls after round 0."""
        if rnd >= 1:
            info = self.context_overflow(messages, rnd, request_id)  # cached when the pipeline checked it already
            if info is not None:  # never send a call that overflows the context window
                self.context_exceeded = dict(info)
                raise UnitIncomplete(f"call {request_id} not made: prompt {info['local_prompt_tokens']} + num_predict "
                                     f"{info['num_predict']} > num_ctx {info['num_ctx']} (local count)",
                                     kind="context_exceeded", stage=stage, rnd=rnd)
        entry = {"stage": stage, "round": rnd, "request_id": request_id, "meta": meta, "reused": False}
        if appended is None:
            entry["messages"] = messages
        else:
            entry["messages_appended"] = appended
        try:
            call = self.backend.call(messages, self.opts, guard=self.guard)
        except (OptionsError, RegistryMismatch) as e:
            raise UnitRefused(f"{self.uid} {stage}: refused before sending: {e}") from None
        except Exception as e:  # noqa: BLE001 - any exception from the backend ends the unit incomplete
            raise UnitIncomplete(scrub_paths(f"{type(e).__name__}: {e}")[:500], kind="backend_exception",
                                 stage=stage, rnd=rnd) from None
        entry["call"] = call
        self._pending.append(entry)
        self._count(call)
        if not call.get("ok"):
            errs = [a.get("error") for a in call.get("attempts") or [] if a.get("error")]
            raise UnitIncomplete(f"call {request_id} failed after {len(call.get('attempts') or [])} attempt(s)"
                                 + (f": {errs[-1]}" if errs else ""), kind="call_failed", stage=stage, rnd=rnd)
        return call

    def execute(self, code):
        return P.run_program(code, timeout=self.ctx.timeout, python=self.ctx.python)

    def repair_message(self, issues, exec_result):
        kw = {"checklist": self.checklist} if self.cfg["repair"] == "gene_generic" else {}
        return G.repair_turn(self.active, issues, self.applications, exec_result=exec_result, condition=self.cfg["id"],
                             repair=self.cfg["repair"], closing=self.cfg["closing"], **kw)

    def check(self, call, rnd, request_id):
        cfg = self.cfg
        budget_ok = not self.over_budget()
        v, text, applied = P.validate_one(
            self.case, dict(call, request_id=request_id), self.active, rnd, self.applications, cond=cfg["id"],
            repeat=self.k, act=self.act, max_rounds=cfg["max_rounds"], repair=cfg["repair"] if self.act else None,
            closing=cfg["closing"] if self.act else None, timeout=self.ctx.timeout, python=self.ctx.python,
            inapplicable=self.inapplicable, budget_ok=budget_ok, checklist=self.checklist,
            force_review=self.force_review)
        self.timing["exec_seconds"] += (v.get("exec") or {}).get("seconds") or 0.0
        if not budget_ok:
            self.note_budget_stop(rnd, v)
        return v, text, applied

    def note_budget_stop(self, rnd, v):
        """Record that the cap stopped a repair that would otherwise have been asked for after round `rnd`."""
        if not (self.act and v["hard_failed_genes"] and rnd < self.cfg["max_rounds"]):
            return
        would, _ = self.repair_message(v["issues"], v.get("exec"))
        if would:
            self.budget_stop = {"round": rnd, "tokens_used": self.tokens_used(), "token_cap": self.cfg.get("token_cap"),
                                "hard_failed_genes": list(v["hard_failed_genes"])}

    def context_overflow(self, messages, rnd, request_id=None):
        """The context window check of a call after round 0 (module doc, CONTEXT WINDOW). Returns None when the call
        fits or cannot be checked (counted in context_check), else the context_exceeded record of the call."""
        key = _sha_obj(messages)
        if key in self._context_seen:
            return self._context_seen[key]
        cc, counter = self.context_check, self.backend.token_counter
        n_ctx, n_pred = cc["num_ctx"], cc["num_predict"]
        info = None
        if counter is None or not n_ctx or not n_pred:
            cc["unchecked"] += 1
        else:
            try:
                think = self.backend.sent_opts(self.backend.build_body(messages, self.opts)).get("think")
                if hasattr(counter, "count_prompt"):
                    n = int(counter.count_prompt(messages, think)[0])
                else:
                    n = int(self.backend.count_local(messages, "", think=think)["rendered_prompt"])
            except Exception:  # noqa: BLE001 - an uncountable prompt is not checked (and is counted as such)
                n = None
                cc["unchecked"] += 1
            if n is not None:
                cc["checked"] += 1
                total = n + int(n_pred)
                cc["max_prompt_plus_predict"] = max(cc["max_prompt_plus_predict"] or 0, total)
                if total > int(n_ctx):
                    info = {"round": rnd, "request_id": request_id, "local_prompt_tokens": n, "num_predict": n_pred,
                            "num_ctx": n_ctx, "prompt_plus_predict": total,
                            "local_tokens_counter": self.backend.token_counter_id}
        self._context_seen[key] = info
        return info

    def stop_for_context(self, v, info):
        """The repair after this round does not fit the context window: the unit ends with this round's answer as its
        result, like a unit whose repairs ran out (decision accepted, no genes applied); v (so the validated record and
        the final row) carries the context_exceeded record. Returns (v, None, []) for add_round."""
        self.context_exceeded = dict(info)
        return dict(v, decision="accepted", repair_applied_genes=[], context_exceeded=dict(info)), None, []

    def add_round(self, v, repair_text, applied):
        self.rounds.append({"round": v["round"], "calls": self._pending, "validated": v, "repair_text": repair_text,
                            "repair_applied_genes": list(applied)})
        self._pending = []
        for gid in applied:
            self.applications[gid] = self.applications.get(gid, 0) + 1
        self.write(RUNNING)

    def tokens_used(self):
        return self.tokens["prompt"] + self.tokens["completion"]

    def over_budget(self):
        cap = self.cfg.get("token_cap")
        return cap is not None and self.tokens_used() >= cap

    def _count(self, call, reused=False):
        self.tokens["prompt"] += call.get("prompt_eval_count") or 0
        self.tokens["completion"] += call.get("eval_count") or 0
        self.tokens["n_calls"] += 1
        self.tokens["n_calls_reused"] += int(reused)
        lt = call.get("local_tokens")
        if isinstance(lt, dict):
            self.tokens["local"]["rendered_prompt"] += lt.get("rendered_prompt") or 0
            self.tokens["local"]["completion"] += lt.get("completion") or 0
        elif call.get("ok"):
            self.tokens["local"]["n_calls_missing"] += 1
        if not reused:
            wall = call.get("wall_seconds") or 0.0
            server = (call.get("total_duration_ns") or 0) / 1e9
            self.timing["gen_wall_seconds"] += wall
            self.timing["server_seconds"] += server
            self.timing["queue_wait_seconds"] += max(0.0, wall - server) if server else 0.0

    # -- record ------------------------------------------------------------------------------------------------------
    def final_row(self):
        prev = None
        for r in self.rounds:
            prev = P.final_entry(r["validated"], prev)
        return prev

    def record(self, status, stop_reason=None, error=None):
        cfg, backend = self.cfg, self.backend
        tok = backend.token_counter_identity() if backend.token_counter is not None else None
        rec = {
            "schema_version": UNIT_SCHEMA,
            "unit_id": self.uid, "case_id": self.case["case_id"], "config_id": cfg["id"], "repeat": self.k,
            "run_id": self.ctx.run_id, "source": self.case.get("source"),
            "status": status, "stop_reason": stop_reason, "error": error,
            "pipeline": cfg.get("pipeline", "standard"),
            "config": cfg,
            "setup_sha256": self.ctx.check_setup(backend),
            "model": {"backend": backend.kind, "model": backend.model, "digest": backend.digest()},
            "model_registry": self.ctx.model_entry_record,
            "opts": self.opts,
            "local_tokenizer": tok,
            "features_sha256": C.features_digest(self.features),
            "activation": {"gene_scope": cfg["gene_scope"], "mode": cfg["activation"], "impl": self.impl,
                           "active_genes": [{"geneId": g["geneId"], "version": g["version"]} for g in self.active],
                           "gene_set_digest": G.store_digest(self.active) if self.impl != "none" else None,
                           "trace": self.trace},
            "inapplicable_genes": self.inapplicable,
            "c1_matching": self.c1_matching,
            "round0": {"source": cfg["round0"], "reused_from": self.reused_from},
            "rounds": self.rounds,
            "pending_calls": self._pending,
            "applications": dict(self.applications),
            "tokens": dict(self.tokens, total=self.tokens_used()),
            "token_cap": cfg.get("token_cap"), "token_cap_counts": TOKEN_CAP_COUNTS, "budget_stop": self.budget_stop,
            "exec_timeout_s": self.ctx.timeout,
            "context_check": dict(self.context_check), "context_exceeded": self.context_exceeded,
            "timing":dict(self.timing, wall_seconds=round(time.monotonic() - self._t0, 3) if self._t0 else None),
            "final_row": self.final_row() if status == COMPLETE else None,
            "schedule": self.schedule,
            "started_at": self.started_at, "finished_at": now_iso() if status != RUNNING else None,
            "code_sha256": _code_sha256(),
        }
        return rec

    def write(self, status, stop_reason=None, error=None):
        rec = self.record(status, stop_reason, error)
        _atomic_write(self.path, json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")  # compact
        return rec


# ----------------------------------------------------------------------------------------------------- pipelines


def stop_reason(u, v, rnd):
    """Why a unit stopped after validating round rnd (no repair was asked for)."""
    if not u.act:
        return "observe_only"
    if not v["hard_failed_genes"]:
        return "accepted"
    if u.context_exceeded is not None:
        return "context_exceeded"
    if u.budget_stop is not None:
        return "token_cap"
    if rnd >= u.cfg["max_rounds"]:
        return "rounds_exhausted"
    return "no_repair_left"


def run_standard(u):
    """Round 0 (generated, or shared) -> checks -> execution -> checks -> repair ..., up to max_rounds. The repair
    request of round r+1 is the previous conversation plus [the answer, the repair message], exactly as the batch path
    builds requests.<config>.repair<r+1>.jsonl, with the same request ids. A repair request that would not fit the
    context window is not sent: the unit stops at the round before it (stop_reason context_exceeded)."""
    req = u.round0_request()
    if u.reuse_source:
        call = u.reuse_round0()
    else:
        call = u.generate(req["messages"], request_id=req["request_id"], stage="round0", rnd=0, meta=req["meta"])
    messages, rid, rnd = list(req["messages"]), req["request_id"], 0
    cid, k = u.case["case_id"], u.k
    while True:
        v, text, applied = u.check(call, rnd, rid)
        if text:
            appended = [{"role": "assistant", "content": call.get("content") or ""}, {"role": "user", "content": text}]
            nxt_rid = f"{cid}.{u.cfg['id']}.rep{k}.repair{rnd + 1}"
            over = u.context_overflow(messages + appended, rnd + 1, nxt_rid)
            if over is not None:
                v, text, applied = u.stop_for_context(v, over)
        u.add_round(v, text, applied)
        if not text:
            return stop_reason(u, v, rnd)
        messages = messages + appended
        parent, rnd = rid, rnd + 1
        rid = nxt_rid
        meta = {"round": rnd, "orig_repeat": k, "repair_applications": dict(u.applications),
                "parent_request_id": parent, "repaired_genes": list(applied)}
        call = u.generate(messages, request_id=rid, stage=f"repair{rnd}", rnd=rnd, meta=meta, appended=appended)


def pipeline_runner(config):
    """The function that drives a unit of this configuration (the dispatch point for config["pipeline"])."""
    name = config.get("pipeline", "standard")
    if name == "standard":
        return run_standard
    if name not in PIPELINE_IMPLS:
        raise PipelineNotImplemented(f"configuration {config['id']}: unknown pipeline {name!r}")
    mod, fn = PIPELINE_IMPLS[name]
    try:
        m = importlib.import_module(f"{__package__}.{mod}")
    except ModuleNotFoundError as e:
        if e.name != f"{__package__}.{mod}":
            raise
        m = None
    if m is None or not hasattr(m, fn):
        raise PipelineNotImplemented(f"configuration {config['id']}: pipeline {name!r} is not implemented yet "
                                     f"({__package__}.{mod}.{fn}(u) -> stop reason; see unit_exec's module doc)")
    return getattr(m, fn)


def check_pipelines(configs):
    """Refuse before anything runs when a configuration's pipeline has no implementation."""
    for c in configs:
        pipeline_runner(c)


# ----------------------------------------------------------------------------------------------------- run_unit


def unit_state(run_dir, case_id, config_id, repeat):
    """running | complete | incomplete | None (no record)."""
    p = unit_path(run_dir, case_id, config_id, repeat)
    return read_unit(p).get("status") if os.path.exists(p) else None


def run_unit(case, config, repeat, backend, ctx, *, schedule=None):
    """Run one (case, configuration, repeat) unit; see the module doc. Returns the unit record."""
    runner = pipeline_runner(config)  # before anything is written
    ctx.require_gate(case["case_id"])
    setup_sha = ctx.check_setup(backend)
    path = unit_path(ctx.run_dir, case["case_id"], config["id"], repeat)
    key = (case["case_id"], int(repeat))
    if os.path.exists(path):
        old = read_unit(path)
        if old.get("status") == COMPLETE:
            if old.get("setup_sha256") != setup_sha or old.get("config") != config:
                raise UnitRefused(f"{old.get('unit_id')} is complete under another setup or configuration; "
                                  "use a new run directory")
            upsert_final(ctx.run_dir, config["id"], key, old["final_row"])
            return old
    u = UnitRun(ctx, case, config, repeat, backend, schedule=schedule)
    if config.get("pipeline", "standard") == "standard":
        u.round0_request()
        if u.reuse_source:
            u.src_entry = u.load_round0_source()  # checked before anything of this unit is written
    u.started_at, u._t0 = now_iso(), time.monotonic()
    u.write(RUNNING)
    try:
        reason = runner(u)
        if reason not in STOP_REASONS:
            raise UnitError(f"{u.uid}: pipeline returned an unknown stop reason {reason!r}")
    except UnitIncomplete as e:
        rec = u.write(INCOMPLETE, error={"kind": e.kind, "stage": e.stage, "round": e.round, "message": str(e)})
        upsert_final(ctx.run_dir, config["id"], key, None)
        return rec
    except UnitRefused as e:
        u.write(INCOMPLETE, error={"kind": "refused", "stage": None, "round": None, "message": str(e)})
        upsert_final(ctx.run_dir, config["id"], key, None)
        raise
    except Exception as e:  # noqa: BLE001 - recorded, then re-raised
        u.write(INCOMPLETE, error={"kind": "exception", "stage": None, "round": None,
                                   "message": scrub_paths(f"{type(e).__name__}: {e}")[:500]})
        upsert_final(ctx.run_dir, config["id"], key, None)
        raise
    rec = u.write(COMPLETE, stop_reason=reason)
    upsert_final(ctx.run_dir, config["id"], key, rec["final_row"])
    return rec



# ----------------------------------------------------------------------------------------------------- before a batch


def preflight_registry_check(entry_id, registry_path=None, runner=subprocess.run, python=None):
    """E19: `tools/model_registry.py check --quick --entry <id>` before a batch of model calls (read-only: Ollama
    identity, server settings, interpreter). Raises UnitRefused unless it reports OK."""
    tool = os.path.join(ROOT, "tools", "model_registry.py")
    cmd = [python or sys.executable, tool, "--registry", registry_path or DEFAULT_MODEL_REGISTRY, "check", "--quick",
           "--entry", entry_id]
    p = runner(cmd, capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        tail = " | ".join(((p.stdout or "") + (p.stderr or "")).strip().splitlines()[-3:])
        raise UnitRefused(f"model registry check failed for entry {entry_id} (exit {p.returncode}): {scrub_paths(tail)}")
    return (p.stdout or "").strip().splitlines()[-1:] or [""]


def attach_local_counter(backend, local_tokens=True, counter=None, counter_id=None):
    """E08/E09: hang a local token counter on the backend. Default for Ollama: orgene.tokcount.OllamaCounter over the
    blobs the server serves (the server's digest must be the local manifest's). Raises UnitRefused when it cannot be
    built. Returns the counter (None with local_tokens False)."""
    if counter is None and local_tokens:
        if backend.kind != "ollama":
            raise UnitRefused(f"no built-in local token counter for backend {backend.kind}; pass one")
        from .tokcount import OllamaCounter, TokenizerError
        digest = backend.digest()
        try:
            if not digest:
                raise TokenizerError(f"the server reports no digest for {backend.model}")
            counter = OllamaCounter(backend.model, expect_digest=digest)
        except TokenizerError as e:
            raise UnitRefused(f"local token counts unavailable: {e}") from None
        counter_id = "orgene.tokcount:OllamaCounter"
    if counter is not None:
        backend.token_counter = counter
        backend.token_counter_id = counter_id or type(counter).__name__
    return counter


def precheck_render(ctx, backend, units):
    """E09: render every round-0 request of `units` [(case, config, repeat)] with the local template port before the
    first call (a request the port cannot render would leave its calls without local counts). No-op without a counter
    that renders. Raises UnitRefused naming the first request that fails."""
    counter = backend.token_counter
    if counter is None or not hasattr(counter, "render"):
        return 0
    from .tokcount import TokenizerError
    n = 0
    for case, cfg, k in units:
        if cfg.get("pipeline", "standard") != "standard":
            continue
        u = UnitRun(ctx, case, cfg, k, backend)
        req = u.round0_request()
        try:
            counter.render(req["messages"], u.opts.get("think"))
        except TokenizerError as e:
            raise UnitRefused(f"local token counts unavailable for {req['request_id']}: {e}") from None
        n += 1
    return n


def default_order(cases, configs, repeats=1):
    """A fixed order that runs every round-0 source before the units that reuse it: for each repeat, configurations
    that generate their own round 0 first (in the given order), then the reusing ones, each over all cases. E07's
    plan replaces this with the seeded shuffle plus its dependency rule."""
    own = [c for c in configs if CF.reuse_source(c) is None]
    reuse = [c for c in configs if CF.reuse_source(c) is not None]
    return [(case, c, k) for k in range(repeats) for c in own + reuse for case in cases]


# ----------------------------------------------------------------------------------------------------- command line


def gate_inputs(cases_path, genes_path, configs_path, lexicon_path, cond_dir, model_registry, c1_report=None):
    """Files a unit run reads that decide what is sent to the model or how answers are checked: under the test gate
    each must be covered by the freeze (freeze.unfrozen_inputs; the same list as cli._gate_inputs for requests and
    validate, plus the model registry). c1_report: the C1 matching report when the run builds a token-matched C1."""
    paths = [cases_path, genes_path, configs_path, lexicon_path or F.DEFAULT_LEXICON, model_registry]
    paths += C.template_input_paths(cond_dir)
    if c1_report:
        paths.append(c1_report)
    return paths


def _run_config_update(run_dir, a, cases, cfgs, ctx):
    """Record what the unit run covers in <run>/run_config.json (the test gate of later stages reads its split)."""
    p = os.path.join(run_dir, "run_config.json")
    cfg = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    for key, now in (("split", a.split), ("config_registry", {"path": ctx.registry["path"],
                                                              "sha256": ctx.registry["sha256"]})):
        if key in cfg and cfg[key] != now:
            raise UnitRefused(f"run directory {rel(run_dir)} was set up with another {key}; use a new run directory")
    cfg.update({"run_id": ctx.run_id, "cases_path": rel(a.cases), "split_dir": rel(a.split_dir), "split": a.split,
                "config_registry": {"path": ctx.registry["path"], "sha256": ctx.registry["sha256"]},
                "conditions": sorted(set(cfg.get("conditions", [])) | {c["id"] for c in cfgs})})
    ue = cfg.setdefault("unit_executor", {"schema_version": UNIT_SCHEMA, "cases": []})
    ue["cases"] = sorted(set(ue.get("cases", [])) | {c["case_id"] for c in cases})
    ue["repeats"] = max(int(ue.get("repeats", 0)), a.repeat)
    _atomic_write(p, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")


def add_runner_options(ap, *, require_selection=True):
    """Shared E06/E07 options; E07 derives conditions and model entries from its sealed plan."""
    ap.add_argument("--run", required=True, help="experiments/<run-id>")
    ap.add_argument("--cases", required=True)
    ap.add_argument("--split-dir", default=None)
    ap.add_argument("--split", choices=["dev", "test", "eng_holdout"], default=None,
                    help="eng_holdout: the engineering-source cases (E22); sealed like test")
    ap.add_argument("--limit", type=int, default=None)
    if require_selection:
        ap.add_argument("--cond", nargs="+", required=True, help="configuration ids from the registry")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--configs", default=CF.DEFAULT_REGISTRY)
    ap.add_argument("--genes", default=os.path.join(ROOT, "genes", "genes.r1.jsonl"))
    ap.add_argument("--lexicon", default=None, help="activation lexicon (default genes/activation_lexicon.v1.json)")
    ap.add_argument("--cond-dir", default=C.DEFAULT_COND_DIR)
    ap.add_argument("--tolerance", type=float, default=0.05)
    ap.add_argument("--timeout", type=int, default=None,
                    help="seconds per program execution (default: execution.timeout_s of the model registry)")
    ap.add_argument("--python", default=None)
    ap.add_argument("--registry", default=DEFAULT_MODEL_REGISTRY, help="model registry (E19)")
    if require_selection:
        ap.add_argument("--registry-entry", required=True)
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--call-timeout", type=int, default=900)
    ap.add_argument("--max-attempts", type=int, default=2)
    ap.add_argument("--local-tokens", choices=["on", "off"], default="on")
    ap.add_argument("--c1-match-mode", choices=C1M.MATCH_MODES, default="tokens",
                    help="C1 length matching, as for `orgene_cli.py requests`: tokens (from the C1 matching report; "
                         "default) or chars (the v5 rule, regression only)")
    ap.add_argument("--c1-report", default=None, help="C1 matching report (default conditions/c1_matching_report.json)")
    ap.add_argument("--c1-tokenizer", choices=C1M.TOKENIZERS, default="qwen",
                    help="whose C1: qwen (main model) or api (C1-api when the report says it is needed)")
    ap.add_argument("--tools-root", default=None, help="where .venv-tools/ and .cache/tiktoken/ are (default: the repository)")
    ap.add_argument("--no-registry-check", action="store_true",
                    help="skip `model_registry.py check --quick` (tests and fake servers only)")
    ap.add_argument("--export-validated", action="store_true", help="also write validated.<config>.round<r>.jsonl")
    return ap


def build_parser():
    ap = argparse.ArgumentParser(prog="unit_runner", description="Run (case, configuration, repeat) units (E06).")
    return add_runner_options(ap)


def prepare_run(a, *, planned_units=None, extra_inputs=(), allowed_backends=None, input_guard=None):
    """E06 preflight shared with E07. No model generation; preserve E21/E19/render safeguards.

    planned_units selects exact (case_id, config_id, repeat) triples for one model context.
    Every selected id must occur in the requested split; no source is implicitly added.
    """
    from . import data as D
    from . import env as E
    from . import freeze as FZ
    from . import split as S
    from .backends import make_backend
    try:
        reg = CF.load_registry(a.configs)
        cfgs = [CF.get_config(reg, c) for c in a.cond]
        check_pipelines(cfgs)
    except (CF.RegistryError, UnitRefused) as e:
        raise SystemExit(f"[units] {e}")
    c1_report = None
    if a.c1_match_mode == "tokens" and any(c.get("prompt") == "C1" for c in cfgs):
        c1_report = a.c1_report or C1M.DEFAULT_REPORT
    inputs = gate_inputs(a.cases, a.genes, a.configs, a.lexicon, a.cond_dir, a.registry,
                         c1_report=c1_report) + list(extra_inputs)
    planned_ids = {u["case_id"] for u in planned_units} if planned_units is not None else None

    def check_gate(case_ids):
        try:
            return FZ.gate_stage("execute", run_dir=a.run, case_ids=case_ids, split=a.split,
                                 split_dir=a.split_dir, inputs=inputs)
        except FZ.GateRefused as e:
            raise SystemExit(f"[units] refused by the test gate: {e}") from e

    # Explicit sealed splits are refused even before opening a missing split-id file.
    # E07 already supplies ids; the default runner needs only top-level identity metadata.
    gate = check_gate(planned_ids or []) if a.split in FZ.SEALED_SPLITS else None
    ids = S.load_split_ids(a.split_dir, a.split) if (a.split_dir and a.split) else None
    if planned_ids is None:
        chosen_ids = D.load_case_ids(a.cases, ids)
        if a.limit:
            chosen_ids = chosen_ids[:a.limit]  # retain E06 file order and original slicing behavior
    else:
        if ids is not None and planned_ids - ids:
            raise SystemExit("[units] planned case ids absent from selected split: " + str(sorted(planned_ids - ids)))
        chosen_ids = list(planned_ids)
    if a.split not in FZ.SEALED_SPLITS:
        gate = check_gate(chosen_ids)
    # Protected payloads are first materialized here, after the gate accepted selected identities.
    # Skip excluded records lexically, so a dev run also does not deserialize test payloads.
    cases = D.load_cases(a.cases, set(chosen_ids), metadata_only_filter=True)
    if planned_units is None and a.limit:
        cases = cases[:len(chosen_ids)]  # ids already sliced once, including a negative limit
    if planned_units is not None:
        if a.limit:
            # E07 previously limited the split's file order before selecting plan ids.
            available_ids = D.load_case_ids(a.cases, ids)[:a.limit]
            if planned_ids - set(available_ids):
                raise SystemExit("[units] planned case ids absent from selected split or limit")
        available = {c["case_id"] for c in cases}
        if planned_ids - available:
            raise SystemExit("[units] planned case ids absent from cases file: " + str(sorted(planned_ids - available)))
    if input_guard is not None:
        input_guard(a, cases, gate)
    python = a.python or E.orgene_python()
    E.require_env(python)
    try:
        if not a.no_registry_check:
            preflight_registry_check(a.registry_entry, a.registry)
        ctx = build_context(a.run, configs_path=a.configs, genes_path=a.genes,
                            lexicon=a.lexicon if a.lexicon else "default", cond_dir=a.cond_dir, tolerance=a.tolerance,
                            timeout=a.timeout, python=python, model_registry=a.registry, entry_id=a.registry_entry,
                            c1_match_mode=a.c1_match_mode, c1_report=a.c1_report, c1_tokenizer=a.c1_tokenizer,
                            tools_root=a.tools_root)
        ctx.gate = gate
        entry = ctx.model_entry
        if allowed_backends is not None and entry["backend"] not in allowed_backends:
            raise UnitRefused("scheduler only permits local model backends; this registry entry is not local")
        backend = make_backend(entry["backend"], entry["model"], host=a.host, timeout=a.call_timeout,
                               max_attempts=a.max_attempts)
        attach_local_counter(backend, local_tokens=a.local_tokens == "on")
        if planned_units is None:
            units = default_order(cases, cfgs, a.repeat)
        else:
            by_id = {c["case_id"]: c for c in cases}
            units = [(by_id[u["case_id"]], CF.get_config(reg, u["config_id"]), u["repeat"])
                     for u in planned_units]
        for _, c, _ in units:
            ctx.check_config(c)
        precheck_render(ctx, backend, units)
        _run_config_update(a.run, a, cases, cfgs, ctx)
    except UnitRefused as e:
        raise SystemExit(f"[units] {e}")
    return {"args": a, "ctx": ctx, "backend": backend, "units": units, "gate": gate, "configs": cfgs}


def finish_run(prepared, counts):
    """Preserve E06 validated export and post-run identity drift refusal."""
    a, backend, cfgs = prepared["args"], prepared["backend"], prepared["configs"]
    if a.export_validated:
        for c in cfgs:
            export_validated(a.run, c["id"])
    start = backend.identity()
    try:
        end = backend.identity(refresh=True)
    except Exception as e:
        print(f"[units] WARNING: could not re-check the model identity: {type(e).__name__}", file=sys.stderr)
        end = start
    drift = sorted(k for k in ("digest", "template_sha256", "ollama_version", "parameters_from_modelfile")
                   if start.get(k) != end.get(k))
    if drift:
        print(f"[units] ERROR: the server's model identity changed during the run: {drift}", file=sys.stderr)
        return 3
    return 0 if not counts.get(INCOMPLETE) else 4


def main(argv=None):
    """Run units in default_order (sources of shared round 0 first). One process = one freeze gate check (E21)."""
    a = build_parser().parse_args(argv)
    prepared = prepare_run(a)
    ctx, backend, units, gate = (prepared[k] for k in ("ctx", "backend", "units", "gate"))
    counts = {}
    t0 = time.time()
    for i, (case, cfg, k) in enumerate(units, 1):
        try:
            rec = run_unit(case, cfg, k, backend, ctx, schedule={"order": "default_order", "index": i - 1,
                                                                  "freeze_gate": bool(gate)})
        except UnitRefused as e:
            raise SystemExit(f"[units] {e}")
        st = rec["status"] if rec["status"] != COMPLETE else f"complete:{rec['stop_reason']}"
        counts[st] = counts.get(st, 0) + 1
        print(f"[units] {i}/{len(units)} {rec['unit_id']} {st} calls={rec['tokens']['n_calls']} "
              f"tokens={rec['tokens']['total']} elapsed={(time.time() - t0) / 60:.1f} min", flush=True)
    print(f"[units] done: {json.dumps(counts, sort_keys=True)}", flush=True)
    return finish_run(prepared, counts)
