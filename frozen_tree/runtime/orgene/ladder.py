"""Repair ladder and repair-conflict accounting, cut from one finished run (E05). No model calls, no re-execution.

Every repairing configuration (C3, C3L, C3E, C2E) is run with at most genes.MAX_REPAIR_ROUNDS = 2 repair rounds
(D8). The ladder points "at most k repair rounds" (k = 0, 1) are cut from that same run:

- a unit that stopped at round m <= k keeps its record;
- a unit that went past round k takes its validated record of round k. That is the record a run with --max-rounds k
  writes: the round-k request is the same in both runs (round 0 is shared; each repair request is built only from the
  previous answer, the checks and the applications so far), so at temperature 0 the answer is the same too. The one
  difference is that a run capped at k does not ask for another repair: decision -> "accepted", no genes applied.

The cut is written in the v5 `final.<cond>.jsonl` format, so pipeline.score_condition scores it unchanged.

Conflict accounting (todo A1-15) reads the per-round hard and soft failure sets that every final record carries:
- a conflict event is a repair step (round r -> r + 1) in which gene g stops failing while gene h starts failing;
- a unit has not converged when hard failures remain after its last round (rounds exhausted, or no failing gene has
  repair applications left).
"""
import glob
import hashlib
import json
import os
import re

from .conditions import read_jsonl, write_jsonl

LADDER_SCHEMA = "orgene.r1.ladder.v1"
CONFLICT_SCHEMA = "orgene.r1.repair_conflicts.v1"

_ROUND_FILE_RE = re.compile(r"validated\.(?P<cond>.+)\.round(?P<r>\d+)\.jsonl$")


def _key(rec):
    return rec["case_id"], int(rec["repeat"])


def _sha_rows(rows):
    h = hashlib.sha256()
    for r in rows:
        h.update((json.dumps(r, ensure_ascii=False) + "\n").encode("utf-8"))
    return h.hexdigest()


def read_final(run_dir, cond):
    path = os.path.join(run_dir, f"final.{cond}.jsonl")
    if not os.path.exists(path):
        raise FileNotFoundError(f"no final.{cond}.jsonl in {run_dir}")
    return read_jsonl(path)


def read_validated(run_dir, cond):
    """{round: {(case_id, repeat): validated record}} from validated.<cond>.round<r>.jsonl."""
    out = {}
    for p in glob.glob(os.path.join(run_dir, f"validated.{cond}.round*.jsonl")):
        m = _ROUND_FILE_RE.search(os.path.basename(p))
        if not m or m.group("cond") != cond:
            continue
        out[int(m.group("r"))] = {_key(v): v for v in read_jsonl(p)}
    return out


def source_max_rounds(final_rows):
    """The repair-round cap the run was validated with (recorded per record since E05); None for older records."""
    caps = {r.get("max_rounds") for r in final_rows if r.get("max_rounds") is not None}
    if len(caps) > 1:
        raise ValueError(f"records of one run carry different max_rounds: {sorted(caps)}")
    return caps.pop() if caps else None


def cut_entry(entry, validated, k):
    """The final record of one unit under "at most k repair rounds", from its record in a run with a higher cap."""
    rounds = entry.get("rounds") or []
    last = len(rounds) - 1
    if last <= k and not (last == k and entry.get("decision") == "repair_requested"):
        out = dict(entry)
        if out.get("max_rounds") is not None:
            out["max_rounds"] = k
        return out, False
    rec = (validated.get(k) or {}).get(_key(entry))
    if rec is None:
        raise ValueError(f"{entry['case_id']} r{entry['repeat']}: no validated record for round {k}")
    out = dict(rec)
    out["decision"] = "accepted"
    out["repair_applied_genes"] = []
    if out.get("max_rounds") is not None:
        out["max_rounds"] = k
    cut = [dict(r) for r in rounds[: k + 1]]
    cut[-1]["decision"] = "accepted"
    if "repair_applied_genes" in cut[-1]:
        cut[-1]["repair_applied_genes"] = []
    out["rounds"] = cut
    out["provisional"] = False
    return out, True


def derive_final(final_rows, validated, k):
    """Final records for "at most k repair rounds" (k >= 0), in the order of `final_rows`. Returns (rows, n_cut)."""
    if k < 0:
        raise ValueError("k must be >= 0")
    cap = source_max_rounds(final_rows)
    if cap is not None and k > cap:
        raise ValueError(f"cannot cut {k} repair rounds from a run capped at {cap}")
    rows, n_cut = [], 0
    for e in final_rows:
        row, was_cut = cut_entry(e, validated, k)
        rows.append(row)
        n_cut += was_cut
    return rows, n_cut


