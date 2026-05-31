# Component Contracts

Every significant component in the system, its interface: what it accepts, what it produces, and what errors it can raise. Precise enough that another engineer could reimplement any single component without reading its code.

---

## Pipeline Orchestrator (`app/agents/graph.py`)

### `process_claim(initial_state: dict) -> dict`

Runs the full 6-agent pipeline synchronously.

**Input:**
```python
{
    "claim_id": str,                    # Unique claim identifier
    "member_id": str,                   # e.g. "EMP001"
    "policy_id": str,                   # Default: "PLUM_GHI_2024"
    "claim_category": str,              # "CONSULTATION" | "DIAGNOSTIC" | "PHARMACY" | "DENTAL" | "VISION" | "ALTERNATIVE_MEDICINE"
    "treatment_date": str,              # ISO date "YYYY-MM-DD"
    "submission_date": str,             # ISO date "YYYY-MM-DD"
    "claimed_amount": float,            # Positive number
    "hospital_name": str | None,        # For network discount detection
    "ytd_claims_amount": float,         # Year-to-date claims already paid
    "claims_history": list[dict],       # Prior claims [{date, amount, ...}]
    "documents": list[dict],            # Uploaded docs [{file_name, file_path?, content?}]
    "simulate_component_failure": bool, # For testing graceful degradation
    "extracted_data": list[dict],       # Pre-populated extraction (skips doc_extractor)
}
```

**Output:**
```python
{
    "decision": "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW",
    "approved_amount": float,           # 0 for rejections
    "confidence_score": float,          # 0.3 - 1.0
    "message": str,                     # Human-readable explanation
    "rejection_reasons": list[str],     # e.g. ["SUBMISSION_DEADLINE_EXCEEDED"]
    "amount_breakdown": dict | None,    # Full financial calculation steps
    "policy_checks": list[dict],        # All rules evaluated [{rule_name, passed, details, impact}]
    "fraud_signals": list[dict],        # Fraud indicators [{signal, details, count, threshold}]
    "trace": list[dict],                # Ordered execution trace
    "component_failures": list[dict],   # Failed agents [{agent, error}]
}
```

**Errors:** Never raises. On internal failure, returns `MANUAL_REVIEW` with reduced confidence and populated `component_failures`.

### `async_process_claim(initial_state: dict) -> dict`

Same contract as `process_claim`, but async. Adds `_processing_time_ms: int` to the output dict.

---

## Agent 1: Intake (`app/agents/intake.py`)

### `intake_agent(state: ClaimProcessingState) -> dict`

Validates basic claim eligibility before any document processing or LLM calls.

**Reads from state:**
- `member_id`, `claim_category`, `treatment_date`, `submission_date`, `claimed_amount`

**Output (success path):**
```python
{
    "member_info": dict,         # Full member record from policy_terms.json
    "policy_config": dict,       # Full policy config
    "category_config": dict,     # Category-specific rules (copay, sub_limit, etc.)
    "early_rejection": None,     # Signals: proceed to doc_verifier
    "trace": list[dict],         # Appended trace steps
}
```

**Output (rejection path):**
```python
{
    "early_rejection": {
        "reason_code": str,      # One of codes below
        "message": str,          # Human-readable with specific details
    },
    "trace": list[dict],
}
```

**Rejection reason codes:**
| Code | Condition |
|------|-----------|
| `MEMBER_NOT_FOUND` | member_id not in policy roster |
| `INVALID_CATEGORY` | claim_category not recognized |
| `CATEGORY_NOT_COVERED` | Category exists but `covered: false` |
| `BELOW_MINIMUM_AMOUNT` | claimed_amount < policy minimum (currently Rs 500) |
| `SUBMISSION_DEADLINE_EXCEEDED` | Days between treatment and submission > deadline (30 days) |
| `INITIAL_WAITING_PERIOD` | Treatment within initial waiting period from join_date (30 days) |

**Errors:** None raised. All failures produce an `early_rejection`.

---

## Agent 2: Document Verifier (`app/agents/doc_verifier.py`)

### `doc_verifier(state: ClaimProcessingState) -> dict`

Classifies uploaded documents by type, assesses readability via OCR, and checks against category requirements.

**Reads from state:**
- `documents` (list of uploaded docs with `file_name`, `file_path`, or metadata)
- `claim_category` (determines which doc types are required)

