"""CLI: python3 orgene_cli.py <subcommand> ... (run from the runtime/ directory or via runtime/orgene_cli.py)."""
import argparse
import hashlib
import importlib.util
import json
import os
import sys

from . import c1match as C1M
from . import conditions as C
from . import configs as CF
from . import data as D
from . import env as E
from . import genes as G
from . import pipeline as P
from . import split as S
from .paths import ROOT, rel

# R1 working gene library (neutral successor of the v5 genes.v3.jsonl, which stays in releases/v1.0/)
DEFAULT_GENES = os.path.join(ROOT, "genes", "genes.r1.jsonl")
DEFAULT_COND_DIR = os.path.join(ROOT, "conditions")


def cmd_cases(a):
    h = D.build_cases(a.source, a.raw, a.out)
    print(json.dumps(h, indent=2, ensure_ascii=False))


def cmd_split(a):
    info = S.make_split(a.cases, a.out, a.n_dev, a.seed, force=a.force)
    print(json.dumps(info, indent=2))


def cmd_contract(a):
    store = G.load_store(a.genes)
    active, trace = G.activate(store, condition="C3")
    text, info = G.compile_contract(active)
    print(text)
    print(f"# active genes: {len(active)}  store digest: {G.store_digest(active)[:16]}  contract sha256: {info['contract_sha256'][:16]}", file=sys.stderr)


def _load_cases_for(a):
    ids = None
    if a.split_dir and a.split:
        ids = S.load_split_ids(a.split_dir, a.split)
    cases = D.load_cases(a.cases, ids)
    if a.limit:
        cases = cases[: a.limit]
    return cases


def _registry_configs(reg, ids, tag):
    try:
        return [CF.get_config(reg, c) for c in ids]
    except CF.RegistryError as e:
        sys.exit(f"[{tag}] {e}")


def _features_by_case(a, cases):
    """({case_id: features}, lexicon info) from the problem text of every case (E04 features.extract_features), or
    (None, None) in a checkout without the features module. Computed for every configuration, so every request
    records its features_sha256; only per-problem activation uses the values."""
    if importlib.util.find_spec(f"{__package__}.features") is None:
        return None, None
    from . import features as F
    lex = F.load_lexicon(a.lexicon)
    return ({c["case_id"]: F.extract_features(c["text"], lex) for c in cases},
            {"path": getattr(lex, "path", None), "sha256": getattr(lex, "sha256", None)})


