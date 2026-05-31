"""Gemini API client for document interpretation with dual-input strategy.

Architecture: EasyOCR text + Gemini Vision → Gemini structured extraction.
Both OCR output and the raw image are fed to Gemini for final structuring.

Uses google.genai SDK with Gemini 3.5 Flash.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from app.logging_config import get_logger

logger = get_logger("service.gemini")

load_dotenv(Path(__file__).parent.parent.parent / ".env")

try:
    from google import genai
    from google.genai import types as genai_types

    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


_client = None

MODEL = "gemini-3.5-flash"


class GeminiExtractionResult(BaseModel):
    """Validated structured output from Gemini extraction."""

    patient_name: str | None = None
    doctor_name: str | None = None
    doctor_registration: str | None = None
    date: str | None = None
    diagnosis: str | None = None
    hospital_name: str | None = None
    medicines: list[str] = []
    line_items: list[dict] = []
    total: float | None = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable not set")
        _client = genai.Client(api_key=api_key)
    return _client


def is_available() -> bool:
    return GEMINI_AVAILABLE and bool(os.environ.get("GEMINI_API_KEY"))


def _load_image_as_part(file_path: str):
    """Load an image file as a Gemini Part object."""
    path = Path(file_path)
    if not path.exists():
        return None

    suffix = path.suffix.lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    mime_type = mime_map.get(suffix)
    if not mime_type:
        return None

    data = path.read_bytes()
    return genai_types.Part.from_bytes(data=data, mime_type=mime_type)


async def extract_with_vision(
    file_path: str,
    ocr_text: str,
    doc_type: str,
) -> GeminiExtractionResult | None:
    """
    Dual-input extraction: sends both the image AND OCR text to Gemini.

    Strategy:
    1. EasyOCR has already extracted raw text (reliable for printed text)
    2. Gemini Vision sees the original image (understands layout, handwriting)
    3. Both are combined in a single prompt for structured extraction
    """
    if not is_available():
        return None

    image_part = _load_image_as_part(file_path)

    prompt = f"""You are a medical document data extractor for Indian health insurance claims.

Document type: {doc_type}

I have two sources of information about this document:
1. OCR-extracted text (may have errors but captures printed text reliably)
2. The original document image (you can see layout, handwriting, stamps)

Use BOTH sources to extract the most accurate data. Where they conflict, prefer what you can visually confirm in the image.

OCR Text:
---
{ocr_text}
---

Extract these fields and return ONLY a JSON object:
- patient_name: string or null
- doctor_name: string or null (include "Dr." prefix)
- doctor_registration: string or null
- date: string in YYYY-MM-DD format or null
- diagnosis: string or null
- hospital_name: string or null
- medicines: list of strings or empty list
- line_items: list of objects with "description" (string) and "amount" (float) keys, or empty list
- total: float or null

Return ONLY valid JSON, no markdown."""

    try:
        logger.info(
            "Gemini dual-input extraction: %s (type=%s, has_image=%s)", file_path, doc_type, image_part is not None
        )
        client = _get_client()
        content_parts: list = [prompt]
        if image_part:
            content_parts.append(image_part)

        response = client.models.generate_content(model=MODEL, contents=content_parts)
        text = (response.text or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        raw = json.loads(text)
        result = GeminiExtractionResult(**raw)
        logger.info("Gemini extraction successful: patient=%s, items=%d", result.patient_name, len(result.line_items))
        return result
    except (json.JSONDecodeError, ValidationError) as e:
        logger.warning("Gemini response validation failed: %s — trying fallback", type(e).__name__)
        return _fallback_parse(text if "text" in dir() else "")
    except Exception as e:
        logger.error("Gemini extraction failed: %s", str(e))
        return None


def interpret_document(ocr_text: str, doc_type: str, prompt_context: str = "") -> dict | None:
    """Synchronous extraction from OCR text only (no vision). Legacy fallback."""
    if not is_available():
        return None

    prompt = f"""You are a medical document data extractor for Indian health insurance claims.

Document type: {doc_type}
{f"Context: {prompt_context}" if prompt_context else ""}

Extract the following fields from the OCR text below. Return ONLY a JSON object with these fields:
- patient_name: string or null
- doctor_name: string or null (include "Dr." prefix)
- doctor_registration: string or null
- date: string in YYYY-MM-DD format or null
- diagnosis: string or null
- hospital_name: string or null
- medicines: list of strings or empty list
- line_items: list of objects with "description" and "amount" (float) keys, or empty list
- total: float or null

OCR Text:
{ocr_text}

Respond with ONLY the JSON object, no markdown formatting."""

    try:
        client = _get_client()
        response = client.models.generate_content(model=MODEL, contents=prompt)
        text = (response.text or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(text)
    except Exception:
        return None


async def classify_document_vision(file_path: str) -> str | None:
    """Use Gemini Vision to classify document type from the image."""
    if not is_available():
        return None

    image_part = _load_image_as_part(file_path)
    if not image_part:
        return None

    prompt = """Classify this medical document into exactly ONE of these types:
- PRESCRIPTION
- HOSPITAL_BILL
- LAB_REPORT
- PHARMACY_BILL
- DISCHARGE_SUMMARY
- UNKNOWN

Return ONLY the type name, nothing else."""

    try:
        client = _get_client()
        response = client.models.generate_content(model=MODEL, contents=[prompt, image_part])
        result = (response.text or "").strip().upper()
        valid_types = {"PRESCRIPTION", "HOSPITAL_BILL", "LAB_REPORT", "PHARMACY_BILL", "DISCHARGE_SUMMARY", "UNKNOWN"}
        return result if result in valid_types else "UNKNOWN"
    except Exception:
        return None


def _fallback_parse(text: str) -> GeminiExtractionResult | None:
    """Attempt lenient parsing when strict validation fails."""
    try:
        if not text:
            return None
        raw = json.loads(text)
        items = raw.get("line_items", [])
        cleaned_items = []
        for item in items:
            if isinstance(item, dict) and "description" in item:
                cleaned_items.append(
                    {
                        "description": str(item["description"]),
                        "amount": float(item.get("amount", 0)),
                    }
                )
        raw["line_items"] = cleaned_items
        return GeminiExtractionResult(**raw)
    except Exception:
        return None
