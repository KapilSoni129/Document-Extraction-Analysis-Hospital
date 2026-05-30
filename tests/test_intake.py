"""Tests for intake agent — member validation, deadlines, limits.
Expected values loaded from test_cases JSON files."""

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from tests.conftest import get_expected, get_input
from app.agents.intake import intake_agent


def _base_state(**overrides):
    state = {
        "claim_id": "TEST_001",
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "submission_date": "2024-11-01",
        "claimed_amount": 1500,
        "hospital_name": None,
        "ytd_claims_amount": 0,
        "claims_history": [],
        "documents": [],
        "simulate_component_failure": False,
        "trace": [],
    }
    state.update(overrides)
    return state


def test_tc004_valid_claim_passes_intake():
    """TC004: Valid member, within all limits → passes intake."""
    inp = get_input("TC004")
    state = _base_state(
        member_id=inp["member_id"],
        claim_category=inp["claim_category"],
        treatment_date=inp["treatment_date"],
        claimed_amount=inp["claimed_amount"],
        ytd_claims_amount=inp.get("ytd_claims_amount", 0),
    )
    result = intake_agent(state)
    assert result["early_rejection"] is None
    assert result["member_info"]["name"] == "Rajesh Kumar"
    assert result["category_config"]["copay_percent"] == 10


def test_member_not_found():
    state = _base_state(member_id="EMP999")
    result = intake_agent(state)
    assert result["early_rejection"] is not None
    assert result["early_rejection"]["reason_code"] == "MEMBER_NOT_FOUND"


def test_tc020_below_minimum_amount():
    """TC020: Amount below ₹500 minimum."""
    inp = get_input("TC020")
    state = _base_state(
        member_id=inp["member_id"],
        claim_category=inp["claim_category"],
        treatment_date=inp["treatment_date"],
        claimed_amount=inp["claimed_amount"],
    )
    result = intake_agent(state)
    assert result["early_rejection"]["reason_code"] == "BELOW_MINIMUM_AMOUNT"
    assert str(inp["claimed_amount"]) in result["early_rejection"]["message"]


def test_tc008_passes_intake():
    """TC008: Amount exceeds per-claim limit — passes intake, handled by policy evaluator."""
    inp = get_input("TC008")
    state = _base_state(
        member_id=inp["member_id"],
        claim_category=inp["claim_category"],
        treatment_date=inp["treatment_date"],
        claimed_amount=inp["claimed_amount"],
        ytd_claims_amount=inp.get("ytd_claims_amount", 0),
    )
    result = intake_agent(state)
    assert result["early_rejection"] is None


def test_tc019_submission_deadline_exceeded():
    """TC019: Treatment 2024-08-15, submission 2024-10-20 — exceeds 30-day deadline."""
    inp = get_input("TC019")
    state = _base_state(
        member_id=inp["member_id"],
        claim_category=inp["claim_category"],
        treatment_date=inp["treatment_date"],
        submission_date=inp["submission_date"],
        claimed_amount=inp["claimed_amount"],
    )
    result = intake_agent(state)
    assert result["early_rejection"]["reason_code"] == "SUBMISSION_DEADLINE_EXCEEDED"
    assert "30" in result["early_rejection"]["message"]


def test_tc017_initial_waiting_period():
    """TC017: EMP005 joined 2024-09-01, treatment 2024-09-20 — within 30-day waiting."""
    inp = get_input("TC017")
    state = _base_state(
        member_id=inp["member_id"],
        claim_category=inp["claim_category"],
        treatment_date=inp["treatment_date"],
        submission_date=inp["treatment_date"],
        claimed_amount=inp["claimed_amount"],
    )
    result = intake_agent(state)
    assert result["early_rejection"]["reason_code"] == "INITIAL_WAITING_PERIOD"
    assert "2024-10-01" in result["early_rejection"]["message"]


def test_tc005_initial_waiting_period_passes():
    """TC005: EMP005 joined 2024-09-01, treatment 2024-10-15 = 44 days > 30 — passes."""
    inp = get_input("TC005")
    state = _base_state(
        member_id=inp["member_id"],
        treatment_date=inp["treatment_date"],
        submission_date=inp["treatment_date"],
        claimed_amount=inp["claimed_amount"],
    )
    result = intake_agent(state)
    assert result["early_rejection"] is None


def test_tc015_dependent_passes_intake():
    """TC015: DEP001 (spouse of EMP001) passes intake."""
    inp = get_input("TC015")
    state = _base_state(
        member_id=inp["member_id"],
        claim_category=inp["claim_category"],
        treatment_date=inp["treatment_date"],
        claimed_amount=inp["claimed_amount"],
    )
    result = intake_agent(state)
    assert result["early_rejection"] is None
    assert result["member_info"]["name"] == "Sunita Kumar"


def test_trace_populated():
    state = _base_state()
    result = intake_agent(state)
    assert len(result["trace"]) > 0
    assert all(step["agent"] == "intake" for step in result["trace"])
