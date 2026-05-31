"""OCR service using EasyOCR for text extraction from medical documents."""

from pathlib import Path

import numpy as np
from PIL import Image

from app.config import load_pipeline_config
from app.logging_config import get_logger

logger = get_logger("service.ocr")


_reader = None


def get_reader():
    """Lazy-initialize EasyOCR reader (downloads model on first call)."""
    global _reader
    if _reader is None:
        import easyocr

        logger.info("Initializing EasyOCR reader (first call, may download model)")
        _reader = easyocr.Reader(["en"], gpu=False)
        logger.info("EasyOCR reader ready")
    return _reader


def extract_text_from_file(file_path: str) -> dict:
    """
    Extract text from an image or PDF file using EasyOCR.

    Returns:
        {
            "raw_text": str,          # All text concatenated
            "lines": list[str],       # Text grouped by lines
            "fields": list[dict],     # [{text, confidence, bbox}]
            "avg_confidence": float,  # Average OCR confidence
        }
    """
    path = Path(file_path)

    if path.suffix.lower() == ".pdf":
        image = _pdf_first_page_to_image(path)
    else:
        image = np.array(Image.open(path).convert("RGB"))

    reader = get_reader()
    results = reader.readtext(image)

    fields = []
    lines = []
    current_line = []
    prev_y = None

    for bbox, text, confidence in results:
        top_y = bbox[0][1]

        config = load_pipeline_config()["ocr"]
        # Group into lines based on vertical position
        if prev_y is not None and abs(top_y - prev_y) > config["line_grouping_y_threshold"] and current_line:
            lines.append(" ".join(current_line))
            current_line = []

        current_line.append(text)
        prev_y = top_y

        fields.append(
            {
                "text": text,
                "confidence": round(confidence, 3),
                "bbox": [[int(p[0]), int(p[1])] for p in bbox],
            }
        )

    if current_line:
        lines.append(" ".join(current_line))

    avg_confidence = sum(f["confidence"] for f in fields) / len(fields) if fields else 0.0

    logger.debug("OCR complete: %s | fields=%d avg_confidence=%.3f", file_path, len(fields), avg_confidence)
    return {
        "raw_text": "\n".join(lines),
        "lines": lines,
        "fields": fields,
        "avg_confidence": round(avg_confidence, 3),
    }


def assess_readability(ocr_result: dict) -> tuple[str, float]:
    """Assess document readability from OCR results."""
    config = load_pipeline_config()["ocr"]
    score = ocr_result["avg_confidence"]
    num_fields = len(ocr_result["fields"])

    if num_fields < config["min_fields_for_confidence"]:
        score = min(score, config["low_field_score_cap"])

    if score >= config["quality_thresholds"]["good_min"]:
        return "GOOD", score
    elif score >= config["quality_thresholds"]["degraded_min"]:
        return "DEGRADED", score
    else:
        return "UNREADABLE", score


def _pdf_first_page_to_image(pdf_path: Path) -> np.ndarray:
    """Convert first page of PDF to image array for OCR processing."""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(pdf_path))
        page = doc[0]
        config = load_pipeline_config()["ocr"]
        pix = page.get_pixmap(dpi=config["pdf_dpi"])
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        return np.array(img)
    except ImportError:
        # Fallback: try to read PDF as image (some PDFs are image-based)
        img = Image.open(pdf_path).convert("RGB")
        return np.array(img)
