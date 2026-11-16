"""Campaign audit distinguishes setup metadata from experimental units."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("it0_campaign", Path(__file__).parents[1] / "run_gene_it0_dev.py")
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)


def write_stage(tmp_path):
    units = tmp_path / "units"
    units.mkdir()
    (units / "setup.json").write_text(json.dumps({"schema_version": "orgene.r1.unit_setup.v1"}))
    for cond in campaign.CONDS:
        row = {"schema_version": "orgene.r1.unit.v1", "case_id": "toy", "config_id": cond,
               "unit_id": f"toy.{cond}.r0", "status": "complete", "rounds": [{}],
               "tokens": {"local": {"n_calls_missing": 0}}, "local_tokenizer": {"id": "toy"},
               "code_sha256": {"runtime/orgene/predicates_it0.py": "approved"},
               "round0": {"reused_from": {"unit_id": "toy.C0.r0"}}}
        (units / f"{cond}.json").write_text(json.dumps(row))
    return units


def test_setup_is_not_an_experiment(tmp_path):
    write_stage(tmp_path)
    assert campaign.check_stage(tmp_path, 1, "approved")["units"] == 4


def test_unknown_artifact_is_not_silently_ignored(tmp_path):
    units = write_stage(tmp_path)
    (units / "unexpected.json").write_text("{}")
    with pytest.raises(RuntimeError, match="unexpected unit artifact"):
        campaign.check_stage(tmp_path, 1, "approved")


@pytest.mark.parametrize("field", ["tokens", "round0", "code_sha256"])
def test_invalid_evidence_stops_campaign(tmp_path, field):
    units = write_stage(tmp_path)
    p = units / "C3L.json"
    row = json.loads(p.read_text())
    row[field] = {"tokens": {"local": {"n_calls_missing": 1}},
                  "round0": {"reused_from": {"unit_id": "other.C0.r0"}},
                  "code_sha256": {"predicate": "changed"}}[field]
    p.write_text(json.dumps(row))
    with pytest.raises(RuntimeError):
        campaign.check_stage(tmp_path, 1, "approved")
