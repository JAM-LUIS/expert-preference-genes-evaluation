# E07 engineering checkpoint: seeded scheduler

This implementation changes engineering scheduling only. No study data were read or model experiments run
during implementation. E07 remains **partially open**: the reverse-order determinism protocol needs an author
decision. There are no new genes, formal test results, preregistration records or claimed accuracy gains.

`orgene_cli.py plan` reads an explicit `schema_version: 1` matrix of ids:

```json
{"schema_version":1,"units":[
  {"case_id":"toy-a","config_id":"C0","repeat":0,"registry_entry":"toy.main"},
  {"case_id":"toy-a","config_id":"C3L","repeat":0,"registry_entry":"toy.main"}
]}
```

Every case/config/repeat/model combination is explicit. Duplicates, unknown/adapter configurations, invalid
ids/repeats and missing same-case/repeat/model round-0 sources are refused. Source chains are not allowed by
the configuration registry. Plans record a seeded global shuffle, then each move of a consumer that appeared
before its source to the position immediately after that source. The plan stores raw and actual order separately,
seed, matrix digest, configuration-registry byte digest and all dependency moves. The plan is written once with
a separate byte-SHA receipt. Execution requires the recorded SHA explicitly and deterministically replays the
plan, refusing changed registry bytes, altered metadata/order or a different plan in the same run directory.

## Reverse is not a closed scientific protocol

`--order reverse` produces the exact reverse of the same seed's **raw shuffled order**. Dependency correction
may make its actual execution order different. The plan reports `exact_reverse=false` when moves are necessary
and `reverse_protocol_status=blocked_dependency_adjustments`. Even when no moves are necessary, status is
`awaiting_protocol_authorization`. **Execution refuses all reverse plans.** This prevents engineering bookkeeping
from being mistaken for completion of the original exact-reverse determinism protocol. The author must decide
how shared C0 is handled (for example, authorized cached C0 versus an agreed stratified protocol) before the
scientific reverse protocol can be implemented or run. No new author decision is inferred here.

## Execution and safeguards

`execute` serially follows the one global plan across all models. Each registry entry gets its own E06 context
under `<run>/by-model/<entry>/`; unit filenames and shared round-0 sources therefore cannot collide across models.
An exclusive nonblocking run lock rejects concurrent schedulers. Execution reuses E06's test/freeze gate, registry
check, interpreter check, configuration/settings check, local token counter, rendered-request preflight, run-unit
request/content/model hash checks, completed-unit skip and incomplete-unit retry. The plan itself is included
among freeze-covered inputs. Existing `unit_runner.py` retains its fixed-order behavior for regression use.

The freeze gate runs before case objects are deserialized. Scheduled execution supplies plan ids directly;
the default runner uses a lexical scan of top-level `case_id` metadata and preserves file-order selection/limits.
Excluded rows do not become question/reference objects, including when a dev file also contains sealed test rows.
Explicit sealed splits are checked before even loading their split-id file. An E07 input receipt is written only
after a passing gate: it pins the resolved cases path, case-file byte SHA, and selected-case SHA for each model.
Resume refuses changed paths or contents before model preflight and preserves the original receipt. Existing
contexts without this receipt are rejected; every saved complete/running/incomplete unit must carry the current
plan SHA, global planned index, seed and order. Old fixed-order results cannot be relabeled as a new seeded run.

Before each new Ollama unit, `/api/ps` is checked. Loaded model names outside the current plan cause bounded
waiting and event logging; malformed/unavailable responses refuse execution. No model is unloaded or killed.
`/api/ps` identifies a model, not a project: another project using the same model name cannot be distinguished.
Independent resource coordination remains necessary. API-backed entries are refused; this scheduler permits
local Ollama and the synthetic canned testing backend only.

The existing E06 record contains started/finished timestamps, server and wall duration and queue-wait estimate.
The new `schedule` metadata contains global `planned_index`, seed, plan SHA and occupancy-wait duration.
`schedule_events.jsonl` records starts, resumes, ends, dependency blocks and occupancy decisions with ids only.
If a source unit is incomplete, its consumers are logged as dependency-blocked and the process returns 4.
Retrying the same plan retries unfinished work and skips completed work. Return 3 retains model-drift refusal.

## Validation commands (existing locked environment; no model experiments)

```sh
"$ORGENE_PY" -B -m pytest -q -p no:cacheprovider \
  runtime/tests/test_schedule.py runtime/tests/test_schedule_execute.py runtime/tests/test_schedule_receipts.py \
  runtime/tests/test_unit_exec.py tools/tests/test_test_gate.py tools/tests/test_gate_inputs.py
```

The scheduler tests use synthetic ids/registries and fake occupancy responses, including 1,000 seeds. Integration
tests use the existing hand-made toy cases and local fake Ollama HTTP server; they verify separate model contexts,
global order, shared C0, no calls on completed-unit resume, dependency blocking/retry, hash refusal and freeze/reverse
gates. Negative tests assert protected case loaders were never called, and receipt/attribution tests reject changed
text, reference, same-byte new paths, unattributed artifacts and tampered units across all three statuses.
The existing E06 tests verify repair, execution and resume behavior. Remote pytest and independent review are
still pending at this checkpoint; local syntax/stdlib checks alone do not close the engineering gate.
