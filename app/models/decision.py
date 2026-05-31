from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class TraceStep(BaseModel):
    agent: str
    timestamp: datetime
    action: str
    status: Literal["SUCCESS", "FAILED", "SKIPPED"]
    duration_ms: int
    input_summary: dict = {}
    output_summary: dict = {}
    details: str | None = None


class AmountBreakdown(BaseModel):
    original_claimed: float
    eligible_after_exclusions: float
    after_network_discount: float
    discount_amount: float
    after_sub_limit_cap: float
    sub_limit_applied: float | None = None
    after_annual_limit_cap: float
    annual_limit_remaining: float | None = None
    copay_amount: float
    copay_type: str
    final_approved: float


class PolicyCheck(BaseModel):
    rule_name: str
    passed: bool
    details: str
    impact: str | None = None


class ClaimDecision(BaseModel):
    claim_id: str
    decision: Literal["APPROVED", "PARTIAL", "REJECTED", "MANUAL_REVIEW"]
    approved_amount: float | None = None
    confidence_score: float
    rejection_reasons: list[str] = []
    user_message: str
    amount_breakdown: AmountBreakdown | None = None
    policy_checks: list[PolicyCheck] = []
    fraud_signals: list[dict] = []
    document_verifications: list[dict] = []
    extracted_data: list[dict] = []
    trace: list[TraceStep] = []
    component_failures: list[dict] = []
    processing_time_ms: int = 0
