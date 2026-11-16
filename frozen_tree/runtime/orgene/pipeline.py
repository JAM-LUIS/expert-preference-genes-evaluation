"""validate / score / report stages over runner output directories."""
import glob
import json
import os
from datetime import datetime, timezone

from . import genes as G
from .conditions import read_jsonl, write_jsonl
from .execute import run_program
from .extract import extract
from .misreport import misreport_row, summarize_misreport  # E12
from .score import is_correct, summarize


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def read_gen_outputs(gen_dir):
    """Runner output records (ollama_runner / api_runner share the format)."""
    recs = []
    for p in sorted(glob.glob(os.path.join(gen_dir, "outputs", "*.json"))):
        with open(p, "r", encoding="utf-8") as f:
            recs.append(json.load(f))
    return recs


def _unit_key(rec):
    """(case_id, original repeat index)."""
    meta = rec.get("meta") or {}
    k = meta.get("orig_repeat", rec.get("repeat", 0))
    return rec["case_id"], int(k)


NOT_APPLICABLE = "not_applicable_no_spec"  # detail of a spec check on an answer that was never asked for a spec
NO_PROGRAM_ISSUE = {"geneId": "orgene.execution.runs", "version": "1.0.0", "predicateId": "predicate.executes.v1",
                    "severity": "hard", "phase": "post_exec", "ok": False, "detail": "no program to execute"}


def _checks(active, ctx, phase, inapplicable):
    """G.validate for one phase; genes in `inapplicable` are recorded with ok None and NOT_APPLICABLE, never run."""
    if not inapplicable:
        return G.validate(active, ctx, phase)
    out = []
    for g in active:
        v = g["validation"]
        if v.get("phase", "pre_exec") != phase:
            continue
        if g["geneId"] in inapplicable:
            out.append({"geneId": g["geneId"], "version": g["version"], "predicateId": v.get("predicateId"),
                        "severity": v.get("severity", "hard"), "phase": phase, "ok": None, "detail": NOT_APPLICABLE})
        else:
            out.extend(G.validate([g], ctx, phase))
    return out


def validate_one(case, rec, active, rnd, applications, *, cond, repeat, act=True, max_rounds=2, repair=None,
                 closing=None, timeout=60, python=None, inapplicable=(), budget_ok=True, checklist=None,
                 force_review=False):
    """Check and execute one answer; decide on repair. Shared by the batch path (validate_round) and the unit
    executor (unit_exec.py), so both write the same validated record for the same answer.

    rec:           the generation record, runner output or backend call record (content, ok, done_reason, eval_count,
                   prompt_eval_count, local_tokens, total_duration_ns, seconds, request_id)
    active:        the genes this configuration validates with (activated by the caller)
    applications:  {geneId: repairs already applied in this unit}; not modified
    act:           the configuration repairs (registry repair != none); False = observe only
    inapplicable:  geneIds recorded as not applicable (spec checks on an answer that was not asked for a spec)
    budget_ok:     False when the unit's token cap is spent: no repair is requested (unit executor only)
    checklist:     the review checklist text of the checklist repair mode (repair "gene_generic")
    force_review:  round 0 only: also send the checklist when no hard check failed (C3A)
    Returns (v, repair_text, applied): the validated record (v5 layout), the repair user message or None, and the
    geneIds that message applies. Repair is requested only when act, hard failures remain, rnd < max_rounds and
    budget_ok, and some failing gene has applications left. The exec dict of run_program goes into v unchanged."""
    content = rec.get("content") or ""
    ex = extract(content)
    ctx = {"case": case, "spec": ex["spec"], "code": ex["code"], "exec": None}
    pre = _checks(active, ctx, "pre_exec", inapplicable)
    exec_res = run_program(ex["code"], timeout=timeout, python=python) if ex["code"] else None
    ctx["exec"] = exec_res
    post = _checks(active, ctx, "post_exec", inapplicable) if exec_res else [dict(NO_PROGRAM_ISSUE)]
    issues = pre + post
    hard = G.hard_failures(issues)
    decision = "accepted"
    repair_text, applied = (None, [])
    forced = bool(force_review) and rnd == 0 and not hard
    if act and (hard or forced) and rnd < max_rounds and budget_ok:
        kw = {"checklist": checklist, "force": forced} if repair == "gene_generic" else {}
        repair_text, applied = G.repair_turn(active, issues, applications, exec_result=exec_res, condition=cond,
                                             repair=repair, closing=closing, **kw)
        if repair_text:
            decision = "repair_requested"
    v = {
        "case_id": case["case_id"], "repeat": repeat, "condition": cond, "round": rnd,
        "request_id": rec.get("request_id"),
        "gen_ok": bool(rec.get("ok")), "done_reason": rec.get("done_reason"),
        "out_tokens": rec.get("eval_count"), "in_tokens": rec.get("prompt_eval_count"),
        "local_tokens": rec.get("local_tokens"),  # runner's local tokenizer counts (E09); in_tokens stays as reported
        "gen_seconds": (rec.get("total_duration_ns") or 0) / 1e9 if rec.get("total_duration_ns") else rec.get("seconds"),
        "has_spec": ex["spec"] is not None, "has_code": ex["code"] is not None,
        "spec": ex["spec"], "code": ex["code"],
        "exec": exec_res, "exec_timeout_s": timeout, "issues": issues,
        "hard_failed_genes": [i["geneId"] for i in hard],
        "soft_failed_genes": [i["geneId"] for i in G.soft_failures(issues)],
        "decision": decision, "repair_applied_genes": applied,
        "repair_applications": dict(applications), "max_rounds": max_rounds if act else 0, "validated_at": now_iso(),
    }
    return v, repair_text, applied