def derive_run(run_dir, cond, k, out_dir):
    """Write final.<cond>.jsonl for "at most k repair rounds" into out_dir, with a manifest ladder.<cond>.json."""
    if os.path.abspath(out_dir) == os.path.abspath(run_dir):
        raise ValueError("the ladder cut goes to its own directory; the source run is never rewritten")
    final_rows = read_final(run_dir, cond)
    rows, n_cut = derive_final(final_rows, read_validated(run_dir, cond), k)
    os.makedirs(out_dir, exist_ok=True)
    write_jsonl(os.path.join(out_dir, f"final.{cond}.jsonl"), rows)
    manifest = {
        "schema_version": LADDER_SCHEMA,
        "condition": cond,
        "max_repair_rounds": k,
        "source_run": os.path.basename(os.path.abspath(run_dir)),
        "source_max_rounds": source_max_rounds(final_rows),
        "source_final_sha256": _sha_rows(final_rows),
        "derived_final_sha256": _sha_rows(rows),
        "n_units": len(rows),
        "n_cut_at_k": n_cut,
        "n_provisional": sum(1 for r in rows if r.get("provisional")),
        "method": "cut from the source run's validated records; no model calls, no re-execution",
    }
    with open(os.path.join(out_dir, f"ladder.{cond}.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest


# ----------------------------------------------------------------------------- conflicts and convergence


def conflict_events(final_rows):
    """One event per (repair step, gene fixed, gene newly failing). A gene is fixed when it failed hard in round r and
    passes in round r + 1; it is newly failing when it passed in round r and fails (hard or soft) in round r + 1."""
    events = []
    for row in final_rows:
        rounds = row.get("rounds") or []
        for a, b in zip(rounds, rounds[1:]):
            hard_a, hard_b = set(a.get("hard_failed_genes") or []), set(b.get("hard_failed_genes") or [])
            soft_a, soft_b = set(a.get("soft_failed_genes") or []), set(b.get("soft_failed_genes") or [])
            fixed = sorted(hard_a - hard_b - soft_b)
            new = [(h, "hard") for h in sorted(hard_b - hard_a - soft_a)] + \
                  [(h, "soft") for h in sorted(soft_b - soft_a - hard_a)]
            targeted = set(a.get("repair_applied_genes") or [])
            for g in fixed:
                for h, sev in new:
                    events.append({"case_id": row["case_id"], "repeat": row["repeat"], "round": b.get("round"),
                                   "fixed": g, "fixed_was_targeted": g in targeted if "repair_applied_genes" in a else None,
                                   "new": h, "new_severity": sev})
    return events


def convergence(row, max_rounds=None):
    """clean_round0 | converged | incomplete | context_exceeded | rounds_exhausted | no_repair_left.
    context_exceeded: the unit executor stopped the unit because its next repair request did not fit the context
    window (the row carries the context_exceeded record, E06)."""
    rounds = row.get("rounds") or []
    if not rounds or not rounds[0].get("hard_failed_genes"):
        return "clean_round0"
    if not (row.get("hard_failed_genes") or []):
        return "converged"
    if row.get("provisional"):
        return "incomplete"
    if row.get("context_exceeded"):
        return "context_exceeded"
    cap = row.get("max_rounds", max_rounds)
    if cap is not None and len(rounds) - 1 >= cap:
        return "rounds_exhausted"
    return "no_repair_left"


def conflict_summary(final_rows, max_rounds=None):
    """Counts for the paper's conflict table: gene pairs (fixed -> newly failing) and units that did not converge."""
    events = conflict_events(final_rows)
    pairs = {}
    for e in events:
        k = f"{e['fixed']} -> {e['new']} ({e['new_severity']})"
        pairs[k] = pairs.get(k, 0) + 1
    status = {}
    nonconv = []
    for row in final_rows:
        s = convergence(row, max_rounds)
        status[s] = status.get(s, 0) + 1
        if s in ("rounds_exhausted", "no_repair_left", "incomplete", "context_exceeded"):
            nonconv.append({"case_id": row["case_id"], "repeat": row["repeat"], "status": s,
                            "hard_failed_genes_final": row.get("hard_failed_genes") or []})
    return {
        "schema_version": CONFLICT_SCHEMA,
        "n_units": len(final_rows),
        "n_conflict_events": len(events),
        "n_units_with_conflict": len({(e["case_id"], e["repeat"]) for e in events}),
        "conflict_pairs": dict(sorted(pairs.items())),
        "convergence": dict(sorted(status.items())),
        "n_not_converged": len(nonconv),
        "not_converged": nonconv,
        "events": events,
    }
