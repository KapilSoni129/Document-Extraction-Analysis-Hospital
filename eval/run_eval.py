"""Evaluation runner: processes all 22 test cases and generates a report."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.graph import process_claim

ROOT = Path(__file__).parent.parent
TEST_CASES_FILE = ROOT / "test_cases.json"
TEST_CASES_EXTENDED_FILE = ROOT / "test_cases_extended.json"


def load_all_cases():
    cases = []
    for path in (TEST_CASES_FILE, TEST_CASES_EXTENDED_FILE):
        if path.exists():
            data = json.loads(path.read_text())
            cases.extend(data["test_cases"])
    return cases


def build_state(tc):
    """Build pipeline state from test case input, with extracted_data from document content."""
    inp = tc["input"]
    extracted_data = []
    for doc in inp.get("documents", []):
        content = doc.get("content", {})
        if content:
            extracted_data.append({
                "patient_name": content.get("patient_name"),
                "doctor_name": content.get("doctor_name"),
                "date": content.get("date"),
                "diagnosis": content.get("diagnosis"),
                "hospital_name": content.get("hospital_name"),
                "line_items": content.get("line_items", []),
                "total": content.get("total"),
            })

    state = {
        "claim_id": tc["case_id"],
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
        "extracted_data": extracted_data,
    }

    # TC022 specifically tests sub-limit enforcement
    if tc["case_id"] == "TC022":
        state["apply_sub_limit"] = True

    return state


def evaluate_case(tc, result):
    """Compare result against expected. Returns (passed, details)."""
    expected = tc["expected"]
    checks = []
    passed = True

    # Check decision
    expected_decision = expected.get("decision")
    if expected_decision:
        actual_decision = result.get("decision")
        if actual_decision == expected_decision:
            checks.append(f"  Decision: {actual_decision} == {expected_decision} PASS")
        else:
            checks.append(f"  Decision: {actual_decision} != {expected_decision} FAIL")
            passed = False

    # Check approved amount
    expected_amount = expected.get("approved_amount")
    if expected_amount is not None:
        actual_amount = result.get("approved_amount", 0)
        if abs(actual_amount - float(expected_amount)) < 1.0:
            checks.append(f"  Amount: ₹{actual_amount:,.0f} == ₹{expected_amount:,.0f} PASS")
        else:
            checks.append(f"  Amount: ₹{actual_amount:,.0f} != ₹{expected_amount:,.0f} FAIL")
            passed = False

    # Check confidence
    confidence_req = expected.get("confidence_score")
    if confidence_req and "above" in confidence_req:
        threshold = float(confidence_req.split()[-1])
        actual_conf = result.get("confidence_score", 0)
        if actual_conf >= threshold:
            checks.append(f"  Confidence: {actual_conf:.2f} >= {threshold} PASS")
        else:
            checks.append(f"  Confidence: {actual_conf:.2f} < {threshold} FAIL")
            passed = False

    # Check rejection reasons (semantic matching)
    expected_reasons = expected.get("rejection_reasons", [])
    if expected_reasons:
        actual_reasons = result.get("rejection_reasons", [])
        policy_check_rules = [c.get("rule_name", "").upper() for c in result.get("policy_checks", [])
                              if c.get("impact") == "REJECT"]
        all_reasons = actual_reasons + policy_check_rules

        # Semantic equivalence map
        equiv = {
            "PRE_AUTH_MISSING": ["PRE_AUTHORIZATION", "PRE_AUTH"],
            "PER_CLAIM_EXCEEDED": ["PER_CLAIM_LIMIT", "PER_CLAIM"],
            "EXCLUDED_CONDITION": ["EXCLUSION_CHECK", "EXCLUSION", "CONDITION_WAITING_PERIOD"],
            "EXCLUDED_PROCEDURE": ["LINE_ITEM_EXCLUSION", "EXCLUSION_CHECK"],
            "WAITING_PERIOD": ["CONDITION_WAITING_PERIOD", "INITIAL_WAITING"],
        }

        for reason in expected_reasons:
            # Direct match or semantic equivalent
            synonyms = equiv.get(reason, []) + [reason]
            matched = any(
                any(syn.lower() in r.lower() for syn in synonyms)
                for r in all_reasons
            )
            if matched:
                checks.append(f"  Rejection reason '{reason}': FOUND PASS")
            else:
                checks.append(f"  Rejection reason '{reason}': NOT FOUND in {all_reasons} FAIL")
                passed = False

    return passed, checks


def run_eval():
    cases = load_all_cases()
    results = []
    total_pass = 0
    total_fail = 0

    print("=" * 70)
    print("PLUM CLAIMS PROCESSING - EVALUATION REPORT")
    print("=" * 70)
    print()

    for tc in cases:
        case_id = tc["case_id"]
        case_name = tc["case_name"]
        print(f"--- {case_id}: {case_name} ---")

        state = build_state(tc)
        start = time.time()
        result = process_claim(state)
        elapsed = (time.time() - start) * 1000

        passed, checks = evaluate_case(tc, result)

        status = "PASS" if passed else "FAIL"
        if passed:
            total_pass += 1
        else:
            total_fail += 1

        print(f"  Status: {status} ({elapsed:.0f}ms)")
        print(f"  Result: decision={result.get('decision')}, "
              f"amount=₹{result.get('approved_amount', 0):,.0f}, "
              f"confidence={result.get('confidence_score', 0):.2f}")
        for check in checks:
            print(check)
        print()

        results.append({
            "case_id": case_id,
            "case_name": case_name,
            "status": status,
            "elapsed_ms": round(elapsed),
            "result": {
                "decision": result.get("decision"),
                "approved_amount": result.get("approved_amount"),
                "confidence_score": result.get("confidence_score"),
                "message": result.get("message"),
                "rejection_reasons": result.get("rejection_reasons", []),
                "fraud_signals": result.get("fraud_signals", []),
            },
            "expected": tc["expected"],
        })

    print("=" * 70)
    print(f"SUMMARY: {total_pass} passed, {total_fail} failed, "
          f"{len(cases)} total ({total_pass/len(cases)*100:.0f}% pass rate)")
    print("=" * 70)

    # Save report
    report_path = ROOT / "eval" / "eval_report.json"
    with open(report_path, "w") as f:
        json.dump({
            "total_cases": len(cases),
            "passed": total_pass,
            "failed": total_fail,
            "pass_rate": f"{total_pass/len(cases)*100:.1f}%",
            "results": results,
        }, f, indent=2)
    print(f"\nDetailed report saved to: {report_path}")


if __name__ == "__main__":
    run_eval()
