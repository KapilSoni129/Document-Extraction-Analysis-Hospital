"""Decision maker agent: synthesizes final decision from all prior pipeline state."""

import time
from datetime import UTC, datetime

from app.config import load_pipeline_config
from app.logging_config import get_logger
from app.models.state import ClaimProcessingState

logger = get_logger("agent.decision_maker")


def decision_maker(state: ClaimProcessingState) -> dict:
    start = time.time()
    trace_steps = []

    early_rejection = state.get("early_rejection")
    policy_checks = state.get("policy_checks", [])
    fraud_signals = state.get("fraud_signals", [])
    amount_breakdown = state.get("amount_breakdown")
    component_failures = state.get("component_failures", [])
    claimed_amount = state["claimed_amount"]

    # Start with full confidence, reduce based on issues
    decision_config = load_pipeline_config()["decision"]
    confidence = decision_config["initial_confidence"]

    # --- Early rejection from intake ---
    if early_rejection:
        decision = "REJECTED"
        reason_code = early_rejection["reason_code"]
        message = early_rejection["message"]
        trace_steps.append(_step("early_rejection", start, {"reason_code": reason_code}, {"decision": decision}))
        return _build_result(
            decision=decision,
            confidence=confidence,
            approved_amount=0,
            message=message,
            rejection_reasons=[reason_code],
            trace=state.get("trace", []) + trace_steps,
            amount_breakdown=None,
            fraud_signals=fraud_signals,
            policy_checks=policy_checks,
            component_failures=component_failures,
        )

    # --- Document errors (wrong type, unreadable, missing) ---
    # These are NOT claim decisions — they're requests for member action.
    # The system stops before making a claim decision (per assignment requirement).
    doc_errors = state.get("doc_errors", [])
    if doc_errors:
        messages = [e["message"] for e in doc_errors]
        trace_steps.append(
            _step("document_error", start, {"errors": len(doc_errors)}, {"types": [e["type"] for e in doc_errors]})
        )
        return _build_result(
            decision=None,
            confidence=confidence,
            approved_amount=0,
            message=" | ".join(messages),
            rejection_reasons=[e["type"] for e in doc_errors],
            trace=state.get("trace", []) + trace_steps,
            amount_breakdown=None,
            fraud_signals=fraud_signals,
            policy_checks=policy_checks,
            component_failures=component_failures,
        )

    # --- Cross-validation failures (document inconsistency) ---
    # Not a claim decision — member needs to clarify/resubmit.
    validation_errors = state.get("validation_errors", [])
    if not state.get("cross_validation_passed", True) and validation_errors:
        messages = [e["details"] for e in validation_errors if e["severity"] == "HIGH"]
        trace_steps.append(
            _step(
                "cross_validation_failure",
                start,
                {"errors": len(validation_errors)},
                {"types": [e["type"] for e in validation_errors]},
            )
        )
        return _build_result(
            decision=None,
            confidence=confidence,
            approved_amount=0,
            message="Document inconsistency detected: "
            + " | ".join(messages)
            + " Please verify the documents belong to the same patient and resubmit.",
            rejection_reasons=[e["type"] for e in validation_errors],
            trace=state.get("trace", []) + trace_steps,
            amount_breakdown=None,
            fraud_signals=fraud_signals,
            policy_checks=policy_checks,
            component_failures=component_failures,
        )

    # --- Hard rejects from policy checks ---
    hard_rejects = [c for c in policy_checks if c.get("impact") == "REJECT"]
    if hard_rejects:
        decision = "REJECTED"
        rejection_reasons = [c["rule_name"].upper() for c in hard_rejects]
        messages = [c["details"] for c in hard_rejects]
        trace_steps.append(
            _step(
                "policy_rejection",
                start,
                {"rejects": len(hard_rejects)},
                {"decision": decision, "reasons": rejection_reasons},
            )
        )
        return _build_result(
            decision=decision,
            confidence=confidence,
            approved_amount=0,
            message=" | ".join(messages),
            rejection_reasons=rejection_reasons,
            trace=state.get("trace", []) + trace_steps,
            amount_breakdown=None,
            fraud_signals=fraud_signals,
            policy_checks=policy_checks,
            component_failures=component_failures,
        )

    # --- Fraud signals → manual review ---
    if fraud_signals:
        decision = "MANUAL_REVIEW"
        confidence -= decision_config["fraud_signal_penalty"] * len(fraud_signals)
        signals_summary = "; ".join(f["signal"] + ": " + f["details"] for f in fraud_signals)
        message = f"Fraud signals detected — routing to manual review. Signals: {signals_summary}"
        approved = amount_breakdown["final_approved"] if amount_breakdown else 0
        trace_steps.append(_step("fraud_review", start, {"signals": len(fraud_signals)}, {"decision": decision}))
        return _build_result(
            decision=decision,
            confidence=max(decision_config["minimum_confidence"], confidence),
            approved_amount=approved,
            message=message,
            rejection_reasons=[],
            trace=state.get("trace", []) + trace_steps,
            amount_breakdown=amount_breakdown,
            fraud_signals=fraud_signals,
            policy_checks=policy_checks,
            component_failures=component_failures,
        )

    # --- Partial vs Approved ---
    # PARTIAL only when: line-item exclusions, sub-limit cap, or annual limit cap reduced the amount
    # Normal co-pay and network discount reductions are still APPROVED
    partial_checks = [c for c in policy_checks if c.get("impact") == "PARTIAL"]
    approved = amount_breakdown["final_approved"] if amount_breakdown else 0

    has_structural_reduction = (
        partial_checks
        or (amount_breakdown and amount_breakdown.get("annual_limit_remaining") is not None)
        or (amount_breakdown and amount_breakdown.get("sub_limit_applied") is not None)
    )

    if has_structural_reduction:
        decision = "PARTIAL"
        reasons = [c["details"] for c in partial_checks]
        if amount_breakdown and amount_breakdown.get("annual_limit_remaining") is not None:
            reasons.append(f"Annual limit capped amount to ₹{amount_breakdown['after_annual_limit_cap']:,.0f}")
        if amount_breakdown and amount_breakdown.get("sub_limit_applied") is not None:
            reasons.append(f"Sub-limit capped amount to ₹{amount_breakdown['after_sub_limit_cap']:,.0f}")
        message = f"Partial approval: ₹{approved:,.0f} of ₹{claimed_amount:,.0f}. " + " | ".join(reasons)
    else:
        decision = "APPROVED"
        message = f"Claim approved for ₹{approved:,.0f}."
        if amount_breakdown and amount_breakdown.get("discount_amount", 0) > 0:
            message += f" Network discount ₹{amount_breakdown['discount_amount']:,.0f} applied."
        if amount_breakdown and amount_breakdown.get("copay_amount", 0) > 0:
            message += f" Co-pay ₹{amount_breakdown['copay_amount']:,.0f} deducted."

    # --- Component failure penalty ---
    if component_failures:
        confidence -= decision_config["component_failure_penalty"] * len(component_failures)
        message += " Note: some components failed during processing — manual review recommended."

    logger.info(
        "[%s] Final decision: %s | approved=%.0f | confidence=%.2f",
        state.get("claim_id"),
        decision,
        approved,
        max(decision_config["minimum_confidence"], confidence),
    )

    trace_steps.append(
        _step(
            "final_decision",
            start,
            {"decision": decision, "approved": approved},
            {"confidence": max(decision_config["minimum_confidence"], confidence)},
        )
    )

    return _build_result(
        decision=decision,
        confidence=max(decision_config["minimum_confidence"], confidence),
        approved_amount=approved,
        message=message,
        rejection_reasons=[],
        trace=state.get("trace", []) + trace_steps,
        amount_breakdown=amount_breakdown,
        fraud_signals=fraud_signals,
        policy_checks=policy_checks,
        component_failures=component_failures,
    )


def _build_result(
    *,
    decision,
    confidence,
    approved_amount,
    message,
    rejection_reasons,
    trace,
    amount_breakdown,
    fraud_signals,
    policy_checks,
    component_failures,
):
    return {
        "decision": decision,
        "confidence_score": round(confidence, 2),
        "approved_amount": approved_amount,
        "message": message,
        "rejection_reasons": rejection_reasons,
        "amount_breakdown": amount_breakdown,
        "fraud_signals": fraud_signals,
        "policy_checks": policy_checks,
        "component_failures": component_failures,
        "trace": trace,
    }


def _step(action, ref_time, input_summary, output_summary):
    return {
        "agent": "decision_maker",
        "timestamp": datetime.now(UTC).isoformat(),
        "action": action,
        "status": "SUCCESS",
        "duration_ms": int((time.time() - ref_time) * 1000),
        "input_summary": input_summary,
        "output_summary": output_summary,
    }