def _sha_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def cmd_requests(a):
    reg = CF.load_registry(a.configs)
    cfgs = _registry_configs(reg, a.cond, "requests")
    other = [c["id"] for c in cfgs if c.get("pipeline", "standard") != "standard"]
    if other:
        sys.exit(f"[requests] {other} build their own stage prompts (pipeline is not 'standard'); not built here")
    store = G.load_store(a.genes)
    CF.check_registry_against_store(reg, store)
    py_env = E.require_env(a.python)
    cfg_path = os.path.join(a.run, "run_config.json")
    cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
    reg_info = {"path": reg["path"], "sha256": reg["sha256"]}
    genes_sha = _sha_file(a.genes)
    if cfg.get("config_registry", reg_info) != reg_info:
        sys.exit("[requests] this run directory was set up with another configuration registry; use a new run directory")
    prompts = cfg.get("prompts") if isinstance(cfg.get("prompts"), dict) and "by_config" in cfg["prompts"] else {}
    if prompts.get("gene_store_file_sha256", genes_sha) != genes_sha:
        sys.exit("[requests] this run directory was set up with another gene library; use a new run directory")
    # the run-level prompt record (cond_dir, templates, tolerance) must describe every configuration built into this run
    tmpl_sha = {k: v["sha256"] for k, v in C.load_templates(a.cond_dir)["files"].items()}
    for key, now, what in (("cond_dir", rel(a.cond_dir), "prompt template directory"),
                           ("template_sha256", tmpl_sha, "set of prompt templates"),
                           ("tolerance", a.tolerance, "C1 length tolerance")):
        if prompts.get(key, now) != now:
            sys.exit(f"[requests] this run directory was set up with another {what}; use a new run directory")
    os.makedirs(a.run, exist_ok=True)
    cases = _load_cases_for(a)
    run_id = os.path.basename(os.path.abspath(a.run))
    sp_path = os.path.join(a.run, "system_prompts.json")
    sp = {"texts": {}, "by_config": {}}
    if os.path.exists(sp_path):
        old = json.load(open(sp_path, encoding="utf-8"))
        if isinstance(old, dict) and "texts" in old and "by_config" in old:
            sp = old
    prompts.update({"gene_store_path": rel(a.genes), "gene_store_file_sha256": genes_sha, "cond_dir": rel(a.cond_dir),
                    "template_sha256": tmpl_sha, "tolerance": a.tolerance})
    by_config = prompts.setdefault("by_config", {})
    feats, lex_info = _features_by_case(a, cases)
    if prompts.get("lexicon", lex_info) != lex_info:
        sys.exit("[requests] this run directory was set up with another activation lexicon; use a new run directory")
    prompts["lexicon"] = lex_info
    # E11: C1 is token-matched from the dev matching report (c1match); a C1 that cannot be matched is an error, and
    # every configuration is built before any file is written
    c1m = C1M.requests_setup(a, reg, cfgs, store, (lex_info or {}).get("sha256"))
    if not C1M.same_run_matching(prompts.get("c1_matching"), c1m.run_info()):
        sys.exit("[requests] this run directory was set up with another C1 matching; use a new run directory")
    built = []
    for c in cfgs:
        try:
            reqs = C.build_requests(cases, c, store, run_id, features_by_case=feats, registry_ids=CF.all_ids(reg),
                                    cond_dir=a.cond_dir, tolerance=a.tolerance, **c1m.kwargs(c))
            summ = C.summarize_requests(reqs)
            c1m.record(c, reqs, summ)
        except C.C1MatchError as e:
            sys.exit(f"[requests] {c['id']}: {e}")
        built.append((c, reqs, summ))
    for c, reqs, summ in built:
        path = os.path.join(a.run, f"requests.{c['id']}.jsonl")
        C.write_jsonl(path, reqs)
        by_config[c["id"]] = summ
        for r in reqs:
            sp["texts"][r["meta"]["system_prompt_sha256"]] = r["messages"][0]["content"]
        sp["by_config"][c["id"]] = summ["system_prompt_sha256"]
        print(f"[requests] {c['id']}: {len(reqs)} requests, {summ['n_distinct_system_prompts']} distinct system prompt(s) -> {rel(path)}")
    if c1m.run_info():
        prompts["c1_matching"] = C1M.merge_run_matching(prompts.get("c1_matching"), c1m.run_info())
    configs_used = dict(cfg.get("configs", {}))
    configs_used.update({c["id"]: c for c in cfgs})
    cfg.update({"run_id": run_id, "cases_path": rel(a.cases), "split_dir": rel(a.split_dir), "split": a.split,
                "n_cases": len(cases), "conditions": sorted(set(cfg.get("conditions", []) + list(a.cond))),
                "config_registry": reg_info, "configs": configs_used, "prompts": prompts,
                "python_env": py_env, "created_at": P.now_iso()})
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    with open(sp_path, "w", encoding="utf-8") as f:
        json.dump(sp, f, indent=2, ensure_ascii=False)


