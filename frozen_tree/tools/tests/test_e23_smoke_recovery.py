"""One-shot recovery claim tests using only invented tmp_path journals.

No model, HTTP, SSH, subprocess, real campaign, case text or answer is accessed.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("e23_smoke_recovery_under_test", TOOLS / "execute_e23_smoke.py")
DRIVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRIVER)

PRIOR = "invented-smoke-dev-prior"
CAMPAIGN = "invented-smoke-dev-recovery"
CLAIMED_AT = "2026-09-30T20:00:00+00:00"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_status(root, campaign, obj):
    directory = root / "experiments" / campaign
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "status.json"
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def prior_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(DRIVER, "now", lambda: CLAIMED_AT)
    # These fail-fast mocks guard against an accidental future model/resource operation.
    def forbidden(*args, **kwargs):
        raise AssertionError("recovery claims must perform metadata IO only")
    monkeypatch.setattr(DRIVER.urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(DRIVER.subprocess, "run", forbidden)
    monkeypatch.setattr(DRIVER.subprocess, "check_output", forbidden)
    record = {"state": "failed", "error": "invented preflight resource refusal",
              "stages": [{"label": "registry-validate", "state": "passed"},
                         {"label": "venv-tools", "state": "passed"},
                         {"label": "registry-live-quick", "state": "passed"}]}
    status = write_status(tmp_path, PRIOR, record)
    log = status.parent / "registry-live-quick.log"
    log.write_bytes(b"invented original preflight log\n")
    return tmp_path, record, status, log


def test_first_valid_claim_records_identity_and_preserves_original_evidence(prior_journal):
    root, record, status, log = prior_journal
    original_status, original_log = status.read_bytes(), log.read_bytes()
    recovery = DRIVER.claim_recovery(root, CAMPAIGN, PRIOR)
    assert recovery == {"campaign": PRIOR, "status_sha256": sha(original_status),
                        "reason": record["error"], "generation_stages_in_prior": 0}
    claim = json.loads((status.parent / "recovery.claim.json").read_text())
    assert claim == dict(recovery, recovery_campaign=CAMPAIGN, claimed_at=CLAIMED_AT)
    assert status.read_bytes() == original_status and log.read_bytes() == original_log
    assert sha(status.read_bytes()) == recovery["status_sha256"]
    # Claiming reserves metadata; it does not create/execute a new model campaign.
    assert not (root / "experiments" / CAMPAIGN).exists()


@pytest.mark.parametrize("state", ["running", "starting", "complete"])
def test_only_failed_prior_is_recoverable(prior_journal, state):
    root, record, status, _ = prior_journal
    record["state"] = state
    write_status(root, PRIOR, record)
    with pytest.raises(RuntimeError):
        DRIVER.claim_recovery(root, CAMPAIGN, PRIOR)
    assert not (status.parent / "recovery.claim.json").exists()


@pytest.mark.parametrize("stage_state", ["failed", "running", "passed"])
def test_any_generation_stage_blocks_recovery_even_if_it_failed(prior_journal, stage_state):
    root, record, status, _ = prior_journal
    record["stages"].append({"label": "generation", "state": stage_state})
    write_status(root, PRIOR, record)
    with pytest.raises(RuntimeError):
        DRIVER.claim_recovery(root, CAMPAIGN, PRIOR)
    assert not (status.parent / "recovery.claim.json").exists()


def test_server_token_stage_blocks_recovery(prior_journal):
    root, record, status, _ = prior_journal
    record["stages"].append({"label": "server-token-comparison", "state": "failed"})
    write_status(root, PRIOR, record)
    with pytest.raises(RuntimeError):
        DRIVER.claim_recovery(root, CAMPAIGN, PRIOR)
    assert not (status.parent / "recovery.claim.json").exists()


@pytest.mark.parametrize("retry_state", ["starting", "running", "failed", "complete"])
def test_existing_recovery_journal_blocks_reuse_without_a_backfill_claim(prior_journal, retry_state):
    root, _, status, _ = prior_journal
    original = status.read_bytes()
    write_status(root, "invented-smoke-dev-existing-retry", {
        "state": retry_state, "recovery_of": {"campaign": PRIOR, "status_sha256": sha(original)}, "stages": []})
    with pytest.raises(RuntimeError):
        DRIVER.claim_recovery(root, CAMPAIGN, PRIOR)
    assert status.read_bytes() == original and not (status.parent / "recovery.claim.json").exists()


def test_an_unrelated_prior_recovery_does_not_consume_this_prior(prior_journal):
    root, _, _, _ = prior_journal
    write_status(root, "invented-other-dev-retry", {"state": "complete", "recovery_of": {"campaign": "other-dev-prior"}})
    assert DRIVER.claim_recovery(root, CAMPAIGN, PRIOR)["campaign"] == PRIOR


def test_existing_claim_is_never_overwritten(prior_journal):
    root, _, status, _ = prior_journal
    claim = status.parent / "recovery.claim.json"
    original = b'{"recovery_campaign":"invented-existing-dev"}\n'
    claim.write_bytes(original)
    with pytest.raises(RuntimeError):
        DRIVER.claim_recovery(root, CAMPAIGN, PRIOR)
    assert claim.read_bytes() == original


def test_second_claim_cannot_resample_under_a_different_new_campaign(prior_journal):
    root, _, status, _ = prior_journal
    DRIVER.claim_recovery(root, CAMPAIGN, PRIOR)
    claim = status.parent / "recovery.claim.json"
    original = claim.read_bytes()
    with pytest.raises(RuntimeError):
        DRIVER.claim_recovery(root, "invented-smoke-dev-second-recovery", PRIOR)
    assert claim.read_bytes() == original


def test_failed_prior_with_empty_stages_is_valid(prior_journal):
    root, record, _, _ = prior_journal
    record["stages"] = []
    write_status(root, PRIOR, record)
    assert DRIVER.claim_recovery(root, CAMPAIGN, PRIOR)["generation_stages_in_prior"] == 0


def test_missing_stages_cannot_prove_zero_generation(prior_journal):
    root, record, status, _ = prior_journal
    del record["stages"]
    write_status(root, PRIOR, record)
    with pytest.raises(RuntimeError):
        DRIVER.claim_recovery(root, CAMPAIGN, PRIOR)
    assert not (status.parent / "recovery.claim.json").exists()


@pytest.mark.parametrize("malformed", [None, {}, "unknown", [None], [1],
                                       [{"label": "registry-validate", "state": "passed"}, "invalid-row"]])
def test_malformed_stages_fail_closed(prior_journal, malformed):
    root, record, status, _ = prior_journal
    record["stages"] = malformed
    write_status(root, PRIOR, record)
    with pytest.raises(RuntimeError):
        DRIVER.claim_recovery(root, CAMPAIGN, PRIOR)
    assert not (status.parent / "recovery.claim.json").exists()


def test_missing_prior_status_is_refused_without_creating_claim(prior_journal):
    root, _, _, _ = prior_journal
    with pytest.raises(FileNotFoundError):
        DRIVER.claim_recovery(root, CAMPAIGN, "invented-missing-dev-prior")
    assert not (root / "experiments/invented-missing-dev-prior").exists()


@pytest.mark.parametrize("bad", ["", ".", "..", "ordinary", "invented-dev-test", "nested/invented-dev", "/invented-dev"])
@pytest.mark.parametrize("argument", ["campaign", "prior"])
def test_invalid_campaign_basenames_are_refused_before_claim(prior_journal, bad, argument):
    root, _, status, _ = prior_journal
    with pytest.raises(RuntimeError):
        DRIVER.claim_recovery(root, bad if argument == "campaign" else CAMPAIGN,
                              bad if argument == "prior" else PRIOR)
    assert not (status.parent / "recovery.claim.json").exists()


def test_existing_new_campaign_directory_is_refused(prior_journal):
    root, _, status, _ = prior_journal
    (root / "experiments" / CAMPAIGN).mkdir()
    with pytest.raises(RuntimeError):
        DRIVER.claim_recovery(root, CAMPAIGN, PRIOR)
    assert not (status.parent / "recovery.claim.json").exists()


def test_exclusive_claim_allows_only_one_concurrent_recovery(prior_journal):
    root, _, status, _ = prior_journal

    def attempt(campaign):
        try:
            DRIVER.claim_recovery(root, campaign, PRIOR)
            return campaign, "claimed"
        except RuntimeError:
            return campaign, "refused"

    campaigns = ["invented-concurrent-dev-a", "invented-concurrent-dev-b"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, campaigns))
    assert sorted(result for _, result in results) == ["claimed", "refused"]
    winner = next(campaign for campaign, result in results if result == "claimed")
    assert json.loads((status.parent / "recovery.claim.json").read_text())["recovery_campaign"] == winner
