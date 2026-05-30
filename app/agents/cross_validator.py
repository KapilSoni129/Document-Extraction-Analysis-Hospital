"""Cross-validator agent: checks consistency across extracted document data."""

import time
from datetime import UTC, datetime
from difflib import SequenceMatcher

from app.config import load_pipeline_config
from app.logging_config import get_logger
from app.models.state import ClaimProcessingState

logger = get_logger("agent.cross_validator")


def cross_validator(state: ClaimProcessingState) -> dict:
    start = time.time()
    trace_steps = []
    validation_errors = []

    member_info = state.get("member_info", {})
    extracted_data = state.get("extracted_data", [])
    treatment_date = state.get("treatment_date")

    if not extracted_data:
        trace_steps.append(_step("skip_no_data", start, {}, {"reason": "no extracted data"}))
        return {
            "cross_validation_passed": True,
            "validation_errors": [],
            "trace": state.get("trace", []) + trace_steps,
        }

    # --- Check 1: Patient name consistency across documents ---
    patient_names = []
    for doc in extracted_data:
        name = doc.get("patient_name")
        if name:
            patient_names.append(name)

    config = load_pipeline_config()["cross_validation"]

    if len(patient_names) >= 2:
        base_name = patient_names[0]
        for _i, name in enumerate(patient_names[1:], 1):
            ratio = SequenceMatcher(None, base_name.lower(), name.lower()).ratio()
            if ratio < config["patient_name_similarity_threshold"]:
                validation_errors.append(
                    {
                        "type": "PATIENT_NAME_MISMATCH",
                        "details": f"Document names don't match: '{base_name}' vs '{name}' (similarity: {ratio:.0%})",
                        "severity": "HIGH",
                    }
                )
                trace_steps.append(
                    _step(
                        "name_mismatch", start, {"name_1": base_name, "name_2": name}, {"ratio": ratio, "passed": False}
                    )
                )

    # --- Check 2: Patient name matches member ---
    member_name = member_info.get("name", "")
    if patient_names and member_name:
        best_ratio = max(SequenceMatcher(None, member_name.lower(), pn.lower()).ratio() for pn in patient_names)
        if best_ratio < config["member_name_similarity_threshold"]:
            validation_errors.append(
                {
                    "type": "MEMBER_NAME_MISMATCH",
                    "details": f"Document patient '{patient_names[0]}' doesn't match member '{member_name}' (similarity: {best_ratio:.0%})",
                    "severity": "MEDIUM",
                }
            )
            trace_steps.append(
                _step(
                    "member_name_check",
                    start,
                    {"member": member_name, "document": patient_names[0]},
                    {"ratio": best_ratio, "passed": False},
                )
            )
        else:
            trace_steps.append(
                _step(
                    "member_name_check",
                    start,
                    {"member": member_name, "document": patient_names[0]},
                    {"ratio": best_ratio, "passed": True},
                )
            )

    # --- Check 3: Date consistency ---
    doc_dates = []
    for doc in extracted_data:
        d = doc.get("date")
        if d:
            doc_dates.append(d)

    if treatment_date and doc_dates:
        mismatches = [d for d in doc_dates if d != treatment_date]
        if mismatches:
            validation_errors.append(
                {
                    "type": "DATE_MISMATCH",
                    "details": f"Document date(s) {mismatches} don't match treatment date {treatment_date}",
                    "severity": "LOW",
                }
            )
            trace_steps.append(
                _step(
                    "date_check", start, {"treatment_date": treatment_date, "doc_dates": doc_dates}, {"passed": False}
                )
            )

    passed = len([e for e in validation_errors if e["severity"] == "HIGH"]) == 0
    if not passed:
        logger.warning(
            "[%s] Cross-validation FAILED: %s",
            state.get("claim_id"),
            [e["type"] for e in validation_errors if e["severity"] == "HIGH"],
        )
    else:
        logger.debug("[%s] Cross-validation passed", state.get("claim_id"))

    if not trace_steps:
        trace_steps.append(
            _step(
                "cross_validation_complete",
                start,
                {"docs_checked": len(extracted_data)},
                {"passed": passed, "errors": len(validation_errors)},
            )
        )

    return {
        "cross_validation_passed": passed,
        "validation_errors": validation_errors,
        "trace": state.get("trace", []) + trace_steps,
    }


def _step(action, ref_time, input_summary, output_summary):
    return {
        "agent": "cross_validator",
        "timestamp": datetime.now(UTC).isoformat(),
        "action": action,
        "status": "SUCCESS",
        "duration_ms": int((time.time() - ref_time) * 1000),
        "input_summary": input_summary,
        "output_summary": output_summary,
    }
