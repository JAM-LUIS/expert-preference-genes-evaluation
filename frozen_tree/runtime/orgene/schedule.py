"""E07: a sealed, seeded global order of (case, configuration, repeat, model) units.

Plans contain ids and scheduling decisions, never benchmark text or answers. Reverse means the
reverse of the *raw seeded shuffle*: C0 dependencies are then repaired and every move is retained.
Execution uses E06's preflight and run_unit, one context/run directory per registry entry.
"""
import argparse
import copy
import hashlib
import json
import math
import os
import random
import re
import time
import urllib.request
from collections import defaultdict

from .paths import rel
from pathlib import Path

SCHEMA = 1
UNIT_FIELDS = {"case_id", "config_id", "repeat", "registry_entry"}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ScheduleError(ValueError):
    """A matrix/plan or occupancy check is unsafe to execute."""


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unit_key(unit):
    return tuple(unit[k] for k in ("registry_entry", "case_id", "config_id", "repeat"))


def _units(matrix, registry=None):
    if not isinstance(matrix, dict) or set(matrix) != {"schema_version", "units"}:
        raise ScheduleError("matrix must contain only schema_version and units")
    if type(matrix["schema_version"]) is not int or matrix["schema_version"] != SCHEMA:
        raise ScheduleError("unsupported matrix schema_version")
    units = matrix["units"]
    if not isinstance(units, list) or not units:
        raise ScheduleError("matrix units must be a nonempty list")
    seen = set()
    for unit in units:
        if not isinstance(unit, dict) or set(unit) != UNIT_FIELDS:
            raise ScheduleError("every unit must contain case_id, config_id, repeat, registry_entry")
        for field in UNIT_FIELDS - {"repeat"}:
            if not isinstance(unit[field], str) or not SAFE_ID.fullmatch(unit[field]) or unit[field] in (".", ".."):
                raise ScheduleError(f"invalid {field}: ids must be safe path components")
        if type(unit["repeat"]) is not int or unit["repeat"] < 0:
            raise ScheduleError("repeat must be a nonnegative integer (not bool)")
        key = unit_key(unit)
        if key in seen:
            raise ScheduleError(f"duplicate unit: {key}")
        seen.add(key)
        if registry is not None and unit["config_id"] not in registry["configs"]:
            raise ScheduleError(f"unknown or adapter configuration {unit['config_id']}")
    return copy.deepcopy(units)


def _source(unit, registry):
    cfg = registry["configs"][unit["config_id"]]
    source = cfg["round0"]
    if source == "own":
        return None
    if not source.startswith("reuse:"):
        raise ScheduleError("invalid round0 dependency")
    source_id = source[6:]
    if source_id not in registry["configs"] or registry["configs"][source_id]["round0"] != "own":
        raise ScheduleError("round0 dependency must point to an own source (no chains)")
    return dict(unit, config_id=source_id)


def make_plan(matrix, config_registry, *, seed=20260930, order="random"):
    if type(seed) is not int or order not in ("random", "reverse"):
        raise ScheduleError("seed must be an integer; order must be random or reverse")
    base = _units(matrix, config_registry)
    keys = {unit_key(u) for u in base}
    for unit in base:
        source = _source(unit, config_registry)
        if source is not None and unit_key(source) not in keys:
            raise ScheduleError(f"missing source unit for {unit_key(unit)} (same case, repeat and model required)")
    raw = copy.deepcopy(base)
    random.Random(seed).shuffle(raw)
    if order == "reverse":
        raw.reverse()
    ordered, moves = copy.deepcopy(raw), []
    # Registry validation forbids chains: moving a consumer never moves a source.
    for unit in raw:
        source = _source(unit, config_registry)
        if source is None:
            continue
        i, j = ordered.index(unit), ordered.index(source)
        if i < j:
            ordered.pop(i)
            dest = ordered.index(source) + 1
            ordered.insert(dest, unit)
            moves.append({"unit": unit, "source": source, "from_index": i, "to_index": dest})
    return {"schema_version": SCHEMA, "seed": seed, "order": order,
            "order_rule": "seeded shuffle; raw reverse if requested; move consumers immediately after sources",
            "exact_reverse": order == "reverse" and not moves,
            "reverse_protocol_status": ("not_requested" if order != "reverse" else
                                        "blocked_dependency_adjustments" if moves else "awaiting_protocol_authorization"),
            "config_registry_sha256": config_registry.get("sha256"),
            "matrix_sha256": hashlib.sha256(_canonical(matrix)).hexdigest(),
            "matrix_units": base, "raw_units": raw, "units": ordered, "dependency_moves": moves}


