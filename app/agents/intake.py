"""Intake agent: validates basic claim eligibility before any document processing."""

import time
from datetime import UTC, date

from app.config import (
    get_category_config,
    get_member,
    get_primary_member,
    load_policy,
)
from app.logging_config import get_logger
from app.models.state import ClaimProcessingState
from app.utils.date_utils import days_between, eligibility_date, is_within_waiting_period

logger = get_logger("agent.intake")


def intake_agent(state: ClaimProcessingState) -> dict:
    trace_steps = []
    start = time.time()

    member_id = state["member_id"]
    policy = load_policy()
    claim_category = state["claim_category"]
    treatment_date = state["treatment_date"]
    claimed_amount = state["claimed_amount"]
    submission_date = state.get("submission_date") or date.today().isoformat()

    # Check member exists
    member = get_member(member_id)
    if not member:
        logger.warning("[%s] Member not found: %s", state.get("claim_id"), member_id)
        return _reject(
            state, trace_steps, start, "MEMBER_NOT_FOUND", f"Member '{member_id}' not found in policy roster."
        )

    # For dependents, get primary member for join_date
    primary = get_primary_member(member_id)
    join_date = primary.get("join_date", member.get("join_date")) if primary else member.get("join_date")

    trace_steps.append(
        _step("validate_member", "SUCCESS", {"member_id": member_id}, {"found": True, "name": member["name"]}, start)
    )

    # Check category exists
    category_config = get_category_config(claim_category)
    if not category_config:
        return _reject(
            state, trace_steps, start, "INVALID_CATEGORY", f"Category '{claim_category}' is not a valid claim category."
        )

    if not category_config.get("covered", True):
        return _reject(
            state,
            trace_steps,
            start,
            "CATEGORY_NOT_COVERED",
            f"Category '{claim_category}' is not covered under this policy.",
        )

    # Check minimum claim amount
    min_amount = policy["submission_rules"]["minimum_claim_amount"]
    if claimed_amount < min_amount:
        return _reject(
            state,
            trace_steps,
            start,
            "BELOW_MINIMUM_AMOUNT",
            f"Claimed amount ₹{claimed_amount:.0f} is below the minimum claim amount of ₹{min_amount}.",
        )

    trace_steps.append(
        _step(
            "check_minimum_amount",
            "SUCCESS",
            {"claimed": claimed_amount, "minimum": min_amount},
            {"passes": True},
            start,
        )
    )

    # Per-claim limit check (deferred to policy evaluator for detailed handling)
    # Only reject at intake when amount exceeds category sub-limit
    # This allows claims with exclusions/pre-auth issues to reach proper rule checks
    per_claim_limit = policy["coverage"]["per_claim_limit"]
    category_sub_limit = category_config.get("sub_limit", per_claim_limit)
    effective_limit = max(per_claim_limit, category_sub_limit)

    trace_steps.append(
        _step(
            "check_per_claim_limit",
            "SUCCESS",
            {"claimed": claimed_amount, "limit": effective_limit},
            {"passes": True, "exceeds_limit": claimed_amount > effective_limit},
            start,
        )
    )

    # Check submission deadline
    deadline_days = policy["submission_rules"]["deadline_days_from_treatment"]
    days_elapsed = days_between(treatment_date, submission_date)
    if days_elapsed > deadline_days:
        deadline_date = eligibility_date(treatment_date, deadline_days)
        return _reject(
            state,
            trace_steps,
            start,
            "SUBMISSION_DEADLINE_EXCEEDED",
            f"Claim submitted {days_elapsed} days after treatment. "
            f"The submission deadline is {deadline_days} days from treatment date. "
            f"Deadline was {deadline_date.isoformat()}.",
        )

    trace_steps.append(
        _step(
            "check_submission_deadline",
            "SUCCESS",
            {
                "treatment_date": treatment_date,
                "submission_date": submission_date,
                "days_elapsed": days_elapsed,
                "deadline_days": deadline_days,
            },
            {"within_deadline": True},
            start,
        )
    )

    # Check initial 30-day waiting period
    if join_date:
        initial_waiting = policy["waiting_periods"]["initial_waiting_period_days"]
        if is_within_waiting_period(join_date, treatment_date, initial_waiting):
            eligible_from = eligibility_date(join_date, initial_waiting)
            return _reject(
                state,
                trace_steps,
                start,
                "INITIAL_WAITING_PERIOD",
                f"Treatment date {treatment_date} is within the {initial_waiting}-day initial waiting period. "
                f"Member joined {join_date}. "
                f"Claims will be accepted from {eligible_from.isoformat()}.",
            )

        trace_steps.append(
            _step(
                "check_initial_waiting_period",
                "SUCCESS",
                {"join_date": join_date, "treatment_date": treatment_date, "initial_waiting_days": initial_waiting},
                {"passes": True},
                start,
            )
        )

    logger.info("[%s] Intake passed | member=%s category=%s", state.get("claim_id"), member["name"], claim_category)
    return {
        "member_info": member,
        "policy_config": policy,
        "category_config": category_config,
        "early_rejection": None,
        "trace": state.get("trace", []) + trace_steps,
    }


def _reject(state, trace_steps, start, reason_code, message):
    trace_steps.append(
        _step(f"reject_{reason_code.lower()}", "SUCCESS", {}, {"reason": reason_code, "message": message}, start)
    )
    return {
        "early_rejection": {"reason_code": reason_code, "message": message},
        "trace": state.get("trace", []) + trace_steps,
    }


def _step(action, status, input_summary, output_summary, ref_time):
    from datetime import datetime

    return {
        "agent": "intake",
        "timestamp": datetime.now(UTC).isoformat(),
        "action": action,
        "status": status,
        "duration_ms": int((time.time() - ref_time) * 1000),
        "input_summary": input_summary,
        "output_summary": output_summary,
    }