def final_entry(v, prev=None):
    """The final.<cond>.jsonl row after validating round v["round"] of a unit: v plus the per-round summaries.
    Re-validating round r (a resumed run) replaces that round and drops later ones instead of appending again."""
    rnd = v["round"]
    entry = dict(v)
    earlier = [r for r in (prev.get("rounds", []) if prev else []) if r.get("round", -1) < rnd]
    entry["rounds"] = earlier + [{
        "round": rnd, "request_id": v["request_id"], "out_tokens": v["out_tokens"], "in_tokens": v["in_tokens"],
        "hard_failed_genes": v["hard_failed_genes"], "soft_failed_genes": v["soft_failed_genes"],
        "exec_ok": bool((v.get("exec") or {}).get("exec_ok")), "decision": v["decision"],
        "repair_applied_genes": v["repair_applied_genes"]}]
    entry["provisional"] = v["decision"] == "repair_requested"
    return entry


def activate_scope(store, scope, activation=None):
    """The genes a batch validation uses: the active genes of `scope`. The batch path has no problem features, so
    under per_problem (the default) a gene with a per-problem rule makes genes.activate raise; such configurations run
    through the unit executor. activation "all" (observe-only C0/C1/C2, C3L-ALL) ignores the rules."""
    if activation in (None, "per_problem"):
        return G.activate(store, condition=scope)[0]
    return G.activate(store, condition=scope, mode=activation)[0]


