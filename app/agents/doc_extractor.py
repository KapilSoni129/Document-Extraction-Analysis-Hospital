"""Document extractor agent: extracts structured fields from verified documents.

Strategy (dual-input when Gemini available):
1. EasyOCR text already extracted by doc_verifier
2. Gemini Vision sees the original image
3. Both fed to Gemini for structured extraction
4. Fallback: regex extraction from OCR text only
"""

import asyncio
import re
import time
from datetime import UTC, datetime

from app.config import load_pipeline_config
from app.logging_config import get_logger
from app.models.state import ClaimProcessingState
from app.services.gemini import extract_with_vision
from app.services.gemini import is_available as gemini_available

logger = get_logger("agent.doc_extractor")


def doc_extractor(state: ClaimProcessingState) -> dict:
    start = time.time()
    trace_steps = []
    extracted_data = []

    verified_documents = state.get("verified_documents", [])
    documents = state.get("documents", [])
    existing_extracted = state.get("extracted_data", [])

    if existing_extracted:
        logger.debug(
            "[%s] Using pre-populated extracted_data (%d docs)", state.get("claim_id"), len(existing_extracted)
        )
        trace_steps.append(
            _step(
                "use_existing_data",
                start,
                {"docs_count": len(existing_extracted)},
                {"reason": "extracted_data already populated"},
            )
        )
        return {
            "extracted_data": existing_extracted,
            "trace": state.get("trace", []) + trace_steps,
        }

    if not verified_documents and not documents:
        trace_steps.append(_step("skip_no_docs", start, {}, {"reason": "no verified documents"}))
        return {
            "extracted_data": [],
            "trace": state.get("trace", []) + trace_steps,
        }

    if verified_documents:
        for doc in verified_documents:
            ocr_result = doc.get("ocr_result")
            file_path = doc.get("file_path")
            detected_type = doc["detected_type"]

            # Dual-input: OCR text + Gemini Vision
            if ocr_result and file_path and gemini_available():
                gemini_result = _run_async(
                    extract_with_vision(
                        file_path=file_path,
                        ocr_text=ocr_result["raw_text"],
                        doc_type=detected_type,
                    )
                )
                if gemini_result:
                    extracted = gemini_result.model_dump()
                    extracted_data.append(extracted)
                    trace_steps.append(
                        _step(
                            "extract_gemini_vision",
                            start,
                            {"file": doc["file_name"], "type": detected_type},
                            {
                                "method": "dual_input_gemini_vision",
                                "fields_extracted": [k for k, v in extracted.items() if v],
                            },
                        )
                    )
                    continue

            # Fallback: regex extraction from OCR text
            if ocr_result:
                extracted = _extract_from_ocr(ocr_result["raw_text"], detected_type)
                extracted_data.append(extracted)
                trace_steps.append(
                    _step(
                        "extract_from_ocr",
                        start,
                        {"file": doc["file_name"], "type": detected_type},
                        {"method": "regex_ocr", "fields_extracted": list(extracted.keys())},
                    )
                )
            else:
                trace_steps.append(_step("skip_no_ocr", start, {"file": doc["file_name"]}, {"reason": "no OCR result"}))

    if not extracted_data and documents:
        for doc in documents:
            content = doc.get("content", {})
            if content:
                extracted = {
                    "patient_name": content.get("patient_name"),
                    "doctor_name": content.get("doctor_name"),
                    "date": content.get("date"),
                    "diagnosis": content.get("diagnosis"),
                    "hospital_name": content.get("hospital_name"),
                    "line_items": content.get("line_items", []),
                    "total": content.get("total"),
                    "medicines": content.get("medicines", []),
                }
                extracted_data.append(extracted)
                trace_steps.append(
                    _step(
                        "extract_from_content",
                        start,
                        {"file": doc.get("file_name", doc.get("file_id", "unknown"))},
                        {"method": "pre_structured", "fields_extracted": [k for k, v in extracted.items() if v]},
                    )
                )
            elif doc.get("patient_name_on_doc"):
                extracted = {
                    "patient_name": doc["patient_name_on_doc"],
                    "doctor_name": None,
                    "date": None,
                    "diagnosis": None,
                    "hospital_name": None,
                    "line_items": [],
                    "total": None,
                    "medicines": [],
                }
                extracted_data.append(extracted)
                trace_steps.append(
                    _step(
                        "extract_from_metadata",
                        start,
                        {"file": doc.get("file_name", doc.get("file_id", "unknown"))},
                        {"method": "doc_metadata", "patient_name": doc["patient_name_on_doc"]},
                    )
                )

    return {
        "extracted_data": extracted_data,
        "trace": state.get("trace", []) + trace_steps,
    }


