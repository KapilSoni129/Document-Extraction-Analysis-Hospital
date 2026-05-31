---
title: Plum Claims Processing API
emoji: 🏥
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
---

# Plum Claims Processing System

Multi-agent health insurance claims processing pipeline for OPD claims. Automates claim decisions using document verification, OCR extraction, policy evaluation, and explainable decision-making.

## Quick Start

```bash
# 1. Clone and enter the project
cd Plum

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment (optional — for Gemini-powered extraction)
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# 5. Generate test documents
python generate_test_documents.py

# 6. Run tests
python -m pytest tests/ -v

# 7. Run evaluation (all 22 test cases)
python eval/run_eval_excel.py
# Output: eval/eval_report.xlsx

# 8. Start the API server
uvicorn app.main:app --reload --port 8000

# 9. Start the UI (in another terminal)
source venv/bin/activate
streamlit run ui/app.py --server.port 8501
```

## Running the System

### API Server

```bash
uvicorn app.main:app --reload --port 8000
```

Endpoints:
- `GET /api/health` — health check (includes Gemini availability status)
- `GET /api/members` — list all members
- `GET /api/policy/categories` — list claim categories
- `POST /api/claims/process` — submit claim with file uploads (async, Pydantic-validated response)
- `POST /api/claims/process-json` — submit claim as JSON (Pydantic-validated request + response)
- `GET /api/claims` — list all processed claims (with optional `?member_id=` filter)
- `GET /api/claims/{claim_id}` — retrieve a specific claim and its decision

API docs (local): http://localhost:8000/docs
**Live API docs:** https://snyder129-plum-claims-api.hf.space/docs

### Streamlit UI

```bash
streamlit run ui/app.py --server.port 8501
```

Open http://localhost:8501 — submit claims, upload documents, view decisions with full trace.

### Evaluation

```bash
# Excel report (recommended)
python eval/run_eval_excel.py
# Output: eval/eval_report.xlsx (4 sheets: Results, Summary, Trace Details, Amount Breakdown)

# JSON report
python eval/run_eval.py
# Output: eval/eval_report.json

# Run pytest suite
python -m pytest tests/ -v

# Run with OCR tests (~35s due to model loading)
python -m pytest tests/ -v

# Run single test
python -m pytest tests/test_financial.py::test_tc004_clean_consultation -v
```

## Architecture

6-agent LangGraph pipeline:

```
START → intake → doc_verifier → doc_extractor → cross_validator → policy_evaluator → decision_maker → END
```

Early exits at intake (invalid member, deadline exceeded), doc_verifier (wrong docs, unreadable), and cross_validator (patient name mismatch) route directly to decision_maker.

### Document Extraction Strategy

Dual-input approach when Gemini is available:
```
Document Image → EasyOCR → raw text
Document Image → Gemini Vision → visual understanding
Both → Gemini structuring prompt → validated structured data
```

Fallback chain: Gemini dual-input → lenient parse → regex-only from OCR text.

## Project Structure

```
app/
├── main.py                 # FastAPI entry point (async, Pydantic-validated)
├── config.py               # Policy + pipeline config loaders
├── pipeline_config.json    # All system thresholds/patterns (JSON DB)
├── agents/
│   ├── graph.py            # LangGraph StateGraph + routing + async wrapper
│   ├── intake.py           # Member validation, deadline, minimum amount
│   ├── doc_verifier.py     # Document type classification + quality
│   ├── doc_extractor.py    # Dual-input extraction (OCR + Gemini Vision)
│   ├── cross_validator.py  # Name/date consistency checks
│   ├── policy_evaluator.py # Rules engine (limits, exclusions, fraud)
│   └── decision_maker.py   # Final decision synthesis
├── services/
│   ├── ocr.py              # EasyOCR wrapper
│   ├── gemini.py           # Gemini dual-input client + validation
│   ├── storage.py          # SQLite persistent storage
│   └── tracing.py          # OpenTelemetry distributed tracing
├── models/
│   ├── state.py            # LangGraph TypedDict state
│   └── claim.py            # Pydantic request/response models
└── utils/
    ├── financial.py        # Amount calculation pipeline
    └── date_utils.py       # Waiting period math

ui/
└── app.py                  # Streamlit UI

eval/
├── run_eval.py             # JSON eval report
└── run_eval_excel.py       # Excel eval report (4 sheets)

tests/
├── conftest.py             # Shared fixtures (loads from JSON)
├── test_financial.py       # Financial calculation tests
├── test_intake.py          # Intake agent tests
├── test_policy_evaluator.py # Policy rules tests
├── test_integration.py     # Full pipeline integration tests
└── test_ocr.py             # OCR extraction tests

policy_terms.json           # Business rules (members, categories, limits)
test_cases.json             # 12 original test cases
test_cases_extended.json    # 10 additional test cases
```

## Configuration

All configuration lives in JSON files — zero hardcoded values in Python:

| File | Purpose |
|------|---------|
| `policy_terms.json` | Business rules: members, coverage, exclusions, limits, fraud thresholds |
| `app/pipeline_config.json` | System behavior: OCR thresholds, extraction patterns, confidence scoring |
| `.env` | Secrets + optional integrations (Gemini API key, OTEL endpoint) |

To tune the system (e.g., change quality threshold, add classification keywords), edit the JSON files — no code changes needed.

### Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `GEMINI_API_KEY` | Optional | Enables Gemini Vision dual-input extraction |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Optional | Send traces to Jaeger/Tempo/Datadog |
| `OTEL_TRACE_CONSOLE` | Optional | Print traces to stdout (set to `1`) |

### Persistent Storage

Claims and decisions are stored in `claims.db` (SQLite, auto-created on first request). Retrieve past decisions via `GET /api/claims/{claim_id}`.

## Requirements

- Python 3.11+
- No external services required (works offline with EasyOCR + regex extraction)
- Optional: Gemini API key for dual-input Vision extraction
- Optional: OTLP endpoint for distributed tracing (Jaeger, Tempo, Datadog)

## Deployment

### Live API (Hugging Face Spaces)

The FastAPI backend is deployed on Hugging Face Spaces (Docker, 16GB RAM):

- **Live API:** https://snyder129-plum-claims-api.hf.space
- **Interactive Docs (Swagger):** https://snyder129-plum-claims-api.hf.space/docs
- **Health Check:** https://snyder129-plum-claims-api.hf.space/api/health

> Note: Free tier sleeps after 48hr of inactivity. First request after sleep takes ~1min (Docker cold start).

### Streamlit UI (Streamlit Community Cloud)

The Streamlit frontend is deployed on Streamlit Community Cloud and calls the HF Spaces API via HTTP.

To deploy yourself:
1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Connect your GitHub account
3. Select this repo → Branch: `main` → Main file: `ui/app.py`
4. Add `GEMINI_API_KEY` in Advanced Settings → Secrets
5. Click Deploy

## Test Results

22/22 test cases passing (100% pass rate). Run `python eval/run_eval_excel.py` to verify.
