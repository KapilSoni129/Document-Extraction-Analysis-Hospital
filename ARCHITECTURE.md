# Architecture Document

## System Overview

A multi-agent claims processing pipeline built on LangGraph that automates OPD claim decisions for Indian health insurance. The system accepts document uploads, verifies them, extracts structured data via OCR + LLM vision, applies policy rules, and produces explainable decisions with full audit traces.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          STREAMLIT UI (Frontend)                              │
│              Lightweight HTTP client → calls backend via httpx                │
└────────────────────────────────────┬─────────────────────────────────────────┘
                                     │ HTTP
┌────────────────────────────────────▼─────────────────────────────────────────┐
│                       FASTAPI SERVER (Backend)                                │
│                                                                              │
│  POST /api/claims/process     GET /api/health     GET /api/members           │
│  POST /api/claims/process-json    GET /api/claims     GET /api/claims/{id}   │
└────────────────────────────────────┬─────────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼─────────────────────────────────────────┐
│                     LANGGRAPH STATE MACHINE                                   │
│                                                                              │
│  START → intake → doc_verifier → doc_extractor → cross_validator             │
│                                        → policy_evaluator → decision_maker → END  │
│                                                                              │
│  Conditional exits:                                                          │
│  • intake: invalid member/deadline/amount → decision_maker                   │
│  • doc_verifier: wrong docs/unreadable → decision_maker                      │
│  • cross_validator: name mismatch → decision_maker                           │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Agent Pipeline

| # | Agent | Responsibility | Uses LLM? | Can Early-Exit? |
|---|-------|---------------|-----------|-----------------|
| 1 | **intake** | Validate member, check deadline, minimum amount, per-claim limit | No | Yes → REJECTED |
| 2 | **doc_verifier** | Classify docs via OCR keywords, assess readability | No (EasyOCR only) | Yes → REJECTED |
| 3 | **doc_extractor** | Extract structured fields via dual-input (OCR + Gemini Vision) | Yes (Gemini) | No |
| 4 | **cross_validator** | Verify patient name consistency across documents | No | Yes → REJECTED |
| 5 | **policy_evaluator** | Apply all policy rules: exclusions, waiting periods, limits, fraud | No | No |
| 6 | **decision_maker** | Synthesize final decision from all prior checks | No | No (terminal) |

## Data Flow

```
Claim Submission
    │
    ▼
┌─────────┐     ┌──────────────┐     ┌───────────────┐
│  Intake │────▶│ Doc Verifier │────▶│ Doc Extractor │
└─────────┘     └──────────────┘     └───────────────┘
    │ early exit      │ early exit           │
    ▼                 ▼                      ▼
┌────────────────────────────────────────────────────┐
│              ClaimProcessingState (TypedDict)        │
│                                                    │
│  member_info, documents, extracted_data,           │
│  policy_checks, fraud_signals, amount_breakdown,   │
│  trace[], component_failures[]                     │
└────────────────────────────────────────────────────┘
    │                      │                     │
    ▼                      ▼                     ▼
┌─────────────────┐  ┌──────────────────┐  ┌──────────────┐
│ Cross Validator │  │ Policy Evaluator │  │Decision Maker│
└─────────────────┘  └──────────────────┘  └──────────────┘
                                                   │
                                                   ▼
                                           ClaimResponse
                                           (decision, amount, trace)
```

## Document Extraction Strategy

Three-level fallback chain:

```
Level 1: Gemini Dual-Input (best quality)
├── EasyOCR extracts raw text from image
├── Gemini Vision sees original image
├── Both fed to single structuring prompt
└── Output: validated Pydantic model (GeminiExtractionResult)

Level 2: Gemini Lenient Parse (on validation failure)
├── Same Gemini response but with relaxed parsing
└── Cleans malformed line_items, retries validation

Level 3: Regex-Only (when Gemini unavailable)
├── Pattern matching on OCR text
└── Extracts: amounts, dates, names via regex
└── Lowest quality but always available
```

### Prompt Engineering

**Extraction prompt** (dual-input):
```
You are a medical document data extractor for Indian health insurance claims.
Document type: {doc_type}

I have two sources of information about this document:
1. OCR-extracted text (may have errors but captures printed text reliably)
2. The original document image (you can see layout, handwriting, stamps)

Use BOTH sources to extract the most accurate data. Where they conflict,
prefer what you can visually confirm in the image.
```

Key design choices in the prompt:
- **Role framing** ("Indian health insurance") focuses the model on domain-specific formats
- **Dual-source instruction** tells the model to cross-reference OCR text with visual layout
- **Conflict resolution rule** ("prefer what you can visually confirm") handles OCR errors gracefully
- **Strict output format** ("Return ONLY valid JSON, no markdown") prevents parsing failures

