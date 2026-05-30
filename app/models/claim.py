from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ClaimHistoryItem(BaseModel):
    claim_id: str
    date: date
    amount: float
    provider: str | None = None
    status: str | None = None


class DocumentInput(BaseModel):
    file_name: str
    file_id: str | None = None
    actual_type: str | None = None
    quality: str | None = None
    content: dict | None = None


class ClaimRequest(BaseModel):
    member_id: str
    policy_id: str = "PLUM_GHI_2024"
    claim_category: Literal["CONSULTATION", "DIAGNOSTIC", "PHARMACY", "DENTAL", "VISION", "ALTERNATIVE_MEDICINE"]
    treatment_date: date
    claimed_amount: float = Field(gt=0)
    hospital_name: str | None = None
    ytd_claims_amount: float = 0.0
    claims_history: list[ClaimHistoryItem] = []
    submission_date: date | None = None
    documents: list[DocumentInput] = []
    simulate_component_failure: bool = False


class AmountBreakdownResponse(BaseModel):
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


class PolicyCheckResponse(BaseModel):
    rule_name: str
    passed: bool
    details: str
    impact: str | None = None


class TraceStepResponse(BaseModel):
    agent: str
    timestamp: str
    action: str
    status: str
    duration_ms: int
    input_summary: dict = {}
    output_summary: dict = {}


class ClaimResponse(BaseModel):
    claim_id: str
    decision: Literal["APPROVED", "PARTIAL", "REJECTED", "MANUAL_REVIEW"] | None = None
    approved_amount: float = 0
    confidence_score: float
    message: str
    rejection_reasons: list[str] = []
    requires_action: bool = False
    amount_breakdown: AmountBreakdownResponse | None = None
    policy_checks: list[PolicyCheckResponse] = []
    fraud_signals: list[dict] = []
    trace: list[TraceStepResponse] = []
    component_failures: list[dict] = []
    processed_at: datetime | None = None