**Output:**
```python
{
    "verified_documents": [
        {
            "file_name": str,
            "file_path": str | None,
            "detected_type": str,        # "PRESCRIPTION" | "HOSPITAL_BILL" | "LAB_REPORT" | "PHARMACY_BILL" | "UNKNOWN"
            "quality": str,              # "GOOD" | "DEGRADED"
            "quality_score": float,      # 0.0 - 1.0
            "ocr_result": dict | None,   # {raw_text, lines, fields, avg_confidence}
        }
    ],
    "doc_errors": [
        {
            "type": str,                 # Error type (see table)
            "file": str | None,          # Which file triggered the error
            "message": str,              # Specific, actionable error message
        }
    ],
    "trace": list[dict],
}
```

**Error types:**
| Type | Condition | Route |
|------|-----------|-------|
| `NO_DOCUMENTS` | Zero documents submitted | Early exit to decision_maker |
| `UNREADABLE_DOCUMENT` | Quality score < 0.2 threshold | Early exit to decision_maker |
| `WRONG_DOCUMENT_TYPE` | Required types not detected in uploads | Early exit to decision_maker |
| `MISSING_DOCUMENT` | Some required types not present | Early exit to decision_maker |
| `OCR_FAILURE` | EasyOCR threw an exception on a file | Logged, processing continues |

**Routing:** If `doc_errors` contains any type in `{NO_DOCUMENTS, UNREADABLE_DOCUMENT, WRONG_DOCUMENT_TYPE}`, the graph routes directly to `decision_maker` (skipping extraction and policy evaluation).

**Errors:** Never raises. OCR failures are caught and logged as `OCR_FAILURE` doc_errors.

---

## Agent 3: Document Extractor (`app/agents/doc_extractor.py`)

### `doc_extractor(state: ClaimProcessingState) -> dict`

Extracts structured medical data from verified documents using a dual-input strategy: EasyOCR text + Gemini Vision sent together for structured interpretation.

**Reads from state:**
- `verified_documents` (from doc_verifier, with OCR results and file paths)
- `documents` (fallback: pre-structured content for testing)
- `extracted_data` (if already populated, returns immediately)

**Output:**
```python
{
    "extracted_data": [
        {
            "patient_name": str | None,
            "doctor_name": str | None,
            "doctor_registration": str | None,
            "date": str | None,              # "YYYY-MM-DD"
            "diagnosis": str | None,
            "hospital_name": str | None,
            "medicines": list[str],
            "line_items": [{"description": str, "amount": float}],
            "total": float | None,
        }
    ],
    "trace": list[dict],
}
```

**Extraction methods (in priority order):**
1. **Gemini dual-input** — OCR text + document image sent to Gemini 3.5 Flash; response validated via Pydantic `GeminiExtractionResult`
2. **Regex extraction** — Pattern matching on OCR text (date, amounts, patient name, doctor name)
3. **Pre-structured content** — Direct pass-through from `documents[].content` (for test cases)

**Fallback behavior:** If Gemini unavailable or returns invalid response, falls back to regex. If no OCR results, falls back to pre-structured content. Never produces an error — returns empty `extracted_data` in worst case.

**Errors:** Never raises. All failures produce empty or partial `extracted_data`.

---

## Agent 4: Cross Validator (`app/agents/cross_validator.py`)

### `cross_validator(state: ClaimProcessingState) -> dict`

Checks consistency across extracted document data and member records.

**Reads from state:**
- `extracted_data` (list of extracted documents)
- `member_info` (member record from intake)
- `treatment_date`

**Output:**
```python
{
    "cross_validation_passed": bool,       # False only if HIGH severity errors
    "validation_errors": [
        {
            "type": str,                   # Error type (see table)
            "details": str,                # Specific mismatch details
            "severity": "HIGH" | "MEDIUM" | "LOW",
        }
    ],
    "trace": list[dict],
}
```

**Validation checks:**
| Check | Type | Severity | Threshold |
|-------|------|----------|-----------|
| Patient names across documents differ | `PATIENT_NAME_MISMATCH` | HIGH | Similarity < 0.85 |
| Document patient vs member name | `MEMBER_NAME_MISMATCH` | MEDIUM | Similarity < 0.75 |
| Document dates vs treatment_date | `DATE_MISMATCH` | LOW | Exact match required |

**Routing:** If `cross_validation_passed == False` (HIGH severity errors), the graph routes directly to `decision_maker`.

**Errors:** Never raises. Returns `cross_validation_passed: True` if no extracted data available.

