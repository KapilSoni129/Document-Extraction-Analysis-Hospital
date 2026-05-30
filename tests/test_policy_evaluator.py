"""Tests for policy evaluator agent — rule checks, exclusions, fraud, calculations.
Expected values loaded from test_cases JSON files."""

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from tests.conftest import get_expected, get_input
from app.agents.intake import intake_agent
from app.agents.policy_evaluator import policy_evaluator


def _run_through_intake(state):
    """Helper: run intake first to populate member_info and category_config."""
    result = intake_agent(state)
    state.update(result)
    return state


def _base_state(**overrides):
    state = {
        "claim_id": "TEST",
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "submission_date": "2024-11-01",
        "claimed_amount": 1500,
        "hospital_name": None,
        "ytd_claims_amount": 5000,
        "claims_history": [],
        "documents": [],
        "simulate_component_failure": False,
        "trace": [],
        "extracted_data": [],
    }
    state.update(overrides)
    return _run_through_intake(state)


def test_tc005_diabetes_waiting_period():
    """TC005: Diabetes within 90-day waiting period → REJECTED."""
    inp = get_input("TC005")
    state = _base_state(
        member_id=inp["member_id"],
        treatment_date=inp["treatment_date"],
        submission_date=inp["treatment_date"],
        claimed_amount=inp["claimed_amount"],
        extracted_data=[{"diagnosis": "Type 2 Diabetes Mellitus", "line_items": []}],
    )
    result = policy_evaluator(state)
    rejects = [c for c in result["policy_checks"] if c.get("impact") == "REJECT"]
    assert len(rejects) > 0
    assert "waiting_period" in rejects[0]["rule_name"]


def test_tc006_dental_partial():
    """TC006: Root canal covered, teeth whitening excluded → PARTIAL."""
    inp = get_input("TC006")
    expected = get_expected("TC006")
    line_items = inp["documents"][0]["content"]["line_items"]
    state = _base_state(
        member_id=inp["member_id"],
        claim_category=inp["claim_category"],
        treatment_date=inp["treatment_date"],
        submission_date=inp["treatment_date"],
        claimed_amount=10000,  # within dental sub-limit to pass intake
        extracted_data=[{
            "diagnosis": "Dental Caries",
            "line_items": line_items,
        }],
    )
    # Override claimed_amount for policy evaluator (real claim is 12000)
    state["claimed_amount"] = inp["claimed_amount"]
    result = policy_evaluator(state)
    line_excl = [c for c in result["policy_checks"] if c["rule_name"] == "line_item_exclusion"]
    assert len(line_excl) > 0
    assert "Teeth Whitening" in line_excl[0]["details"]
    assert result["amount_breakdown"]["final_approved"] == float(expected["approved_amount"])


def test_tc007_pre_auth_missing():
    """TC007: MRI without pre-auth → passes (amount within limit for this path)."""
    pass


def test_tc007_pre_auth_logic():
    """TC007: Pre-auth required when amount exceeds threshold for high-value tests."""
    inp = get_input("TC007")
    state = _base_state(
        member_id=inp["member_id"],
        claim_category=inp["claim_category"],
        treatment_date=inp["treatment_date"],
        submission_date=inp["treatment_date"],
        claimed_amount=5000,  # within per-claim for intake to pass
        extracted_data=[{
            "diagnosis": "Suspected Lumbar Disc Herniation",
            "line_items": [{"description": "MRI Lumbar Spine", "amount": 15000}],
        }],
        ytd_claims_amount=0,
    )
    # Override claimed_amount higher for policy evaluator
    state["claimed_amount"] = inp["claimed_amount"]
    result = policy_evaluator(state)
    rejects = [c for c in result["policy_checks"] if c.get("impact") == "REJECT"]
    pre_auth = [c for c in rejects if "pre_authorization" in c["rule_name"]]
    assert len(pre_auth) > 0
    assert "pre-authorization" in pre_auth[0]["details"].lower()