def validate_round(run_dir, cond, rnd, gen_dir, cases_by_id, genes_path, timeout=60, act=True,
                   max_rounds=2, python=None, gene_scope=None, repair=None, closing=None, activation=None,
                   inapplicable=()):
    """Validate one generation directory. act=True (repairing configurations) writes repair requests for hard failures.

    Round `rnd` of a unit asks for another repair only while rnd < max_rounds; every repairing configuration is run with
    max_rounds = genes.MAX_REPAIR_ROUNDS and the lower ladder points are cut from that run (ladder.py).
    gene_scope / repair / closing default to genes.REPAIR_PROFILES[cond]; a configuration registry passes its own
    (for observe-only configurations also activation "all" and the spec genes that do not apply, E06).
    The per-answer work is validate_one(), shared with the unit executor (unit_exec.py)."""
    store = G.load_store(genes_path)
    active = activate_scope(store, gene_scope or G.gene_scope(cond), activation)
    recs = read_gen_outputs(gen_dir)
    if not recs:
        raise SystemExit(f"no outputs in {gen_dir}")
    req_path = os.path.join(run_dir, f"requests.{cond}.jsonl" if rnd == 0 else f"requests.{cond}.repair{rnd}.jsonl")
    requests_by_id = {r["request_id"]: r for r in read_jsonl(req_path)} if os.path.exists(req_path) else {}
    validated, repair_reqs = [], []
    for rec in recs:
        case_id, k = _unit_key(rec)
        case = cases_by_id.get(case_id)
        if case is None:
            continue
        meta = rec.get("meta") or {}
        applications = dict(meta.get("repair_applications") or {})
        content = rec.get("content") or ""
        v, repair_text, applied = validate_one(case, rec, active, rnd, applications, cond=cond, repeat=k, act=act,
                                               max_rounds=max_rounds, repair=repair, closing=closing,
                                               timeout=timeout, python=python, inapplicable=inapplicable)
        decision = v["decision"]
        validated.append(v)
        if decision == "repair_requested":
            base_req = requests_by_id.get(rec.get("request_id"))
            if base_req is None:
                raise SystemExit(f"request {rec.get('request_id')} not found in {req_path}; cannot build repair turn")
            new_apps = dict(applications)
            for gid in applied:
                new_apps[gid] = new_apps.get(gid, 0) + 1
            msgs = list(base_req["messages"]) + [{"role": "assistant", "content": content}, {"role": "user", "content": repair_text}]
            repair_reqs.append({
                "request_id": f"{case_id}.{cond}.rep{k}.repair{rnd + 1}", "case_id": case_id, "condition": cond,
                "messages": msgs,
                "meta": dict(meta, round=rnd + 1, orig_repeat=k, repair_applications=new_apps,
                             parent_request_id=rec.get("request_id"), repaired_genes=applied),
            })
    write_jsonl(os.path.join(run_dir, f"validated.{cond}.round{rnd}.jsonl"), validated)
    if repair_reqs:
        write_jsonl(os.path.join(run_dir, f"requests.{cond}.repair{rnd + 1}.jsonl"), repair_reqs)
    # update final.<cond>.jsonl: accepted units replace earlier entries; repair-requested units keep the earlier entry as fallback
    final_path = os.path.join(run_dir, f"final.{cond}.jsonl")
    final = {(r["case_id"], r["repeat"]): r for r in read_jsonl(final_path)} if os.path.exists(final_path) else {}
    for v in validated:
        key = (v["case_id"], v["repeat"])
        final[key] = final_entry(v, final.get(key))
    write_jsonl(final_path, [final[k] for k in sorted(final)])
    n_rep = len(repair_reqs)
    return {"n_validated": len(validated), "n_hard_failed": sum(1 for v in validated if v["hard_failed_genes"]),
            "n_repair_requested": n_rep, "repair_requests_path": os.path.join(run_dir, f"requests.{cond}.repair{rnd + 1}.jsonl") if n_rep else None}