async def async_doc_extractor(state: ClaimProcessingState) -> dict:
    """Async version for use within async pipeline."""
    start = time.time()
    trace_steps = []
    extracted_data = []

    verified_documents = state.get("verified_documents", [])
    documents = state.get("documents", [])
    existing_extracted = state.get("extracted_data", [])

    if existing_extracted:
        trace_steps.append(
            _step(
                "use_existing_data",
                start,
                {"docs_count": len(existing_extracted)},
                {"reason": "extracted_data already populated"},
            )
        )
        return {
            "extracted_data": existing_extracted,
            "trace": state.get("trace", []) + trace_steps,
        }

    if not verified_documents and not documents:
        trace_steps.append(_step("skip_no_docs", start, {}, {"reason": "no verified documents"}))
        return {
            "extracted_data": [],
            "trace": state.get("trace", []) + trace_steps,
        }

    # Process documents concurrently with Gemini Vision
    if verified_documents and gemini_available():
        tasks = []
        task_docs = []
        for doc in verified_documents:
            ocr_result = doc.get("ocr_result")
            file_path = doc.get("file_path")
            if ocr_result and file_path:
                tasks.append(
                    extract_with_vision(
                        file_path=file_path,
                        ocr_text=ocr_result["raw_text"],
                        doc_type=doc["detected_type"],
                    )
                )
                task_docs.append(doc)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for doc, result in zip(task_docs, results, strict=False):
                if result and not isinstance(result, (Exception, BaseException)):
                    extracted = result.model_dump()  # type: ignore[union-attr]
                    extracted_data.append(extracted)
                    trace_steps.append(
                        _step(
                            "extract_gemini_vision",
                            start,
                            {"file": doc["file_name"], "type": doc["detected_type"]},
                            {"method": "dual_input_gemini_vision_async"},
                        )
                    )
                elif doc.get("ocr_result"):
                    extracted = _extract_from_ocr(doc["ocr_result"]["raw_text"], doc["detected_type"])
                    extracted_data.append(extracted)
                    trace_steps.append(
                        _step("extract_from_ocr", start, {"file": doc["file_name"]}, {"method": "regex_ocr_fallback"})
                    )

    # Fallback for docs without Gemini
    if not extracted_data:
        if verified_documents:
            for doc in verified_documents:
                ocr_result = doc.get("ocr_result")
                if ocr_result:
                    extracted = _extract_from_ocr(ocr_result["raw_text"], doc["detected_type"])
                    extracted_data.append(extracted)
                    trace_steps.append(
                        _step("extract_from_ocr", start, {"file": doc["file_name"]}, {"method": "regex_ocr"})
                    )
        elif documents:
            for doc in documents:
                content = doc.get("content", {})
                if content:
                    extracted = {
                        "patient_name": content.get("patient_name"),
                        "doctor_name": content.get("doctor_name"),
                        "date": content.get("date"),
                        "diagnosis": content.get("diagnosis"),
                        "hospital_name": content.get("hospital_name"),
                        "line_items": content.get("line_items", []),
                        "total": content.get("total"),
                        "medicines": content.get("medicines", []),
                    }
                    extracted_data.append(extracted)
                    trace_steps.append(
                        _step(
                            "extract_from_content",
                            start,
                            {"file": doc.get("file_name", "unknown")},
                            {"method": "pre_structured"},
                        )
                    )

    return {
        "extracted_data": extracted_data,
        "trace": state.get("trace", []) + trace_steps,
    }


def _run_async(coro):
    """Run an async coroutine from sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=30)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _extract_from_ocr(text: str, doc_type: str) -> dict:
    """Extract structured fields from raw OCR text using regex patterns."""
    config = load_pipeline_config()["extraction"]["patterns"]
    extracted = {
        "patient_name": None,
        "doctor_name": None,
        "date": None,
        "diagnosis": None,
        "hospital_name": None,
        "line_items": [],
        "total": None,
        "medicines": [],
    }

    lines = text.split("\n")

    for line in lines:
        match = re.search(config["patient_name"], line, re.IGNORECASE)
        if match and not extracted["patient_name"]:
            extracted["patient_name"] = match.group(1).strip()
            break

    for line in lines:
        match = re.search(config["doctor_name"], line, re.IGNORECASE)
        if match and not extracted["doctor_name"]:
            extracted["doctor_name"] = match.group(1).strip().split("\n")[0]
            break

    for line in lines:
        match = re.search(config["date"], line)
        if match:
            extracted["date"] = match.group(1)
            break

    for line in lines:
        match = re.search(config["diagnosis"], line, re.IGNORECASE)
        if match:
            extracted["diagnosis"] = match.group(1).strip()
            break

    amounts = re.findall(config["amount"], text, re.IGNORECASE)
    if amounts:
        extracted["total"] = float(amounts[-1].replace(",", ""))

    for line in lines:
        match = re.search(config["line_item"], line, re.IGNORECASE)
        if match:
            desc = match.group(1).strip()
            amount = float(match.group(2).replace(",", ""))
            if desc and amount > 0:
                extracted["line_items"].append({"description": desc, "amount": amount})

    return extracted


def _step(action, ref_time, input_summary, output_summary):
    return {
        "agent": "doc_extractor",
        "timestamp": datetime.now(UTC).isoformat(),
        "action": action,
        "status": "SUCCESS",
        "duration_ms": int((time.time() - ref_time) * 1000),
        "input_summary": input_summary,
        "output_summary": output_summary,
    }