---

## Agent 5: Policy Evaluator (`app/agents/policy_evaluator.py`)

### `policy_evaluator(state: ClaimProcessingState) -> dict`

Applies all policy rules to determine eligibility and calculate the approved amount.

**Reads from state:**
- `category_config`, `policy_config`, `member_info` (from intake)
- `claimed_amount`, `claim_category`, `treatment_date`
- `ytd_claims_amount`, `claims_history`
- `extracted_data` (for diagnosis, line items, hospital name)

**Output (eligible claim):**
```python
{
    "policy_checks": [
        {
            "rule_name": str,            # e.g. "exclusion_check", "pre_authorization"
            "passed": bool,
            "details": str,              # Human-readable explanation
            "impact": str | None,        # "REJECT" | "PARTIAL" | None (info only)
        }
    ],
    "eligible_amount": float,
    "amount_breakdown": {
        "original_claimed": float,
        "eligible_after_exclusions": float,
        "after_network_discount": float,
        "discount_amount": float,
        "after_sub_limit_cap": float,
        "sub_limit_applied": float | None,
        "after_annual_limit_cap": float,
        "annual_limit_remaining": float | None,
        "copay_amount": float,
        "copay_type": str,
        "final_approved": float,
    },
    "fraud_signals": [
        {
            "signal": str,               # "SAME_DAY_CLAIMS" | "MONTHLY_CLAIMS_LIMIT"
            "details": str,
            "count": int,
            "threshold": int,
        }
    ],
    "trace": list[dict],
}
```

**Output (ineligible claim — hard reject or fraud):**
```python
{
    "policy_checks": list[dict],         # With impact="REJECT" entries
    "eligible_amount": None,
    "amount_breakdown": None,            # Not calculated when rejected
    "fraud_signals": list[dict],
    "trace": list[dict],
}
```

**Policy rules evaluated (in order):**
| # | Rule | Impact on failure |
|---|------|-------------------|
| 1 | Condition-specific waiting period | REJECT |
| 2 | Exclusion matching (conditions, dental, vision) | REJECT |
| 3 | Pre-authorization (diagnostic > threshold) | REJECT |
| 4 | Line-item exclusions (dental/vision specific items) | PARTIAL (or REJECT if all items excluded) |
| 5 | Per-claim limit (only if no other rule rejected) | REJECT |
| 6 | Fraud signals (same-day, monthly limit) | Routes to MANUAL_REVIEW |

**Financial calculation order (when eligible):**
```
claimed_amount
  → filter excluded line items → eligible_after_exclusions
  → apply network discount (20%) → after_network_discount
  → apply sub-limit cap (if enabled) → after_sub_limit_cap
  → apply annual OPD remaining cap → after_annual_limit_cap
  → apply co-pay (10% consultation, 30% branded drugs) → final_approved
```

**Errors:** Never raises. If calculation fails, returns `amount_breakdown: None`.

---

## Agent 6: Decision Maker (`app/agents/decision_maker.py`)

### `decision_maker(state: ClaimProcessingState) -> dict`

Synthesizes the final decision from all prior pipeline state. Pure logic — no external calls.

**Reads from state:**
- `early_rejection` (from intake)
- `doc_errors` (from doc_verifier)
- `policy_checks`, `fraud_signals`, `amount_breakdown` (from policy_evaluator)
- `component_failures` (from any failed agent)
- `claimed_amount`

**Output:**
```python
{
    "decision": "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW",
    "confidence_score": float,       # 0.3 - 1.0
    "approved_amount": float,        # 0 for rejections/manual review
    "message": str,                  # Human-readable decision explanation
    "rejection_reasons": list[str],  # Reason codes for rejections
    "amount_breakdown": dict | None,
    "fraud_signals": list[dict],
    "policy_checks": list[dict],
    "component_failures": list[dict],
    "trace": list[dict],
}
```

**Decision logic (evaluated in this priority order):**

| Priority | Condition | Decision | Confidence |
|----------|-----------|----------|-----------|
| 1 | `early_rejection` set | REJECTED | 1.0 |
| 2 | `doc_errors` with critical types | REJECTED | 1.0 |
| 3 | `policy_checks` with `impact="REJECT"` | REJECTED | 1.0 |
| 4 | `fraud_signals` non-empty | MANUAL_REVIEW | 1.0 - 0.15 per signal |
| 5 | Structural reductions (sub-limit, annual cap, line-item exclusions) | PARTIAL | 1.0 |
| 6 | Normal claim (co-pay/discount only) | APPROVED | 1.0 |