def score_condition(run_dir, cond, cases_by_id, rel_tol=1e-4, abs_tol=1e-4):
    final = read_jsonl(os.path.join(run_dir, f"final.{cond}.jsonl"))
    rows = []
    for v in final:
        case = cases_by_id[v["case_id"]]
        ex = v.get("exec") or {}
        ref = case["reference"]
        correct, reason = is_correct(ex.get("objective"), ref.get("objective"), ref.get("status"), rel_tol, abs_tol, status=ex.get("status"),
                                     reference_interval=ref.get("interval"))  # E22: time-limited references
        rounds = v.get("rounds", [])
        rows.append({
            "case_id": v["case_id"], "repeat": v["repeat"], "condition": cond, "source": case.get("source"),
            "exec_ok": bool(ex.get("exec_ok")), "protocol_ok": bool(ex.get("protocol_ok")), "status": ex.get("status"),
            "objective": ex.get("objective"), "reference_objective": ref.get("objective"), "reference_status": ref.get("status"),
            "correct": correct, "reason": reason, "provisional": v.get("provisional", False),
            "out_tokens": sum((r.get("out_tokens") or 0) for r in rounds) or v.get("out_tokens"),
            "in_tokens": sum((r.get("in_tokens") or 0) for r in rounds) or v.get("in_tokens"),
            "n_calls": len(rounds) or 1, "repair_rounds_used": max(0, len(rounds) - 1),
            "hard_issue_count_round0": len(rounds[0]["hard_failed_genes"]) if rounds else len(v.get("hard_failed_genes") or []),
            "hard_failed_genes_final": v.get("hard_failed_genes") or [],
            "soft_failed_genes_final": v.get("soft_failed_genes") or [],
            "exec_seconds": ex.get("seconds"),
        })
        rows[-1].update(misreport_row(ex, correct))  # E12: misreport flags + verified_correct (main score unchanged)
    rows.sort(key=lambda r: (r["case_id"], r["repeat"]))
    # E13: three tolerance tiers; effective (overridden) vs original reference; `correct` stays the primary tier
    from .refs import reference_fields, reference_summary
    for r in rows:
        r.update(reference_fields(r, cases_by_id[r["case_id"]]["reference"], rel_tol, abs_tol))
    write_jsonl(os.path.join(run_dir, f"results.{cond}.jsonl"), rows)
    metrics = summarize(rows)
    by_source = {}
    for r in rows:
        by_source.setdefault(r["source"], []).append(r)
    metrics["by_source"] = {s: summarize(v) for s, v in by_source.items()}
    metrics.update(reference_summary(rows, cases_by_id))
    for s, v in by_source.items():
        metrics["by_source"][s].update(reference_summary(v))
    metrics["misreport"] = summarize_misreport(rows)  # E12
    for s, v in by_source.items():
        metrics["by_source"][s]["misreport"] = summarize_misreport(v)
    gene_stats = {}
    for v in final:
        for rd in v.get("rounds", []):
            for gid in rd["hard_failed_genes"]:
                d = gene_stats.setdefault(gid, {"round0_fail": 0, "final_fail": 0})
                if rd["round"] == 0:
                    d["round0_fail"] += 1
        for gid in v.get("hard_failed_genes") or []:
            gene_stats.setdefault(gid, {"round0_fail": 0, "final_fail": 0})["final_fail"] += 1
    metrics["gene_hard_failures"] = gene_stats
    metrics["condition"] = cond
    metrics["scored_at"] = now_iso()
    metrics["tolerance"] = {"rel": rel_tol, "abs": abs_tol}
    with open(os.path.join(run_dir, f"metrics.{cond}.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    return metrics


def report(run_dir):
    mets = {}
    for p in sorted(glob.glob(os.path.join(run_dir, "metrics.*.json"))):
        m = json.load(open(p, "r", encoding="utf-8"))
        mets[m.get("condition", os.path.basename(p))] = m
    lines = [f"# Run report: {os.path.basename(os.path.abspath(run_dir))}", "",
             "| condition | n | exec rate | accuracy | correct | mean out tokens | mean calls | repaired |",
             "|---|---|---|---|---|---|---|---|"]
    for c, m in mets.items():
        lines.append(f"| {c} | {m.get('n')} | {m.get('exec_rate')} | {m.get('accuracy')} | {m.get('n_correct')} | {m.get('mean_out_tokens')} | {m.get('mean_calls')} | {m.get('repaired_cases')} |")
    lines.append("")
    for c, m in mets.items():
        if m.get("gene_hard_failures"):
            lines.append(f"## {c}: hard gene failures (round0 -> final)")
            for gid, d in sorted(m["gene_hard_failures"].items()):
                lines.append(f"- {gid}: {d['round0_fail']} -> {d['final_fail']}")
            lines.append("")
    text = "\n".join(lines) + "\n"
    with open(os.path.join(run_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(text)
    return text
