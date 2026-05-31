# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Health Insurance Claims Processing System for the Plum AI Engineer assignment. Multi-agent pipeline that automates OPD claim decisions for Indian employee health benefits — accepts document uploads, verifies them, extracts structured data via OCR + LLM, applies policy rules, and produces explainable decisions.

**Stack:** FastAPI + Streamlit + LangGraph + Gemini 3.5 Flash + EasyOCR

## Commands

```bash
# Activate venv
source venv/bin/activate

# Run tests (fast, no OCR)
python -m pytest tests/ --ignore=tests/test_ocr.py -v

# Run all tests including OCR (~35s due to model loading)
python -m pytest tests/ -v

# Run single test
python -m pytest tests/test_financial.py::test_tc004_clean_consultation -v

# Run evaluation (all 22 test cases through pipeline)
python eval/run_eval.py              # JSON report
python eval/run_eval_excel.py        # Excel report (eval/eval_report.xlsx)

# Start API server
uvicorn app.main:app --reload --port 8000

# Start Streamlit UI
streamlit run ui/app.py --server.port 8501
```

## Architecture

LangGraph StateGraph pipeline with 6 agents:
```
START → intake → doc_verifier → doc_extractor → cross_validator → policy_evaluator → decision_maker → END
```

**Conditional routing (early exits):**
- After `intake`: if member invalid / deadline exceeded / amount below minimum → decision_maker
- After `doc_verifier`: if wrong doc types / unreadable → decision_maker  
- After `cross_validator`: if patient name mismatch → decision_maker

**Graceful degradation:** Each agent wrapped in try/except. On failure: log to `component_failures`, skip agent, continue pipeline. Decision maker applies -0.2 confidence penalty per failure.

## Key Design Decisions

- **Financial calculation order:** filter exclusions → network discount → sub-limit cap (opt-in) → annual cap → co-pay. Network discount BEFORE co-pay.
- **Sub-limit enforcement:** `apply_sub_limit=False` by default (matches TC010). Set True explicitly when sub-limit should cap.
- **Per-claim limit:** checked in policy_evaluator (not intake) so exclusion/pre-auth checks take precedence. Only fires when no other rule handles the rejection.
- **Exclusion matching:** uses keyword matching with generic word filtering to avoid false positives (e.g., "dental" won't match "Dental Caries" to "Cosmetic dental procedures").
- **OCR strategy:** EasyOCR first for text extraction, then Gemini for structured interpretation (when API key available).

## Domain Context

- Policy rules live in `policy_terms.json` — never hardcode policy logic
- Test scenarios: `test_cases.json` (12 from Plum) + `test_cases_extended.json` (10 additional)
- Tests pull expected values from these JSON files (not hardcoded)
- Indian medical documents: prescriptions, hospital bills, lab reports, pharmacy bills

## Environment

Copy `.env.example` to `.env` and add your Gemini API key. The system works without it (OCR-only mode) but Gemini enables better structured extraction.
