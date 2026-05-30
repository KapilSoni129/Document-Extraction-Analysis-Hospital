"""Integration tests: run the full LangGraph pipeline for key test cases.
Expected values loaded from test_cases JSON files."""

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from tests.conftest import get_expected, get_input
from app.agents.graph import process_claim


def _make_state(case_id: str, **overrides) -> dict:
    """Build pipeline state from a test case's input."""
    inp = get_input(case_id)
    state = {
        "claim_id": case_id,
        "member_id": inp["member_id"],
        "policy_id": inp.get("policy_id", "PLUM_GHI_2024"),
        "claim_category": inp["claim_category"],
        "treatment_date": inp["treatment_date"],
        "submission_date": inp.get("submission_date", inp["treatment_date"]),
        "claimed_amount": inp["claimed_amount"],
        "hospital_name": inp.get("hospital_name"),
        "ytd_claims_amount": inp.get("ytd_claims_amount", 0),
        "claims_history": inp.get("claims_history", []),
        "documents": inp.get("documents", []),
        "simulate_component_failure": inp.get("simulate_component_failure", False),
    }
    state.update(overrides)
    return state


def test_tc004_full_pipeline_approval():
    """TC004: Full approval through entire pipeline."""
    expected = get_expected("TC004")
    result = process_claim(_make_state("TC004"))
    assert result["decision"] == expected["decision"]
    assert result["approved_amount"] == float(expected["approved_amount"])
    assert result["confidence_score"] >= 0.85


def test_tc005_waiting_period_rejection():
    """TC005: Diabetes waiting period → REJECTED."""
    expected = get_expected("TC005")
    inp = get_input("TC005")
    state = _make_state("TC005")
    # Provide extracted_data with diagnosis (simulating doc extraction)
    state["extracted_data"] = [{"diagnosis": "Type 2 Diabetes Mellitus", "line_items": []}]
    result = process_claim(state)
    assert result["decision"] == expected["decision"]


def test_tc008_per_claim_exceeded():
    """TC008: Per-claim limit exceeded → REJECTED by policy evaluator."""
    expected = get_expected("TC008")
    state = _make_state("TC008")
    state["extracted_data"] = [{"diagnosis": "Gastroenteritis", "line_items": []}]
    result = process_claim(state)
    assert result["decision"] == expected["decision"]
    assert "PER_CLAIM_LIMIT" in result.get("rejection_reasons", [])


def test_tc009_fraud_manual_review():
    """TC009: Same-day fraud signals → MANUAL_REVIEW."""
    expected = get_expected("TC009")
    state = _make_state("TC009")
    state["extracted_data"] = [{"diagnosis": "Migraine", "line_items": []}]
    result = process_claim(state)
    assert result["decision"] == expected["decision"]
    assert len(result["fraud_signals"]) > 0


def test_tc010_network_discount():
    """TC010: Network hospital discount → APPROVED with correct amount."""
    expected = get_expected("TC010")
    inp = get_input("TC010")
    state = _make_state("TC010")
    state["extracted_data"] = [{
        "diagnosis": "Acute Bronchitis",
        "hospital_name": inp["hospital_name"],
        "line_items": inp["documents"][1]["content"]["line_items"],
    }]
    result = process_claim(state)
    assert result["decision"] == expected["decision"]
    assert result["approved_amount"] == float(expected["approved_amount"])


def test_tc017_initial_waiting_period():
    """TC017: 30-day initial waiting period → REJECTED at intake."""
    expected = get_expected("TC017")
    result = process_claim(_make_state("TC017"))
    assert result["decision"] == expected["decision"]
    assert "INITIAL_WAITING_PERIOD" in result.get("rejection_reasons", [])


def test_tc019_submission_deadline():
    """TC019: Submission deadline exceeded → REJECTED at intake."""
    expected = get_expected("TC019")
    result = process_claim(_make_state("TC019"))
    assert result["decision"] == expected["decision"]
    assert "SUBMISSION_DEADLINE_EXCEEDED" in result.get("rejection_reasons", [])


def test_tc020_below_minimum():
    """TC020: Below minimum amount → REJECTED at intake."""
    expected = get_expected("TC020")
    result = process_claim(_make_state("TC020"))
    assert result["decision"] == expected["decision"]
    assert "BELOW_MINIMUM_AMOUNT" in result.get("rejection_reasons", [])


def test_tc021_monthly_limit_fraud():
    """TC021: Monthly claims limit → MANUAL_REVIEW."""
    expected = get_expected("TC021")
    state = _make_state("TC021")
    state["extracted_data"] = [{"diagnosis": "Tension Headache", "line_items": []}]
    result = process_claim(state)
    assert result["decision"] == expected["decision"]


def test_trace_end_to_end():
    """Verify trace is populated through the full pipeline."""
    result = process_claim(_make_state("TC004"))
    assert len(result["trace"]) > 0
    agents_in_trace = {step["agent"] for step in result["trace"]}
    assert "intake" in agents_in_trace
    assert "decision_maker" in agents_in_trace
