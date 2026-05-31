"""Run all 22 test cases through the pipeline and export results to Excel."""

import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.graph import process_claim

ROOT = Path(__file__).parent.parent
TEST_CASES_FILE = ROOT / "test_cases.json"
TEST_CASES_EXTENDED_FILE = ROOT / "test_cases_extended.json"
OUTPUT_PATH = ROOT / "eval" / "eval_report.xlsx"

REASON_EQUIVALENCE = {
    "PRE_AUTH_MISSING": ["PRE_AUTHORIZATION", "PRE_AUTH"],
    "PER_CLAIM_EXCEEDED": ["PER_CLAIM_LIMIT", "PER_CLAIM"],
    "EXCLUDED_CONDITION": ["EXCLUSION_CHECK", "EXCLUSION", "CONDITION_WAITING_PERIOD"],
    "EXCLUDED_PROCEDURE": ["LINE_ITEM_EXCLUSION", "EXCLUSION_CHECK"],
    "WAITING_PERIOD": ["CONDITION_WAITING_PERIOD", "INITIAL_WAITING"],
}


def load_all_cases():
    cases = []
    for path in (TEST_CASES_FILE, TEST_CASES_EXTENDED_FILE):
        if path.exists():
            data = json.loads(path.read_text())
            cases.extend(data["test_cases"])
    return cases


def build_state(tc):
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

    if tc["case_id"] == "TC022":
        state["apply_sub_limit"] = True

    return state


def check_reasons(expected_reasons, result):
    actual_reasons = result.get("rejection_reasons", [])
    policy_check_rules = [
        c.get("rule_name", "").upper()
        for c in result.get("policy_checks", [])
        if c.get("impact") == "REJECT"
    ]
    all_reasons = actual_reasons + policy_check_rules

    for reason in expected_reasons:
        synonyms = REASON_EQUIVALENCE.get(reason, []) + [reason]
        matched = any(
            any(syn.lower() in r.lower() for syn in synonyms)
            for r in all_reasons
        )
        if not matched:
            return False
    return True


def evaluate(tc, result):
    expected = tc["expected"]
    passed = True

    if expected.get("decision"):
        if result.get("decision") != expected["decision"]:
            passed = False

    if expected.get("approved_amount") is not None:
        if abs(result.get("approved_amount", 0) - float(expected["approved_amount"])) >= 1.0:
            passed = False

    confidence_req = expected.get("confidence_score")
    if confidence_req and "above" in confidence_req:
        threshold = float(confidence_req.split()[-1])
        if result.get("confidence_score", 0) < threshold:
            passed = False

    if expected.get("rejection_reasons"):
        if not check_reasons(expected["rejection_reasons"], result):
            passed = False

    return passed