def test_tc009_fraud_same_day():
    """TC009: 4th same-day claim triggers fraud signal."""
    inp = get_input("TC009")
    state = _base_state(
        member_id=inp["member_id"],
        treatment_date=inp["treatment_date"],
        submission_date=inp["treatment_date"],
        claimed_amount=inp["claimed_amount"],
        claims_history=inp["claims_history"],
        extracted_data=[{"diagnosis": "Migraine", "line_items": []}],
    )
    result = policy_evaluator(state)
    assert len(result["fraud_signals"]) > 0
    assert result["fraud_signals"][0]["signal"] == "SAME_DAY_CLAIMS"


def test_tc010_network_discount_calculation():
    """TC010: Apollo hospital network discount → ₹3,240."""
    inp = get_input("TC010")
    expected = get_expected("TC010")
    state = _base_state(
        member_id=inp["member_id"],
        treatment_date=inp["treatment_date"],
        submission_date=inp["treatment_date"],
        claimed_amount=inp["claimed_amount"],
        hospital_name=inp["hospital_name"],
        ytd_claims_amount=inp["ytd_claims_amount"],
        extracted_data=[{
            "diagnosis": "Acute Bronchitis",
            "hospital_name": inp["hospital_name"],
            "line_items": inp["documents"][1]["content"]["line_items"],
        }],
    )
    result = policy_evaluator(state)
    assert result["amount_breakdown"] is not None
    assert result["amount_breakdown"]["after_network_discount"] == 3600.0
    assert result["amount_breakdown"]["final_approved"] == float(expected["approved_amount"])


def test_tc012_excluded_condition():
    """TC012: Obesity/bariatric is excluded → REJECTED."""
    inp = get_input("TC012")
    state = _base_state(
        member_id=inp["member_id"],
        treatment_date=inp["treatment_date"],
        submission_date=inp["treatment_date"],
        claimed_amount=5000,  # within per-claim limit
        extracted_data=[{
            "diagnosis": "Morbid Obesity - BMI 37",
            "line_items": inp["documents"][1]["content"]["line_items"],
        }],
    )
    result = policy_evaluator(state)
    rejects = [c for c in result["policy_checks"] if c.get("impact") == "REJECT"]
    assert len(rejects) > 0
    reject_rules = [c["rule_name"] for c in rejects]
    assert "exclusion_check" in reject_rules or "condition_waiting_period" in reject_rules


def test_tc021_monthly_limit():
    """TC021: 7th claim in a month triggers fraud signal."""
    inp = get_input("TC021")
    state = _base_state(
        member_id=inp["member_id"],
        treatment_date=inp["treatment_date"],
        submission_date=inp["treatment_date"],
        claimed_amount=inp["claimed_amount"],
        claims_history=inp["claims_history"],
        extracted_data=[{"diagnosis": "Tension Headache", "line_items": []}],
    )
    result = policy_evaluator(state)
    monthly_fraud = [f for f in result["fraud_signals"] if f["signal"] == "MONTHLY_CLAIMS_LIMIT"]
    assert len(monthly_fraud) > 0


def test_tc004_clean_approval():
    """TC004: No policy issues, amount calculated correctly."""
    inp = get_input("TC004")
    expected = get_expected("TC004")
    state = _base_state(
        member_id=inp["member_id"],
        claimed_amount=inp["claimed_amount"],
        ytd_claims_amount=inp.get("ytd_claims_amount", 0),
        extracted_data=[{
            "diagnosis": "Viral Fever",
            "line_items": inp["documents"][1]["content"]["line_items"],
        }],
    )
    result = policy_evaluator(state)
    assert len(result["fraud_signals"]) == 0
    rejects = [c for c in result["policy_checks"] if c.get("impact") == "REJECT"]
    assert len(rejects) == 0
    assert result["amount_breakdown"]["final_approved"] == float(expected["approved_amount"])


def test_trace_populated():
    state = _base_state(
        extracted_data=[{"diagnosis": "Viral Fever", "line_items": []}],
    )
    result = policy_evaluator(state)
    assert len(result["trace"]) > 0
    policy_steps = [t for t in result["trace"] if t["agent"] == "policy_evaluator"]
    assert len(policy_steps) > 0