def batch_validate_kwargs(c, reg, store):
    """validate_round keyword arguments for configuration `c` on the batch path (the unit executor reads the same
    registry fields, E06).

    The batch path activates the genes of one scope without problem features. The gene scope, repair kind, closing and
    activation mode come from the registry, so configurations whose scope has another name (C2E -> C3E, C3L-ALL -> C3L)
    run here as well. Observe-only configurations (C0, C1, C2) run every gene of their scope and record the result
    without repairing; for an answer that was not asked for a spec (C0, C1) the spec genes are recorded as not
    applicable. Under per_problem activation, genes whose rule depends on the problem need the unit executor."""
    if c["validator"] not in ("gene", "observe"):
        return {}
    if c["activation"] == "per_problem":
        ruled = C.problem_rule_genes(store, c["gene_scope"])
        if ruled:
            sys.exit(f"[validate] genes of scope {c['gene_scope']} carry per-problem activation rules ({ruled}); the "
                     f"batch path cannot evaluate them, so run {c['id']} through the unit executor (unit_exec.py)")
    if c["validator"] == "gene":
        return {"gene_scope": c["gene_scope"], "repair": c["repair"], "closing": c["closing"],
                "activation": c["activation"]}
    active = P.activate_scope(store, c["gene_scope"], c["activation"])
    return {"gene_scope": c["gene_scope"], "activation": c["activation"],
            "inapplicable": CF.inapplicable_genes(c, reg, active)}


def cmd_validate(a):
    reg = CF.load_registry(a.configs)
    c = _registry_configs(reg, [a.cond], "validate")[0]
    if c.get("pipeline", "standard") != "standard":
        sys.exit(f"[validate] {c['id']} uses pipeline {c['pipeline']!r}; it runs through its own module and the unit "
                 "executor (E06), not through this batch path")
    kw = batch_validate_kwargs(c, reg, G.load_store(a.genes))
    cases = {x["case_id"]: x for x in D.load_cases(a.cases)}
    gen_dir = a.gen or os.path.join(a.run, f"gen.{a.cond}.r0" if a.round == 0 else f"gen.{a.cond}.repair{a.round}")
    act = c["repair"] != "none" and not a.no_repair
    max_rounds = c["max_rounds"] if a.max_rounds is None else a.max_rounds
    python = a.python or E.orgene_python()
    E.require_env(python)
    if a.timeout is None:  # E22: the registry holds the execution timeout (E19 block `execution`)
        from .reexec import execution_timeouts
        a.timeout = execution_timeouts()["timeout_s"]
    res = P.validate_round(a.run, a.cond, a.round, gen_dir, cases, a.genes, timeout=a.timeout, act=act,
                           max_rounds=max_rounds, python=python, **kw)
    print(json.dumps(res, indent=2))


def cmd_configs(a):
    try:
        reg = CF.load_registry(a.configs)
        if a.genes:
            CF.check_registry_against_store(reg, G.load_store(a.genes))
    except CF.RegistryError as e:
        print(f"[configs] INVALID\n{e}", file=sys.stderr)
        sys.exit(1)
    cols = ("id", "prompt", "round0", "validator", "gene_scope", "activation", "repair", "closing", "max_rounds",
            "num_predict", "num_ctx", "variant", "pipeline", "token_cap")
    print(f"registry {reg['path']} sha256 {reg['sha256']}")
    print("| " + " | ".join(cols) + " |")
    print("|" + "---|" * len(cols))
    for c in reg["configs"].values():
        print("| " + " | ".join("-" if c[k] is None else str(c[k]) for k in cols) + " |")
    for x in reg["adapters"].values():
        print(f"adapter {x['id']}: {x['adapter']} ({x['workpackage'] or '-'}) {x['label']}")


def cmd_score(a):
    from . import refs as R
    try:
        cases = {c["case_id"]: c for c in R.load_scoring_cases(a.cases, overrides=a.overrides, freeze_manifest=a.freeze_manifest,
                                                                expected_sha256=a.overrides_sha256)}
    except R.OverrideError as exc:
        sys.exit(f"[score] refused: {exc}")
    for fi in {json.dumps(c["reference"]["overrides_file"], sort_keys=True) for c in cases.values()}:
        fi = json.loads(fi)
        print(f"[score] reference overrides: {fi['path'] or 'none'} (mode {fi['mode']}, "
              f"sha256 {(fi['sha256'] or '-')[:16]}, check {fi['integrity_check'] or 'none'})", file=sys.stderr)
    for cond in a.cond:
        m = P.score_condition(a.run, cond, cases, rel_tol=a.rel_tol, abs_tol=a.abs_tol)
        print(f"[score] {cond}: n={m['n']} exec_rate={m['exec_rate']} accuracy={m['accuracy']} ({m['n_correct']}/{m['n']})")


