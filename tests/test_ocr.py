"""Tests for OCR service — verify text extraction from test documents."""

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from app.services.ocr import assess_readability, extract_text_from_file


def test_extract_clear_jpg():
    """TC001: clear prescription JPG should extract doctor name and patient."""
    result = extract_text_from_file("test_documents/TC001/dr_sharma_prescription.jpg")
    assert result["avg_confidence"] > 0.5
    assert len(result["lines"]) > 3
    text = result["raw_text"].lower()
    assert "sharma" in text or "arun" in text
    assert "rajesh" in text or "kumar" in text


def test_extract_blurry_jpg():
    """TC002: blurry pharmacy bill should have lower confidence."""
    result = extract_text_from_file("test_documents/TC002/blurry_bill.jpg")
    clear_result = extract_text_from_file("test_documents/TC001/dr_sharma_prescription.jpg")
    # Blurry should have lower confidence than clear
    assert result["avg_confidence"] < clear_result["avg_confidence"]


def test_extract_pdf():
    """TC004: hospital bill PDF should extract patient and amounts."""
    result = extract_text_from_file("test_documents/TC004/hospital_bill.pdf")
    assert result["avg_confidence"] > 0.6
    text = result["raw_text"].lower()
    assert "rajesh" in text or "kumar" in text
    assert "1500" in text or "1,500" in text


def test_readability_good():
    result = extract_text_from_file("test_documents/TC001/dr_sharma_prescription.jpg")
    label, score = assess_readability(result)
    assert label in ("GOOD", "DEGRADED")


def test_readability_blurry():
    result = extract_text_from_file("test_documents/TC002/blurry_bill.jpg")
    label, score = assess_readability(result)
    # Should be DEGRADED or UNREADABLE
    assert label in ("DEGRADED", "UNREADABLE")


def test_extract_pharmacy_bill_jpg():
    """TC018: pharmacy bill JPG should extract medicine names and amounts."""
    result = extract_text_from_file("test_documents/TC018/pharmacy_bill.jpg")
    text = result["raw_text"].lower()
    assert "pharmacy" in text or "medplus" in text
    assert "2400" in text or "1800" in text or "600" in text


if __name__ == "__main__":
    print("Testing OCR extraction...")
    test_extract_clear_jpg()
    print("  Clear JPG: PASS")
    test_extract_blurry_jpg()
    print("  Blurry vs Clear confidence: PASS")
    test_extract_pdf()
    print("  PDF extraction: PASS")
    test_readability_good()
    print("  Readability (good): PASS")
    test_readability_blurry()
    print("  Readability (blurry): PASS")
    test_extract_pharmacy_bill_jpg()
    print("  Pharmacy bill JPG: PASS")
    print("\nAll OCR tests passed!")
