from typing import Literal

from pydantic import BaseModel


class DocumentInfo(BaseModel):
    file_id: str
    file_name: str
    file_path: str
    mime_type: str


class LineItem(BaseModel):
    description: str
    amount: float


class DocumentVerification(BaseModel):
    file_id: str
    detected_type: str
    quality_score: float
    quality_label: Literal["GOOD", "DEGRADED", "UNREADABLE"]
    is_valid: bool
    issues: list[str] = []


class ExtractedDocument(BaseModel):
    file_id: str
    doc_type: str
    confidence: float
    patient_name: str | None = None
    date: str | None = None
    doctor_name: str | None = None
    doctor_registration: str | None = None
    hospital_name: str | None = None
    diagnosis: str | None = None
    treatment: str | None = None
    medicines: list[str] = []
    line_items: list[LineItem] = []
    total_amount: float | None = None