def cmd_report(a):
    print(P.report(a.run))


def cmd_env(a):
    res = E.check_env(a.python)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res.get("ok") else 1)


def cmd_selftest(a):
    from .selftest import run_selftest
    ok = run_selftest(ROOT, a.genes, a.cond_dir, keep=a.keep)
    sys.exit(0 if ok else 1)


def _gate_inputs(a):
    """Files that decide what a stage sends to the model or scores against. When the stage is gated they must be
    frozen files (freeze.unfrozen_inputs): the cases; for requests and validate the gene library and the configuration
    registry; for requests also the activation lexicon, the prompt templates (per-problem activation sets are
    recorded per request, so they are only as frozen as these inputs) and, when a C1 is token-matched, the C1 matching
    report (E11)."""
    paths = [a.cases]
    if a.cmd in ("requests", "validate"):
        paths += [a.genes, a.configs]
    if a.cmd == "requests":
        if a.lexicon:
            paths.append(a.lexicon)
        elif importlib.util.find_spec(f"{__package__}.features") is not None:
            from . import features as F
            paths.append(F.DEFAULT_LEXICON)
        paths += C.template_input_paths(a.cond_dir)
        if getattr(a, "c1_match_mode", None) == "tokens" and _asks_for_c1(a):
            paths.append(a.c1_report or C1M.DEFAULT_REPORT)
    return paths


def _asks_for_c1(a):
    """Whether `requests` builds a C1 prompt (a bad registry or id is reported by the command itself)."""
    try:
        reg = CF.load_registry(a.configs)
        return any((CF.get_config(reg, c) or {}).get("prompt") == "C1" for c in a.cond)
    except Exception:  # noqa: BLE001
        return False