**Confidence penalties:**
- `-0.15` per fraud signal
- `-0.2` per component failure
- Minimum floor: `0.3`

**APPROVED vs PARTIAL distinction:**
- APPROVED: Co-pay deductions or network discounts only (standard policy application)
- PARTIAL: Sub-limit cap hit, annual limit cap hit, or line-item exclusions reduced the amount

**Errors:** Never raises. Always produces a valid decision.

---

## Service: OCR (`app/services/ocr.py`)

### `extract_text_from_file(file_path: str) -> dict`

Extracts text from an image or PDF using EasyOCR.

**Input:** Absolute file path to image (JPG/PNG) or PDF.

**Output:**
```python
{
    "raw_text": str,            # All text concatenated with newlines
    "lines": list[str],         # Text grouped by vertical position
    "fields": [                 # Per-detection results
        {
            "text": str,
            "confidence": float,    # 0.0 - 1.0
            "bbox": list[list[int]],
        }
    ],
    "avg_confidence": float,    # Mean of all field confidences
}
```

**Errors:**
- `FileNotFoundError` — file doesn't exist
- `PIL.UnidentifiedImageError` — corrupted or unsupported format
- `RuntimeError` — EasyOCR internal failure

### `assess_readability(ocr_result: dict) -> tuple[str, float]`

**Input:** Output dict from `extract_text_from_file`.

**Output:** `(quality_label, score)` where:
- `"GOOD"` — score >= 0.7
- `"DEGRADED"` — score >= 0.2
- `"UNREADABLE"` — score < 0.2

---

## Service: Gemini (`app/services/gemini.py`)

### `extract_with_vision(file_path: str, ocr_text: str, doc_type: str) -> GeminiExtractionResult | None`

Dual-input extraction: sends both the document image and OCR text to Gemini 3.5 Flash.

**Input:**
- `file_path`: Path to the document image (JPG/PNG/WebP)
- `ocr_text`: Raw text from EasyOCR
- `doc_type`: Classified document type (for prompt context)

**Output:** `GeminiExtractionResult` (Pydantic model) or `None` on any failure.

```python
class GeminiExtractionResult(BaseModel):
    patient_name: str | None
    doctor_name: str | None
    doctor_registration: str | None
    date: str | None              # "YYYY-MM-DD"
    diagnosis: str | None
    hospital_name: str | None
    medicines: list[str]
    line_items: list[dict]        # [{"description": str, "amount": float}]
    total: float | None
```

**Failure modes (all return None):**
- `GEMINI_API_KEY` not set
- `google-generativeai` not installed
- API timeout or rate limit
- Response is not valid JSON
- Response JSON fails Pydantic validation AND lenient fallback

### `is_available() -> bool`

Returns `True` if Gemini package is installed AND API key is set.

### `classify_document_vision(file_path: str) -> str | None`

Uses Gemini Vision to classify a document image into one of: `PRESCRIPTION`, `HOSPITAL_BILL`, `LAB_REPORT`, `PHARMACY_BILL`, `DISCHARGE_SUMMARY`, `UNKNOWN`.

Returns `None` if Gemini unavailable or API call fails.

---

## Service: Storage (`app/services/storage.py`)

### `save_claim(state: dict) -> str`

Persists claim metadata to SQLite. Returns `claim_id`.

**Input:** Pipeline state dict (uses `claim_id`, `member_id`, `policy_id`, `claim_category`, `treatment_date`, `submission_date`, `claimed_amount`, `hospital_name`).

**Behavior:** INSERT OR REPLACE — idempotent on `claim_id`.

### `save_decision(claim_id: str, result: dict, processing_time_ms: int) -> None`

Persists a pipeline result. JSON-serializes: `rejection_reasons`, `amount_breakdown`, `policy_checks`, `fraud_signals`, `trace`, `component_failures`.

### `get_claim(claim_id: str) -> dict | None`

Returns the stored claim record or `None`.

### `get_decision(claim_id: str) -> dict | None`

Returns the most recent decision for a claim, with JSON fields deserialized back to Python objects. Returns `None` if no decision exists.

### `list_claims(member_id: str | None, limit: int) -> list[dict]`

Lists claims with their latest decision, optionally filtered by member. Ordered by `created_at DESC`.