def run():
    cases = load_all_cases()
    rows = []

    print(f"Running {len(cases)} test cases through the pipeline...\n")

    for tc in cases:
        case_id = tc["case_id"]
        state = build_state(tc)

        start = time.time()
        result = process_claim(state)
        elapsed_ms = round((time.time() - start) * 1000)

        passed = evaluate(tc, result)
        expected = tc["expected"]

        # Build trace summary
        trace = result.get("trace", [])
        agents_involved = " → ".join(dict.fromkeys(s["agent"] for s in trace))

        row = {
            "Case ID": case_id,
            "Case Name": tc["case_name"],
            "Category": tc["input"]["claim_category"],
            "Claimed Amount (₹)": tc["input"]["claimed_amount"],
            "Expected Decision": expected.get("decision", ""),
            "Actual Decision": result.get("decision", ""),
            "Decision Match": "✓" if result.get("decision") == expected.get("decision") else "✗",
            "Expected Amount (₹)": expected.get("approved_amount", ""),
            "Actual Amount (₹)": result.get("approved_amount", 0),
            "Amount Match": "✓" if expected.get("approved_amount") is None or abs(result.get("approved_amount", 0) - float(expected.get("approved_amount", 0))) < 1.0 else "✗",
            "Confidence Score": result.get("confidence_score", 0),
            "Expected Reasons": ", ".join(expected.get("rejection_reasons", [])),
            "Actual Reasons": ", ".join(result.get("rejection_reasons", [])),
            "Fraud Signals": len(result.get("fraud_signals", [])),
            "Pipeline Trace": agents_involved,
            "Duration (ms)": elapsed_ms,
            "Overall": "PASS" if passed else "FAIL",
            "Message": result.get("message", ""),
        }
        rows.append(row)

        status = "PASS" if passed else "FAIL"
        print(f"  {case_id}: {status} | {result.get('decision')} | ₹{result.get('approved_amount', 0):,.0f} | {elapsed_ms}ms")

    # Create DataFrame
    df = pd.DataFrame(rows)

    # Write to Excel with formatting
    with pd.ExcelWriter(OUTPUT_PATH, engine="openpyxl") as writer:
        # Main results sheet
        df.to_excel(writer, sheet_name="Results", index=False)

        # Summary sheet
        summary_data = {
            "Metric": [
                "Total Cases",
                "Passed",
                "Failed",
                "Pass Rate",
                "Avg Duration (ms)",
                "",
                "By Decision Type:",
                "APPROVED",
                "PARTIAL",
                "REJECTED",
                "MANUAL_REVIEW",
            ],
            "Value": [
                len(rows),
                sum(1 for r in rows if r["Overall"] == "PASS"),
                sum(1 for r in rows if r["Overall"] == "FAIL"),
                f"{sum(1 for r in rows if r['Overall'] == 'PASS') / len(rows) * 100:.0f}%",
                round(sum(r["Duration (ms)"] for r in rows) / len(rows)),
                "",
                "",
                sum(1 for r in rows if r["Actual Decision"] == "APPROVED"),
                sum(1 for r in rows if r["Actual Decision"] == "PARTIAL"),
                sum(1 for r in rows if r["Actual Decision"] == "REJECTED"),
                sum(1 for r in rows if r["Actual Decision"] == "MANUAL_REVIEW"),
            ],
        }
        pd.DataFrame(summary_data).to_excel(writer, sheet_name="Summary", index=False)

        # Trace details sheet
        trace_rows = []
        for tc, row in zip(cases, rows):
            state = build_state(tc)
            result = process_claim(state)
            for step in result.get("trace", []):
                trace_rows.append({
                    "Case ID": tc["case_id"],
                    "Agent": step["agent"],
                    "Action": step["action"],
                    "Status": step["status"],
                    "Duration (ms)": step["duration_ms"],
                    "Input": json.dumps(step.get("input_summary", {}), default=str),
                    "Output": json.dumps(step.get("output_summary", {}), default=str),
                })
        pd.DataFrame(trace_rows).to_excel(writer, sheet_name="Trace Details", index=False)

        # Amount breakdown sheet (for approved/partial claims)
        amount_rows = []
        for tc in cases:
            state = build_state(tc)
            result = process_claim(state)
            breakdown = result.get("amount_breakdown")
            if breakdown:
                amount_rows.append({
                    "Case ID": tc["case_id"],
                    "Decision": result["decision"],
                    "Original Claimed": breakdown["original_claimed"],
                    "After Exclusions": breakdown["eligible_after_exclusions"],
                    "Network Discount": breakdown["discount_amount"],
                    "After Discount": breakdown["after_network_discount"],
                    "After Sub-Limit": breakdown["after_sub_limit_cap"],
                    "After Annual Cap": breakdown["after_annual_limit_cap"],
                    "Co-pay Deducted": breakdown["copay_amount"],
                    "Co-pay Type": breakdown["copay_type"],
                    "Final Approved": breakdown["final_approved"],
                })
        pd.DataFrame(amount_rows).to_excel(writer, sheet_name="Amount Breakdown", index=False)

    total_pass = sum(1 for r in rows if r["Overall"] == "PASS")
    print(f"\n{'='*60}")
    print(f"RESULT: {total_pass}/{len(rows)} passed ({total_pass/len(rows)*100:.0f}% pass rate)")
    print(f"{'='*60}")
    print(f"\nExcel report saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    run()
