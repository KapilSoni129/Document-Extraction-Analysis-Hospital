"""FastAPI entry point for claims processing API."""

import contextlib
import os
import tempfile
from datetime import UTC, datetime

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.agents.graph import async_process_claim
from app.config import load_policy
from app.logging_config import get_logger, setup_logging
from app.models.claim import ClaimRequest, ClaimResponse
from app.services.storage import get_claim, get_decision, list_claims, save_claim, save_decision

setup_logging()
logger = get_logger("api")

app = FastAPI(title="Plum Claims Processing API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health_check():
    from app.services.gemini import is_available as gemini_available

    return {
        "status": "ok",
        "version": "2.0.0",
        "gemini_available": gemini_available(),
    }


@app.get("/api/members")
def list_members():
    policy = load_policy()
    members = policy["members"]
    return {"members": [{"id": m["member_id"], "name": m["name"], "type": m["type"]} for m in members]}


@app.get("/api/policy/categories")
def list_categories():
    policy = load_policy()
    categories = policy["opd_categories"]
    return {
        "categories": [
            {"id": k.upper(), "name": k.replace("_", " ").title(), "covered": v.get("covered", True)}
            for k, v in categories.items()
        ]
    }


@app.post("/api/claims/process", response_model=ClaimResponse)
async def process_claim_endpoint(
    member_id: str = Form(...),
    claim_category: str = Form(...),
    treatment_date: str = Form(...),
    claimed_amount: float = Form(...),
    hospital_name: str | None = Form(None),
    ytd_claims_amount: float = Form(0.0),
    submission_date: str | None = Form(None),
    documents: list[UploadFile] = File(default=[]),
):
    doc_list = []
    for doc in documents:
        suffix = os.path.splitext(doc.filename or "")[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await doc.read()
            tmp.write(content)
            doc_list.append(
                {
                    "file_name": doc.filename,
                    "file_path": tmp.name,
                }
            )

    logger.info(
        "POST /api/claims/process | member=%s category=%s amount=%.0f docs=%d",
        member_id,
        claim_category,
        claimed_amount,
        len(doc_list),
    )

    state = {
        "claim_id": f"CLM_{member_id}_{treatment_date}",
        "member_id": member_id,
        "policy_id": "PLUM_GHI_2024",
        "claim_category": claim_category,
        "treatment_date": treatment_date,
        "submission_date": submission_date or treatment_date,
        "claimed_amount": claimed_amount,
        "hospital_name": hospital_name,
        "ytd_claims_amount": ytd_claims_amount,
        "claims_history": [],
        "documents": doc_list,
        "simulate_component_failure": False,
    }

    result = await async_process_claim(state)
    processing_time_ms = result.pop("_processing_time_ms", 0)

    # Persist
    save_claim(state)
    save_decision(state["claim_id"], result, processing_time_ms)

    # Clean up temp files
    for doc in doc_list:
        with contextlib.suppress(OSError):
            os.unlink(doc["file_path"])

    decision = result.get("decision")
    return ClaimResponse(
        claim_id=state["claim_id"],
        decision=decision,
        approved_amount=result.get("approved_amount", 0),
        confidence_score=result.get("confidence_score", 0),
        message=result.get("message", ""),
        rejection_reasons=result.get("rejection_reasons", []),
        requires_action=decision is None,
        amount_breakdown=result.get("amount_breakdown"),
        policy_checks=result.get("policy_checks", []),
        fraud_signals=result.get("fraud_signals", []),
        trace=result.get("trace", []),
        component_failures=result.get("component_failures", []),
        processed_at=datetime.now(UTC),
    )


@app.post("/api/claims/process-json", response_model=ClaimResponse)
async def process_claim_json(payload: ClaimRequest):
    """Process a claim from validated JSON input."""
    logger.info(
        "POST /api/claims/process-json | member=%s category=%s amount=%.0f docs=%d",
        payload.member_id,
        payload.claim_category,
        payload.claimed_amount,
        len(payload.documents),
    )
    state = {
        "claim_id": f"CLM_{payload.member_id}_{payload.treatment_date}",
        "member_id": payload.member_id,
        "policy_id": payload.policy_id,
        "claim_category": payload.claim_category,
        "treatment_date": str(payload.treatment_date),
        "submission_date": str(payload.submission_date or payload.treatment_date),
        "claimed_amount": payload.claimed_amount,
        "hospital_name": payload.hospital_name,
        "ytd_claims_amount": payload.ytd_claims_amount,
        "claims_history": [h.model_dump() for h in payload.claims_history],
        "documents": [d.model_dump() for d in payload.documents],
        "simulate_component_failure": payload.simulate_component_failure,
        "extracted_data": [],
    }

    result = await async_process_claim(state)
    processing_time_ms = result.pop("_processing_time_ms", 0)

    save_claim(state)
    save_decision(state["claim_id"], result, processing_time_ms)

    decision = result.get("decision")
    return ClaimResponse(
        claim_id=state["claim_id"],
        decision=decision,
        approved_amount=result.get("approved_amount", 0),
        confidence_score=result.get("confidence_score", 0),
        message=result.get("message", ""),
        rejection_reasons=result.get("rejection_reasons", []),
        requires_action=decision is None,
        amount_breakdown=result.get("amount_breakdown"),
        policy_checks=result.get("policy_checks", []),
        fraud_signals=result.get("fraud_signals", []),
        trace=result.get("trace", []),
        component_failures=result.get("component_failures", []),
        processed_at=datetime.now(UTC),
    )


@app.get("/api/claims/{claim_id}")
def get_claim_detail(claim_id: str):
    """Retrieve a previously processed claim and its decision."""
    claim = get_claim(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    decision = get_decision(claim_id)
    return {"claim": claim, "decision": decision}


@app.get("/api/claims")
def list_all_claims(member_id: str | None = None, limit: int = 50):
    """List claims with optional member filter."""
    return {"claims": list_claims(member_id=member_id, limit=limit)}