**Errors:** All functions catch `sqlite3` errors internally. Database is auto-created on first call.

---

## Service: Tracing (`app/services/tracing.py`)

### `agent_span(agent_name: str, claim_id: str | None) -> ContextManager`

Creates an OpenTelemetry span for an agent execution. The span records:
- `agent.name` attribute
- `claim.id` attribute (if provided)
- Exceptions (via `span.record_exception`)
- Custom attributes (via `span.set_attribute`)

**Behavior when OTEL unavailable:** Returns a no-op context manager. Zero overhead.

### `pipeline_span(claim_id: str) -> ContextManager`

Top-level span wrapping the entire pipeline execution.

### `init_tracing(service_name: str) -> None`

Initializes the OpenTelemetry TracerProvider. Safe to call multiple times (idempotent). Configures exporter based on environment:
- `OTEL_EXPORTER_OTLP_ENDPOINT` set → OTLP HTTP exporter
- `OTEL_TRACE_CONSOLE=1` → Console exporter
- Neither → No exporter (spans are created but not exported)

---

## Utility: Financial Calculator (`app/utils/financial.py`)

### `calculate_approved_amount(...) -> AmountBreakdown`

Pure function that computes the approved amount through a fixed sequence of reductions.

**Input:**
```python
calculate_approved_amount(
    claimed_amount: float,
    category_config: dict,           # From policy_terms.json
    is_network: bool = False,
    ytd_claims_amount: float = 0.0,
    annual_opd_limit: float | None = None,  # Default: 50000
    line_items: list[dict] | None = None,
    excluded_descriptions: list[str] | None = None,
    is_branded_drug: bool = False,
    apply_sub_limit: bool = False,
)
```

**Output:**
```python
@dataclass
class AmountBreakdown:
    original_claimed: float
    eligible_after_exclusions: float
    after_network_discount: float
    discount_amount: float
    after_sub_limit_cap: float
    sub_limit_applied: float | None       # Only set when sub-limit actually capped
    after_annual_limit_cap: float
    annual_limit_remaining: float | None  # Only set when annual cap actually capped
    copay_amount: float
    copay_type: str                       # e.g. "category_copay_10%"
    final_approved: float
```

**Calculation order (invariant — must not be reordered):**
1. Filter excluded line items → `eligible_after_exclusions`
2. Network discount (20% if `is_network`) → `after_network_discount`
3. Sub-limit cap (only if `apply_sub_limit=True`) → `after_sub_limit_cap`
4. Annual OPD remaining cap → `after_annual_limit_cap`
5. Co-pay (10% default, 30% branded drugs) → `final_approved`

**Errors:** Never raises. All inputs have safe defaults.

---

## API Endpoints (`app/main.py`)

### `POST /api/claims/process`

**Input:** Multipart form data
- `member_id: str` (required)
- `claim_category: str` (required)
- `treatment_date: str` (required, ISO date)
- `claimed_amount: float` (required, > 0)
- `hospital_name: str` (optional)
- `ytd_claims_amount: float` (optional, default 0)
- `submission_date: str` (optional)
- `documents: list[UploadFile]` (optional, images/PDFs)

**Output:** `ClaimResponse` (JSON, Pydantic-validated)

**Errors:**
- `422 Unprocessable Entity` — validation failure (missing fields, bad types)

### `POST /api/claims/process-json`

**Input:** JSON body validated by `ClaimRequest` Pydantic model.

**Output:** `ClaimResponse` (JSON, Pydantic-validated)

**Errors:**
- `422 Unprocessable Entity` — invalid category enum, negative amount, bad date format

### `GET /api/claims/{claim_id}`

**Output:** `{"claim": dict, "decision": dict | null}`

**Errors:**
- `404 Not Found` — claim_id not in database

### `GET /api/claims?member_id=X&limit=50`

**Output:** `{"claims": list[dict]}`

---

## Configuration Sources

### `load_policy() -> dict`

Reads `policy_terms.json`. Cached via `@lru_cache`. Contains: members, OPD categories, coverage limits, exclusions, waiting periods, fraud thresholds, network hospitals, document requirements.

### `load_pipeline_config() -> dict`

Reads `app/pipeline_config.json`. Cached via `@lru_cache`. Contains: OCR thresholds, classification keywords, extraction patterns, cross-validation thresholds, decision scoring, financial defaults, policy matching config.

Both are the **only** data access layer. No agent reads configuration from anywhere else.
