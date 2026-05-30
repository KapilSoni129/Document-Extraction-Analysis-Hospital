"""Policy evaluator agent: applies all policy rules to determine eligibility and amount."""

import time
from datetime import UTC, datetime

from app.config import (
    get_exclusions,
    get_fraud_thresholds,
    get_waiting_period_days,
    is_network_hospital,
    load_pipeline_config,
)
from app.logging_config import get_logger
from app.models.state import ClaimProcessingState
from app.utils.date_utils import is_within_waiting_period
from app.utils.financial import calculate_approved_amount

logger = get_logger("agent.policy_evaluator")


def policy_evaluator(state: ClaimProcessingState) -> dict:
    trace_steps = []
    policy_checks = []
    fraud_signals = []
    start = time.time()

    category_config = state["category_config"]
    policy_config = state["policy_config"]
    member_info = state["member_info"]
    claimed_amount = state["claimed_amount"]
    claim_category = state["claim_category"]
    treatment_date = state["treatment_date"]
    ytd = state.get("ytd_claims_amount", 0.0)
    claims_history = state.get("claims_history", [])
    extracted_data = state.get("extracted_data", [])

    # Determine hospital name from state or extracted data
    hospital_name = state.get("hospital_name")
    if not hospital_name:
        for doc in extracted_data:
            if doc.get("hospital_name"):
                hospital_name = doc["hospital_name"]
                break

    # Determine diagnosis from extracted data
    diagnosis = None
    for doc in extracted_data:
        if doc.get("diagnosis"):
            diagnosis = doc["diagnosis"]
            break

    # Collect line items from bills
    line_items = []
    for doc in extracted_data:
        if doc.get("line_items"):
            line_items.extend(doc["line_items"])

    # --- Check 1: Condition-specific waiting period ---
    if diagnosis:
        waiting_days = get_waiting_period_days(diagnosis)
        if waiting_days:
            join_date = member_info.get("join_date")
            if join_date and is_within_waiting_period(join_date, treatment_date, waiting_days):
                from app.utils.date_utils import eligibility_date

                eligible_from = eligibility_date(join_date, waiting_days)
                policy_checks.append(
                    {
                        "rule_name": "condition_waiting_period",
                        "passed": False,
                        "details": f"Diagnosis '{diagnosis}' has a {waiting_days}-day waiting period. "
                        f"Member joined {join_date}. Eligible from {eligible_from.isoformat()}.",
                        "impact": "REJECT",
                    }
                )
                trace_steps.append(
                    _step(
                        "check_condition_waiting_period",
                        start,
                        {"diagnosis": diagnosis, "waiting_days": waiting_days},
                        {"passed": False, "eligible_from": eligible_from.isoformat()},
                    )
                )
            else:
                policy_checks.append(
                    {
                        "rule_name": "condition_waiting_period",
                        "passed": True,
                        "details": f"Waiting period for '{diagnosis}' ({waiting_days} days) has elapsed.",
                    }
                )
                trace_steps.append(
                    _step("check_condition_waiting_period", start, {"diagnosis": diagnosis}, {"passed": True})
                )

    # --- Check 2: Exclusions ---
    exclusions = get_exclusions()
    all_exclusions = exclusions.get("conditions", [])
    if claim_category == "DENTAL":
        all_exclusions += exclusions.get("dental_exclusions", [])
    elif claim_category == "VISION":
        all_exclusions += exclusions.get("vision_exclusions", [])

    excluded = False
    if diagnosis:
        for exc in all_exclusions:
            if _matches_exclusion(diagnosis, exc):
                excluded = True
                policy_checks.append(
                    {
                        "rule_name": "exclusion_check",
                        "passed": False,
                        "details": f"Diagnosis/treatment '{diagnosis}' matches exclusion: '{exc}'.",
                        "impact": "REJECT",
                    }
                )
                trace_steps.append(
                    _step(
                        "check_exclusions",
                        start,
                        {"diagnosis": diagnosis},
                        {"excluded": True, "matched_exclusion": exc},
                    )
                )
                break

    if not excluded:
        policy_checks.append(
            {
                "rule_name": "exclusion_check",
                "passed": True,
                "details": "No exclusions matched.",
            }
        )
        trace_steps.append(_step("check_exclusions", start, {}, {"excluded": False}))

    # --- Check 3: Pre-authorization ---
    if claim_category == "DIAGNOSTIC":
        pre_auth_threshold = category_config.get("pre_auth_threshold", float("inf"))
        high_value_tests = category_config.get("high_value_tests_requiring_pre_auth", [])
        needs_pre_auth = False

        if claimed_amount > pre_auth_threshold:
            # Check if any high-value test is in the claim
            for item in line_items:
                for test in high_value_tests:
                    if test.lower() in item.get("description", "").lower():
                        needs_pre_auth = True
                        break

        if needs_pre_auth:
            policy_checks.append(
                {
                    "rule_name": "pre_authorization",
                    "passed": False,
                    "details": f"Pre-authorization required for high-value diagnostic test "
                    f"(amount ₹{claimed_amount:,.0f} exceeds threshold ₹{pre_auth_threshold:,.0f}). "
                    f"Please obtain pre-authorization and resubmit.",
                    "impact": "REJECT",
                }
            )
            trace_steps.append(
                _step(
                    "check_pre_auth",
                    start,
                    {"amount": claimed_amount, "threshold": pre_auth_threshold},
                    {"required": True, "obtained": False},
                )
            )
        else:
            policy_checks.append(
                {
                    "rule_name": "pre_authorization",
                    "passed": True,
                    "details": "Pre-authorization not required or threshold not exceeded.",
                }
            )

    # --- Check 4: Line-item exclusions (dental/vision) ---
    excluded_descriptions = []
    if claim_category == "DENTAL" and line_items:
        excluded_procedures = category_config.get("excluded_procedures", [])
        for item in line_items:
            for proc in excluded_procedures:
                if proc.lower() in item["description"].lower():
                    excluded_descriptions.append(item["description"])
                    policy_checks.append(
                        {
                            "rule_name": "line_item_exclusion",
                            "passed": False,
                            "details": f"Line item '{item['description']}' (₹{item['amount']:,.0f}) "
                            f"is excluded: matches '{proc}'.",
                            "impact": "PARTIAL",
                        }
                    )
    elif claim_category == "VISION" and line_items:
        excluded_items = category_config.get("excluded_items", [])
        for item in line_items:
            for exc in excluded_items:
                if exc.lower() in item["description"].lower():
                    excluded_descriptions.append(item["description"])
                    policy_checks.append(
                        {
                            "rule_name": "line_item_exclusion",
                            "passed": False,
                            "details": f"Line item '{item['description']}' is excluded: '{exc}'.",
                            "impact": "PARTIAL",
                        }
                    )
        # If ALL line items are excluded, it's a full rejection
        if excluded_descriptions and len(excluded_descriptions) == len(line_items):
            for check in policy_checks:
                if check["rule_name"] == "line_item_exclusion":
                    check["impact"] = "REJECT"

    # --- Check 5: Per-claim limit (skip if exclusions already handle the amount) ---
    hard_rejects_so_far = [c for c in policy_checks if c.get("impact") == "REJECT"]
    partial_exclusions = [c for c in policy_checks if c.get("impact") == "PARTIAL"]
    if not hard_rejects_so_far and not partial_exclusions:
        per_claim_limit = policy_config["coverage"]["per_claim_limit"]
        cat_sub_limit = category_config.get("sub_limit", per_claim_limit)
        effective_limit = max(per_claim_limit, cat_sub_limit)
        if claimed_amount > effective_limit:
            policy_checks.append(
                {
                    "rule_name": "per_claim_limit",
                    "passed": False,
                    "details": f"Claimed amount ₹{claimed_amount:,.0f} exceeds the per-claim limit of ₹{effective_limit:,.0f}.",
                    "impact": "REJECT",
                }
            )
            trace_steps.append(
                _step(
                    "check_per_claim_limit",
                    start,
                    {"claimed": claimed_amount, "limit": effective_limit},
                    {"passed": False},
                )
            )

    # --- Check 6: Fraud signals ---
    thresholds = get_fraud_thresholds()

    # Same-day claims
    same_day_count = sum(1 for c in claims_history if str(c.get("date", "")) == treatment_date)
    if same_day_count >= thresholds["same_day_claims_limit"]:
        fraud_signals.append(
            {
                "signal": "SAME_DAY_CLAIMS",
                "details": f"{same_day_count + 1} claims on {treatment_date} "
                f"(limit: {thresholds['same_day_claims_limit']})",
                "count": same_day_count + 1,
                "threshold": thresholds["same_day_claims_limit"],
            }
        )
        trace_steps.append(
            _step("check_fraud_same_day", start, {"same_day_count": same_day_count + 1}, {"flagged": True})
        )

    # Monthly claims
    treatment_month = treatment_date[:7]
    monthly_count = sum(1 for c in claims_history if str(c.get("date", "")).startswith(treatment_month))
    if monthly_count >= thresholds["monthly_claims_limit"]:
        fraud_signals.append(
            {
                "signal": "MONTHLY_CLAIMS_LIMIT",
                "details": f"{monthly_count + 1} claims in {treatment_month} "
                f"(limit: {thresholds['monthly_claims_limit']})",
                "count": monthly_count + 1,
                "threshold": thresholds["monthly_claims_limit"],
            }
        )
        trace_steps.append(_step("check_fraud_monthly", start, {"monthly_count": monthly_count + 1}, {"flagged": True}))

    # --- Check 6: Financial calculation ---
    # Only calculate if no hard-reject reasons found
    hard_rejects = [c for c in policy_checks if c.get("impact") == "REJECT"]
    if hard_rejects:
        logger.info("[%s] Policy rejected: %s", state.get("claim_id"), [c["rule_name"] for c in hard_rejects])
    if fraud_signals:
        logger.warning("[%s] Fraud signals: %s", state.get("claim_id"), [f["signal"] for f in fraud_signals])
    if not hard_rejects and not fraud_signals:
        is_network = is_network_hospital(hospital_name or "")
        # Determine if branded drugs
        is_branded = False
        if claim_category == "PHARMACY":
            for doc in extracted_data:
                for item in doc.get("line_items", []):
                    if "branded" in item.get("description", "").lower():
                        is_branded = True
                        break

        breakdown = calculate_approved_amount(
            claimed_amount=claimed_amount,
            category_config=category_config or {},
            is_network=is_network,
            ytd_claims_amount=ytd,
            annual_opd_limit=policy_config["coverage"]["annual_opd_limit"],
            line_items=line_items if excluded_descriptions else None,
            excluded_descriptions=excluded_descriptions if excluded_descriptions else None,
            is_branded_drug=is_branded,
            apply_sub_limit=state.get("apply_sub_limit", False),
        )

        trace_steps.append(
            _step(
                "calculate_amount",
                start,
                {"claimed": claimed_amount, "is_network": is_network, "is_branded": is_branded},
                {
                    "final_approved": breakdown.final_approved,
                    "discount": breakdown.discount_amount,
                    "copay": breakdown.copay_amount,
                },
            )
        )

        return {
            "policy_checks": policy_checks,
            "eligible_amount": breakdown.eligible_after_exclusions,
            "amount_breakdown": {
                "original_claimed": breakdown.original_claimed,
                "eligible_after_exclusions": breakdown.eligible_after_exclusions,
                "after_network_discount": breakdown.after_network_discount,
                "discount_amount": breakdown.discount_amount,
                "after_sub_limit_cap": breakdown.after_sub_limit_cap,
                "sub_limit_applied": breakdown.sub_limit_applied,
                "after_annual_limit_cap": breakdown.after_annual_limit_cap,
                "annual_limit_remaining": breakdown.annual_limit_remaining,
                "copay_amount": breakdown.copay_amount,
                "copay_type": breakdown.copay_type,
                "final_approved": breakdown.final_approved,
            },
            "fraud_signals": fraud_signals,
            "trace": state.get("trace", []) + trace_steps,
        }

    return {
        "policy_checks": policy_checks,
        "eligible_amount": None,
        "amount_breakdown": None,
        "fraud_signals": fraud_signals,
        "trace": state.get("trace", []) + trace_steps,
    }


def _matches_exclusion(diagnosis: str, exclusion: str) -> bool:
    """Check if a diagnosis matches an exclusion entry.
    Uses the most specific keyword from the exclusion as primary match."""
    config = load_pipeline_config()["policy_matching"]
    diag_lower = diagnosis.lower()
    exc_lower = exclusion.lower()
    generic_words = set(config["generic_words_excluded"])
    min_len = config["min_keyword_length"]
    keywords = [w for w in exc_lower.split() if len(w) > min_len and w not in generic_words]
    if not keywords:
        return exc_lower in diag_lower
    return any(kw in diag_lower for kw in keywords)


def _step(action, ref_time, input_summary, output_summary):
    return {
        "agent": "policy_evaluator",
        "timestamp": datetime.now(UTC).isoformat(),
        "action": action,
        "status": "SUCCESS",
        "duration_ms": int((time.time() - ref_time) * 1000),
        "input_summary": input_summary,
        "output_summary": output_summary,
    }