def write_plan(path, plan):
    """Write once; refuse to overwrite a different plan. Return the actual on-disk byte SHA."""
    raw = (json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ScheduleError("plan already exists with different contents; use a new plan path") from None
    digest = hashlib.sha256(raw).hexdigest()
    receipt = Path(str(path) + ".sha256")
    if receipt.exists() and receipt.read_text().strip() != digest:
        raise ScheduleError("existing plan hash receipt differs")
    receipt.write_text(digest + "\n")
    return digest


def load_plan(path, expected_sha256, *, configs_path=None):
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ScheduleError("supply the recorded plan SHA-256 explicitly")
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ScheduleError("plan SHA-256 mismatch; refusing execution")
    try:
        plan = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ScheduleError("invalid plan JSON") from exc
    if not isinstance(plan, dict) or plan.get("schema_version") != SCHEMA:
        raise ScheduleError("unsupported plan schema")
    _units({"schema_version": SCHEMA, "units": plan.get("units")})
    if configs_path is not None:
        from . import configs as CF
        registry = CF.load_registry(configs_path)
        if registry["sha256"] != plan.get("config_registry_sha256"):
            raise ScheduleError("configuration registry SHA-256 differs from plan")
        replay = make_plan({"schema_version": SCHEMA, "units": plan.get("matrix_units")}, registry,
                           seed=plan.get("seed"), order=plan.get("order"))
        if replay != plan:
            raise ScheduleError("plan order or dependency metadata differs from deterministic replay")
    return plan


def _get_models(host):
    with urllib.request.urlopen(host.rstrip("/") + "/api/ps", timeout=30) as response:
        obj = json.load(response)
    if not isinstance(obj, dict) or not isinstance(obj.get("models"), list):
        raise ScheduleError("malformed Ollama /api/ps response")
    return obj["models"]


def wait_until_idle(host, model, log, *, get_models=None, sleep=time.sleep, max_wait=600,
                    interval=10, allowed_models=None):
    """Wait for foreign loaded model names. Never unload a model or hide a failed occupancy check.

    /api/ps identifies models, not projects; another project using the same model cannot be
    distinguished by this endpoint. External coordination/ownership remains necessary.
    """
    if not math.isfinite(interval) or not math.isfinite(max_wait) or interval <= 0 or max_wait < 0:
        raise ScheduleError("occupancy interval must be positive and max_wait nonnegative")
    allowed, waited = set(allowed_models or [model]), 0.0
    get_models = get_models or _get_models
    while True:
        try:
            models = get_models(host)
            if not isinstance(models, list):
                raise ScheduleError("malformed loaded models list")
            names = []
            for entry in models:
                name = (entry.get("name") or entry.get("model")) if isinstance(entry, dict) else None
                if not isinstance(name, str) or not name:
                    raise ScheduleError("malformed loaded model entry")
                names.append(name)
        except Exception as exc:
            log({"event": "occupancy_refused", "error_kind": type(exc).__name__})
            raise ScheduleError("cannot verify Ollama occupancy; no unit started") from exc
        foreign = sorted(set(names) - allowed)
        if not foreign:
            if waited:
                log({"event": "occupancy_clear", "waited_seconds": waited})
            return waited
        log({"event": "yield_to_foreign_models", "models": foreign, "waited_seconds": waited})
        if waited >= max_wait:
            raise ScheduleError("foreign model remains loaded; occupancy wait limit reached")
        duration = min(interval, max_wait - waited)
        sleep(duration)
        waited += duration


def add_cli_parsers(sub):
    from . import configs as CF
    from . import unit_exec as U
    p = sub.add_parser("plan", help="seal a global seeded E07 unit order (ids only; no model calls)")
    p.add_argument("--matrix", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--configs", default=CF.DEFAULT_REGISTRY)
    p.add_argument("--seed", type=int, default=20260930)
    p.add_argument("--order", choices=["random", "reverse"], default="random")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("execute", help="execute a sealed E07 plan through E06 safeguards")
    U.add_runner_options(p, require_selection=False)
    p.add_argument("--plan", required=True)
    p.add_argument("--plan-sha256", required=True, help="recorded byte SHA; never inferred from a rewritten plan")
    p.add_argument("--occupancy-max-wait", type=float, default=600)
    p.add_argument("--occupancy-interval", type=float, default=10)
    p.set_defaults(fn=cmd_execute)


def cmd_plan(a):
    from . import configs as CF
    try:
        matrix = json.loads(Path(a.matrix).read_bytes())
        plan = make_plan(matrix, CF.load_registry(a.configs), seed=a.seed, order=a.order)
        digest = write_plan(a.out, plan)
    except (ScheduleError, CF.RegistryError, OSError, ValueError) as exc:
        raise SystemExit(f"[plan] {exc}") from exc
    print(json.dumps({"plan": a.out, "sha256": digest, "units": len(plan["units"]),
                      "dependency_moves": len(plan["dependency_moves"]), "order": plan["order"]}, sort_keys=True))


# Files a fresh model context may hold before the scheduler's input receipt exists: the run lock, and the freeze gate's
# own record, which the gate appends on a sealed stage before the receipt is written (prepare_run runs the gate first).
_NOT_ARTIFACTS = {".lock", "freeze_gate.jsonl"}


def _context_has_artifacts(path):
    """Names only: do not open old unit/answer payloads before the freeze gate."""
    return path.exists() and any(p.is_file() and p.name not in _NOT_ARTIFACTS for p in path.rglob("*"))


def _check_unit_attribution(path, selected, plan, plan_sha256):
    """After the input gate, verify all saved units belong to this exact scheduling plan."""
    from . import unit_exec as U
    by_key = {unit_key(unit): index for index, unit in enumerate(plan["units"])}
    expected = {Path(U.unit_path(str(path), unit["case_id"], unit["config_id"], unit["repeat"])).name: unit
                for unit in selected}
    directory = path / "units"
    if not directory.exists():
        return
    for file in directory.glob("*.json"):
        if file.name == "setup.json":
            continue
        if file.name not in expected:
            raise ScheduleError("existing unit outside scheduled context; refusing to read its payload")
        unit = expected[file.name]
        try:
            rec = json.loads(file.read_bytes())
            meta = rec.get("schedule")
            valid = (isinstance(meta, dict) and meta.get("plan_sha256") == plan_sha256
                     and type(meta.get("planned_index")) is int
                     and meta["planned_index"] == by_key[unit_key(unit)]
                     and type(meta.get("seed")) is int and meta["seed"] == plan["seed"]
                     and meta.get("order") == plan["order"]
                     and rec.get("case_id") == unit["case_id"] and rec.get("config_id") == unit["config_id"]
                     and type(rec.get("repeat")) is int and rec["repeat"] == unit["repeat"]
                     and rec.get("status") in (U.COMPLETE, U.RUNNING, U.INCOMPLETE))
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise ScheduleError("scheduled unit attribution differs or is missing; existing evidence was preserved")


def _input_guard(root, plan, plan_sha256, groups):
    """Pin case identity/content after gating, before model preflight or run_config updates."""
    from . import unit_exec as U
    path = root / "schedule_inputs.json"
    if path.exists():
        try:
            state = json.loads(path.read_bytes())
            if not isinstance(state, dict) or state.get("schema_version") != SCHEMA or \
                    state.get("plan_sha256") != plan_sha256 or not isinstance(state.get("selected_case_sha256"), dict):
                raise ScheduleError("existing scheduler input receipt is invalid")
        except (ValueError, TypeError) as exc:
            raise ScheduleError("existing scheduler input receipt is invalid") from exc
    else:
        if any(_context_has_artifacts(root / "by-model" / model) for model in groups):
            raise ScheduleError("existing unattributed context has artifacts but no scheduler input receipt; "
                                "use a new run directory")
        state = {"schema_version": SCHEMA, "plan_sha256": plan_sha256, "selected_case_sha256": {}}

    def guard(args, cases, gate):
        del gate  # prepare_run calls this only after accepting the selected identities.
        resolved = str(Path(args.cases).resolve())  # the receipt holds the neutral form and a digest of the real path
        current = {"cases_path": rel(resolved), "cases_path_sha256": hashlib.sha256(resolved.encode()).hexdigest(),
                   "cases_sha256": _sha(args.cases)}
        if any(key in state and state[key] != value for key, value in current.items()):
            raise ScheduleError("cases input path or bytes changed; resume requires the original pinned input")
        digest = hashlib.sha256(_canonical(cases)).hexdigest()
        previous = state["selected_case_sha256"].get(args.registry_entry)
        if previous is None and _context_has_artifacts(Path(args.run)):
            raise ScheduleError("existing unattributed model context has no pinned selected-case input receipt; "
                                "use a new run directory")
        if previous is not None and previous != digest:
            raise ScheduleError("selected cases input changed; refusing resume")
        _check_unit_attribution(Path(args.run), groups[args.registry_entry], plan, plan_sha256)
        state.update(current)
        state["selected_case_sha256"][args.registry_entry] = digest
        U._atomic_write(str(path), json.dumps(state, indent=2, sort_keys=True) + "\n")
    return guard


def execute_plan(a):
    """One global writer/order, separate E06 run contexts for models; no budget or test gate override."""
    import fcntl
    from . import configs as CF
    from . import unit_exec as U
    plan = load_plan(a.plan, a.plan_sha256, configs_path=a.configs)
    if plan["order"] == "reverse":
        raise ScheduleError("reverse execution is not authorized: raw reverse is recorded, but the determinism "
                            "protocol and shared-C0 dependency handling require an author decision")
    if not math.isfinite(a.occupancy_interval) or not math.isfinite(a.occupancy_max_wait) or \
            a.occupancy_interval <= 0 or a.occupancy_max_wait < 0:
        raise ScheduleError("invalid occupancy wait settings")
    registry = CF.load_registry(a.configs)
    groups = defaultdict(list)
    for unit in plan["units"]:
        groups[unit["registry_entry"]].append(unit)
    root = Path(a.run)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".schedule.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ScheduleError("another scheduler owns this run directory") from None
        receipt = root / "schedule_plan.sha256"
        if receipt.exists() and receipt.read_text().strip() != a.plan_sha256:
            raise ScheduleError("run directory belongs to a different plan; use a new run directory")
        guard = _input_guard(root, plan, a.plan_sha256, groups)
        receipt.write_text(a.plan_sha256 + "\n")
        prepared = {}
        for model_id, selected in groups.items():
            args = copy.copy(a)
            args.run = str(root / "by-model" / model_id)
            args.registry_entry = model_id
            args.cond = sorted({u["config_id"] for u in selected})
            args.repeat = max(u["repeat"] for u in selected) + 1
            prepared[model_id] = U.prepare_run(args, planned_units=selected, extra_inputs=[a.plan],
                                              allowed_backends={"ollama", "canned"}, input_guard=guard)
        allowed = {p["backend"].model for p in prepared.values()}
        counts = {model: {} for model in prepared}
        lookup = {model: {unit_key(dict(case_id=c["case_id"], config_id=cfg["id"], repeat=k,
                                        registry_entry=model)): (c, cfg, k) for c, cfg, k in p["units"]}
                  for model, p in prepared.items()}
        with (root / "schedule_events.jsonl").open("a", encoding="utf-8") as events:
            def log(obj):
                events.write(json.dumps(dict(obj, at=U.now_iso()), sort_keys=True) + "\n")
                events.flush()
            log({"event": "execute_plan", "plan_sha256": a.plan_sha256, "units": len(plan["units"]),
                 "seed": plan["seed"], "order": plan["order"], "dependency_moves": plan["dependency_moves"]})
            for index, unit in enumerate(plan["units"]):
                model = unit["registry_entry"]
                p = prepared[model]
                case, cfg, k = lookup[model][unit_key(unit)]
                source = _source(unit, registry)
                if source is not None and U.unit_state(p["args"].run, case["case_id"], source["config_id"], k) != U.COMPLETE:
                    log({"event": "dependency_blocked", "unit": unit, "source": source, "planned_index": index})
                    counts[model][U.INCOMPLETE] = counts[model].get(U.INCOMPLETE, 0) + 1
                    continue
                waited = 0.0
                already_complete = U.unit_state(p["args"].run, case["case_id"], cfg["id"], k) == U.COMPLETE
                if not already_complete and p["backend"].kind == "ollama":
                    waited = wait_until_idle(a.host, p["backend"].model, log, allowed_models=allowed,
                                             max_wait=a.occupancy_max_wait, interval=a.occupancy_interval)
                metadata = {"order": plan["order"], "index": index, "planned_index": index,
                            "seed": plan["seed"], "plan_sha256": a.plan_sha256,
                            "occupancy_wait_seconds": waited, "freeze_gate": bool(p["gate"])}
                log({"event": "unit_resume" if already_complete else "unit_start", "unit": unit,
                     "planned_index": index, "occupancy_wait_seconds": waited})
                rec = U.run_unit(case, cfg, k, p["backend"], p["ctx"], schedule=metadata)
                counts[model][rec["status"]] = counts[model].get(rec["status"], 0) + 1
                log({"event": "unit_finish", "unit": unit, "planned_index": index, "status": rec["status"]})
            exits = [U.finish_run(p, counts[model]) for model, p in prepared.items()]
            log({"event": "execute_finished", "counts": counts, "exit_codes": exits})
        print(json.dumps({"plan_sha256": a.plan_sha256, "counts": counts}, sort_keys=True), flush=True)
        return 3 if 3 in exits else 4 if 4 in exits else 0


def cmd_execute(a):
    from . import configs as CF
    from . import unit_exec as U
    try:
        status = execute_plan(a)
    except (ScheduleError, CF.RegistryError, U.UnitRefused, OSError) as exc:
        raise SystemExit(f"[execute] {exc}") from exc
    if status:
        raise SystemExit(status)
