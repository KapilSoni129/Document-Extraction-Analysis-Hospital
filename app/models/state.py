from typing import TypedDict


class ClaimProcessingState(TypedDict, total=False):
    # Input
    claim_id: str
    member_id: str
    policy_id: str
    claim_category: str
    treatment_date: str
    submission_date: str
    claimed_amount: float
    hospital_name: str | None
    ytd_claims_amount: float
    claims_history: list[dict]
    documents: list[dict]
    simulate_component_failure: bool
    apply_sub_limit: bool

    # Intake
    member_info: dict | None
    policy_config: dict | None
    category_config: dict | None
    early_rejection: dict | None

    # Document verification
    verified_documents: list[dict]
    doc_errors: list[dict]

    # Extraction
    extracted_data: list[dict]

    # Cross-validation
    cross_validation_passed: bool
    validation_errors: list[dict]

    # Policy evaluation
    policy_checks: list[dict]
    eligible_amount: float | None
    amount_breakdown: dict | None
    fraud_signals: list[dict]

    # Decision
    decision: str | None
    approved_amount: float | None
    rejection_reasons: list[str]
    confidence_score: float
    message: str

    # Observability
    trace: list[dict]
    component_failures: list[dict]
