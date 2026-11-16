"""E12: tools/recorder_check.py, the dev-rehearsal check that the recorder does not change program behaviour.

Run directories, case ids and split files are all made up inside tmp_path; no benchmark case or split is read.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import solve_fixtures as FX  # noqa: E402

from orgene.conditions import write_jsonl  # noqa: E402

TOOL = os.path.join(FX.ROOT, "tools", "recorder_check.py")
needs_py = pytest.mark.skipif(not os.path.exists(FX.PY), reason=f"generation interpreter {FX.PY} not present")


def _splits(tmp_path):
    d = tmp_path / "splits" / "fx"
    d.mkdir(parents=True)
    (d / "test_ids.json").write_text(json.dumps(["fx-held-out"]))
    return str(tmp_path / "splits")


@needs_py
def test_recorder_check_on_a_dev_style_run(tmp_path):
    run = tmp_path / "20260101-fixture-smoke-dev-C0"
    run.mkdir()
    recs = [{"case_id": "fx-1", "condition": "C0", "repeat": 0, "code": FX.HONEST},
            {"case_id": "fx-2", "condition": "C0", "repeat": 0, "code": FX.ERRORS["chained_exception"]},
            {"case_id": "fx-3", "condition": "C0", "repeat": 0, "code": FX.ERRORS["default_solver_path"]},
            {"case_id": "fx-4", "condition": "C0", "repeat": 0, "code": None}]
    write_jsonl(str(run / "validated.C0.round0.jsonl"), recs)
    out = tmp_path / "check.json"
    p = subprocess.run([sys.executable, TOOL, str(run), "--splits-root", _splits(tmp_path), "--out", str(out)],
                       capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stdout + p.stderr
    rep = json.load(open(out))
    assert rep["counts"] == {"identical": 3, "identical_after_normalization": 0, "different": 0, "no_program": 1}
    assert FX.HONEST not in out.read_text() and "2600" not in out.read_text()  # ids and flags only


@needs_py
def test_recorder_check_normalizes_a_program_whose_own_output_varies(tmp_path):
    run = tmp_path / "20260101-fixture-smoke-dev-C0"
    run.mkdir()
    noisy = FX.HEAD + "import time\nprint('Total time (CPU seconds):', time.perf_counter_ns())\n" + FX.SOLVE + FX.PRINT
    write_jsonl(str(run / "validated.C0.round0.jsonl"), [{"case_id": "fx-1", "condition": "C0", "code": noisy}])
    out = tmp_path / "check.json"
    p = subprocess.run([sys.executable, TOOL, str(run), "--splits-root", _splits(tmp_path), "--out", str(out)],
                       capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stdout + p.stderr
    rep = json.load(open(out))
    assert rep["counts"]["identical_after_normalization"] == 1
    assert rep["per_program"][0]["plain_deterministic"] is False


def test_recorder_check_refuses_test_runs_and_test_ids(tmp_path):
    splits = _splits(tmp_path)
    marker = tmp_path / "executed.txt"
    prog = f"open({str(marker)!r}, 'w').write('x')\n"
    bad_dir = tmp_path / "20260101-fixture-smoke-test-C0"
    bad_dir.mkdir()
    write_jsonl(str(bad_dir / "validated.C0.round0.jsonl"), [{"case_id": "fx-1", "code": prog}])
    p = subprocess.run([sys.executable, TOOL, str(bad_dir), "--splits-root", splits],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 2 and "refused" in p.stderr and not marker.exists()
    dev_dir = tmp_path / "20260101-fixture-smoke-dev-C0"
    dev_dir.mkdir()
    write_jsonl(str(dev_dir / "validated.C0.round0.jsonl"), [{"case_id": "fx-held-out", "code": prog}])
    p = subprocess.run([sys.executable, TOOL, str(dev_dir), "--splits-root", splits],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 2 and "refused" in p.stderr and not marker.exists()


def test_recorder_check_fails_closed_without_test_id_lists(tmp_path):
    """A wrong or empty --splits-root cannot rule out test cases, so nothing runs."""
    marker = tmp_path / "executed.txt"
    dev_dir = tmp_path / "20260101-fixture-smoke-dev-C0"
    dev_dir.mkdir()
    write_jsonl(str(dev_dir / "validated.C0.round0.jsonl"),
                [{"case_id": "fx-1", "code": f"open({str(marker)!r}, 'w').write('x')\n"}])
    empty = tmp_path / "no-splits"
    empty.mkdir()
    p = subprocess.run([sys.executable, TOOL, str(dev_dir), "--splits-root", str(empty)],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 2 and "refused" in p.stderr and "test ids" in p.stderr and not marker.exists()
