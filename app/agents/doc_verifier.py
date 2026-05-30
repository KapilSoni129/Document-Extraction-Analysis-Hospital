"""Document verifier agent: classifies document types and assesses quality using OCR."""

import time
from datetime import UTC, datetime

from app.config import get_document_requirements, load_pipeline_config
from app.logging_config import get_logger
from app.models.state import ClaimProcessingState
from app.services.ocr import assess_readability, extract_text_from_file

logger = get_logger("agent.doc_verifier")


def doc_verifier(state: ClaimProcessingState) -> dict:
    start = time.time()
    trace_steps = []
    verified_docs = []
    doc_errors = []

    documents = state.get("documents", [])
    claim_category = state["claim_category"]

    doc_reqs = get_document_requirements(claim_category)
    required_types = doc_reqs.get("required", []) if isinstance(doc_reqs, dict) else doc_reqs

    if not documents:
        logger.warning("[%s] No documents submitted", state.get("claim_id"))
        required_names = [t.replace("_", " ").title() for t in required_types]
        trace_steps.append(_step("no_documents", start, {}, {"result": "no documents provided"}))
        return {
            "verified_documents": [],
            "doc_errors": [
                {
                    "type": "NO_DOCUMENTS",
                    "message": f"No documents were submitted. For a {claim_category.title()} claim, "
                    f"you must upload: {', '.join(required_names)}. "
                    f"Please upload these documents as clear photos or PDF scans and resubmit.",
                }
            ],
            "trace": state.get("trace", []) + trace_steps,
        }

    for doc in documents:
        file_name = doc.get("file_name", "")
        file_path = doc.get("file_path")

        # If file_path provided, run OCR
        if file_path:
            try:
                ocr_result = extract_text_from_file(file_path)
                quality_label, quality_score = assess_readability(ocr_result)
                detected_type = _classify_document(ocr_result["raw_text"])
            except Exception as e:
                doc_errors.append(
                    {
                        "type": "OCR_FAILURE",
                        "file": file_name,
                        "message": f"Failed to process document: {str(e)}",
                    }
                )
                trace_steps.append(_step("ocr_failure", start, {"file": file_name}, {"error": str(e)}))
                continue
        else:
            # Use metadata from test case input (no actual file)
            config = load_pipeline_config()
            quality_scores = config["document_verification"]["test_quality_scores"]
            quality_label = doc.get("quality", "GOOD")
            quality_score = quality_scores.get(quality_label, 0.5)
            detected_type = doc.get("actual_type", "UNKNOWN")
            ocr_result = None

        # Check readability
        if quality_label == "UNREADABLE":
            logger.warning("[%s] Document unreadable: %s (score=%.2f)", state.get("claim_id"), file_name, quality_score)
            doc_errors.append(
                {
                    "type": "UNREADABLE_DOCUMENT",
                    "file": file_name,
                    "message": f"Document '{file_name}' is unreadable (quality score: {quality_score:.2f}). "
                    f"Please retake the photo in good lighting, ensure the full document is visible "
                    f"without blur or shadows, and re-upload.",
                }
            )
            trace_steps.append(
                _step("quality_check", start, {"file": file_name, "quality": quality_label}, {"passed": False})
            )
            continue

        verified_docs.append(
            {
                "file_name": file_name,
                "file_path": file_path,
                "detected_type": detected_type,
                "quality": quality_label,
                "quality_score": quality_score,
                "ocr_result": ocr_result,
            }
        )
        trace_steps.append(
            _step("verify_document", start, {"file": file_name}, {"type": detected_type, "quality": quality_label})
        )

    logger.info(
        "[%s] Verified %d docs: %s",
        state.get("claim_id"),
        len(verified_docs),
        [(d["file_name"], d["detected_type"], d["quality"]) for d in verified_docs],
    )

    # Check if required document types are present
    detected_types = {d["detected_type"] for d in verified_docs}
    missing = [rt for rt in required_types if rt not in detected_types]
    if missing:
        missing_names = [t.replace("_", " ").title() for t in missing]
        wrong_types = detected_types - set(required_types)
        if wrong_types:
            wrong_names = [t.replace("_", " ").title() for t in wrong_types]
            doc_errors.append(
                {
                    "type": "WRONG_DOCUMENT_TYPE",
                    "message": f"For a {claim_category.title()} claim, we require: {', '.join(missing_names)}. "
                    f"You uploaded: {', '.join(wrong_names)} instead. "
                    f"Please upload the correct document(s) and resubmit your claim.",
                }
            )
        else:
            detected_names = [t.replace("_", " ").title() for t in detected_types]
            doc_errors.append(
                {
                    "type": "MISSING_DOCUMENT",
                    "message": f"For a {claim_category.title()} claim, you are missing: {', '.join(missing_names)}. "
                    f"You uploaded: {', '.join(detected_names)}. "
                    f"Please also upload {'this document' if len(missing) == 1 else 'these documents'} "
                    f"and resubmit your claim.",
                }
            )
        trace_steps.append(
            _step(
                "check_required_types",
                start,
                {"required": required_types, "detected": list(detected_types)},
                {"missing": missing},
            )
        )

    return {
        "verified_documents": verified_docs,
        "doc_errors": doc_errors,
        "trace": state.get("trace", []) + trace_steps,
    }


def _classify_document(text: str) -> str:
    config = load_pipeline_config()
    doc_type_keywords = config["document_verification"]["classification_keywords"]
    text_lower = text.lower()
    scores = {}
    for doc_type, keywords in doc_type_keywords.items():
        scores[doc_type] = sum(1 for kw in keywords if kw in text_lower)
    if max(scores.values()) == 0:
        return "UNKNOWN"
    return max(scores, key=lambda k: scores[k])


def _step(action, ref_time, input_summary, output_summary):
    return {
        "agent": "doc_verifier",
        "timestamp": datetime.now(UTC).isoformat(),
        "action": action,
        "status": "SUCCESS",
        "duration_ms": int((time.time() - ref_time) * 1000),
        "input_summary": input_summary,
        "output_summary": output_summary,
    }