**Classification prompt** (vision-only):
```
Classify this medical document into exactly ONE of these types:
- PRESCRIPTION
- HOSPITAL_BILL
- LAB_REPORT
- PHARMACY_BILL
- DISCHARGE_SUMMARY
- UNKNOWN

Return ONLY the type name, nothing else.
```

Design: Single-word response eliminates parsing complexity. Closed set prevents hallucinated categories.

## Financial Calculation Pipeline

Order matters — changing sequence produces wrong amounts:

```
1. Filter excluded line items         → eligible_amount
2. Apply network discount (20%)       → after_discount
3. Apply category sub-limit cap       → after_sub_limit  (opt-in)
4. Apply annual OPD remaining cap     → after_annual_cap
5. Apply co-pay (10%/30% by type)     → final_approved
```

Critical: **Network discount BEFORE co-pay**. TC010 proves this:
- ₹4,500 → 20% discount → ₹3,600 → 10% co-pay → **₹3,240** (correct)
- ₹4,500 → 10% co-pay → ₹4,050 → 20% discount → ₹3,240 (same by coincidence)
- But with sub-limits: order matters for intermediate caps

## Graceful Degradation

Every agent is wrapped in try/except at the graph level:

```python
# In graph.py — each agent node:
try:
    result = agent_function(state)
except Exception as e:
    state["component_failures"].append({"agent": name, "error": str(e)})
    # Continue pipeline with degraded state
```

Decision maker applies **-0.2 confidence penalty per failed component**:
- 0 failures: confidence 1.0
- 1 failure: confidence 0.8
- 2+ failures: routes to MANUAL_REVIEW

## Observability

### Trace Structure

Every agent appends trace steps:
```json
{
    "agent": "policy_evaluator",
    "timestamp": "2025-03-15T10:30:00Z",
    "action": "check_exclusions",
    "status": "SUCCESS",
    "duration_ms": 12,
    "input_summary": {"diagnosis": "Morbid Obesity BMI 37"},
    "output_summary": {"excluded": true, "matched_exclusion": "Obesity and weight loss programs"}
}
```

### OpenTelemetry Integration

```python
# app/services/tracing.py
@contextmanager
def pipeline_span(claim_id):
    """Root span for entire pipeline execution."""

@contextmanager
def agent_span(agent_name, claim_id):
    """Child span per agent — shows waterfall in Jaeger/Tempo."""
```

Configure via environment:
- `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` → sends to Jaeger/Tempo/Datadog
- `OTEL_TRACE_CONSOLE=1` → prints spans to stdout for debugging

## Configuration Architecture

Zero hardcoded values. Two config files serve as flat-file databases:

| File | Owner | Changes When |
|------|-------|-------------|
| `policy_terms.json` | Business/Ops | Policy renews, new exclusion added, member joins |
| `app/pipeline_config.json` | Engineering | OCR threshold tuned, new keyword added, scoring adjusted |

Both loaded via `@lru_cache` — read once, served from memory. Swapping to PostgreSQL later means changing two functions, nothing else.

## Deployment Architecture

```
┌─────────────────────────────────┐     ┌──────────────────────────────────────┐
│  Streamlit Community Cloud      │     │  Hugging Face Spaces (Docker)        │
│                                 │     │  16GB RAM, 2 vCPU                    │
│  UI only — httpx calls to API   │────▶│  FastAPI + LangGraph + EasyOCR       │
│  No torch/easyocr loaded        │     │  + Gemini Vision + SQLite            │
│                                 │     │  Port 7860                           │
└─────────────────────────────────┘     └──────────────────────────────────────┘
```

Why HF Spaces over Render: Render's free tier (512MB) OOMs when loading PyTorch + EasyOCR model. HF Spaces provides 16GB — purpose-built for ML workloads.

## Scaling Considerations (10x Load)

| Current | At Scale |
|---------|----------|
| SQLite (claims.db) | PostgreSQL with read replicas |
| Sync pipeline | Celery + Redis task queue, webhook on completion |
| Single instance | Horizontal scaling behind load balancer |
| JSON config files | Config service or database with version history |
| In-process OCR | Dedicated OCR microservice with GPU |
| Gemini Flash | Rate-limited — add request queue + retry with backoff |

## Limitations

1. **No batch processing** — each claim processed individually (fine for demo, not for bulk imports)
2. **SQLite is single-writer** — concurrent requests queue at DB level
3. **EasyOCR on CPU is slow** (~15-30s per document) — GPU would be 10x faster
4. **No authentication** — API is open (would add JWT/API keys in production)
5. **Cold start on HF Spaces** — ~1min if Space has been sleeping 48hr