def _freeze_gate(a):
    """E21 test gate: `requests` (plan), `validate` (execute) and `score` refuse to touch sealed cases (split test or
    eng_holdout, or any id in data/splits*/**/test_ids.json) unless FREEZE_MANIFEST.json is complete, verifies and
    carries the OSF registration id; each pass is appended to <run>/freeze_gate.jsonl."""
    if a.cmd not in ("requests", "validate", "score"):
        return
    from . import freeze as FZ
    ids = [c["case_id"] for c in _load_cases_for(a)] if a.cmd == "requests" else None
    extra = [a.gen] if getattr(a, "gen", None) else ()
    try:
        rec = FZ.gate_stage(a.cmd, run_dir=a.run, case_ids=ids, split=getattr(a, "split", None),
                            split_dir=getattr(a, "split_dir", None), extra_dirs=extra, inputs=_gate_inputs(a))
    except FZ.GateRefused as e:
        sys.exit(f"[{a.cmd}] refused by the test gate: {e}")
    # a gated score checks the reference-override file against the same manifest (the E13 option, when present)
    if rec and a.cmd == "score" and getattr(a, "freeze_manifest", False) is None:
        a.freeze_manifest = os.path.join(ROOT, rec["manifest"])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="orgene", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("cases", help="raw benchmark file -> canonical cases jsonl")
    p.add_argument("--source", required=True, help="mamo_complex_lp | mamo_easy_lp | industryor | nl4opt | smoke")
    p.add_argument("--raw", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_cases)

    p = sub.add_parser("split", help="freeze dev/test ids")
    p.add_argument("--cases", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--n-dev", type=int, required=True)
    p.add_argument("--seed", type=int, default=20260905)
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_split)

    p = sub.add_parser("contract", help="print the compiled C3 contract")
    p.add_argument("--genes", default=DEFAULT_GENES)
    p.set_defaults(fn=cmd_contract)

    p = sub.add_parser("requests", help="build round-0 runner request files for registered configurations")
    p.add_argument("--run", required=True, help="experiments/<run-id>")
    p.add_argument("--cases", required=True)
    p.add_argument("--split-dir", default=None)
    p.add_argument("--split", choices=["dev", "test", "eng_holdout"], default=None,
                   help="eng_holdout: the engineering-source cases (E22, data/splits/eng); sealed like test")
    p.add_argument("--cond", nargs="+", default=["C0", "C1", "C2", "C3"], help="configuration ids from the registry")
    p.add_argument("--configs", default=CF.DEFAULT_REGISTRY, help="configuration registry (default configs/r1_configs.json)")
    p.add_argument("--genes", default=DEFAULT_GENES)
    p.add_argument("--lexicon", default=None, help="activation lexicon for problem features (default: the features module's)")
    p.add_argument("--cond-dir", default=DEFAULT_COND_DIR)
    p.add_argument("--tolerance", type=float, default=0.05)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--python", default=None, help=f"interpreter for generated programs (default ${E.ENV_VAR} or {E.DEFAULT_PYTHON})")
    C1M.add_requests_options(p)  # E11: --c1-match-mode, --c1-report, --c1-tokenizer, --local-tokens, --tools-root
    p.set_defaults(fn=cmd_requests)

    p = sub.add_parser("validate", help="extract, check, execute; write repair requests for repairing configurations")
    p.add_argument("--run", required=True)
    p.add_argument("--cases", required=True)
    p.add_argument("--cond", required=True, help="configuration id from the registry")
    p.add_argument("--configs", default=CF.DEFAULT_REGISTRY, help="configuration registry (default configs/r1_configs.json)")
    p.add_argument("--round", type=int, default=0)
    p.add_argument("--gen", default=None, help="runner output dir (default gen.<cond>.r0 / gen.<cond>.repair<n>)")
    p.add_argument("--genes", default=DEFAULT_GENES)
    p.add_argument("--timeout", type=int, default=None,
                   help="execution timeout in seconds (default: execution.timeout_s of configs/model_registry.json, 60)")
    p.add_argument("--max-rounds", type=int, default=None, help="default: the configuration's max_rounds")
    p.add_argument("--no-repair", action="store_true", help="ablation: validate but never request repair")
    p.add_argument("--python", default=None, help=f"interpreter for generated programs (default ${E.ENV_VAR} or {E.DEFAULT_PYTHON}; never PATH)")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("score", help="score final artifacts against references")
    p.add_argument("--run", required=True)
    p.add_argument("--cases", required=True)
    p.add_argument("--cond", nargs="+", required=True)
    p.add_argument("--rel-tol", type=float, default=1e-4)
    p.add_argument("--abs-tol", type=float, default=1e-4)
    p.add_argument("--overrides", default="auto",
                   help="reference overrides: auto (data/reference_overrides/<source>.json if present) | none | PATH")
    p.add_argument("--freeze-manifest", default=None,
                   help="refuse to score unless the override file in use matches its sha256 in this manifest")
    p.add_argument("--overrides-sha256", default=None, help="refuse to score unless the override file has this sha256")
    p.set_defaults(fn=cmd_score)

    p = sub.add_parser("report", help="markdown summary across conditions")
    p.add_argument("--run", required=True)
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("env", help="check the interpreter for generated programs (pulp + CBC solve a test LP)")
    p.add_argument("--python", default=None)
    p.set_defaults(fn=cmd_env)

    p = sub.add_parser("selftest", help="end-to-end check without a model (canned outputs)")
    p.add_argument("--genes", default=DEFAULT_GENES)
    p.add_argument("--cond-dir", default=DEFAULT_COND_DIR)
    p.add_argument("--keep", action="store_true")
    p.set_defaults(fn=cmd_selftest)

    p = sub.add_parser("configs", help="validate and list the configuration registry")
    p.add_argument("--configs", default=CF.DEFAULT_REGISTRY)
    p.add_argument("--genes", default=DEFAULT_GENES, help="also check gene scopes against this library ('' to skip)")
    p.set_defaults(fn=cmd_configs)

    C1M.add_c1_match_parser(sub)  # E11: c1-match (dev cases only) writes c1_matching_report.json

    from . import schedule
    schedule.add_cli_parsers(sub)  # E07 uses E06's own execution gate and preflight.

    a = ap.parse_args(argv)
    _freeze_gate(a)
    a.fn(a)


if __name__ == "__main__":
    main()
