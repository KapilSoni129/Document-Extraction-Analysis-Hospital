# Thought Process — Build Narrative

This document narrates how the system was built, step by step. At each decision point, I describe what options I considered, why I chose what I chose, and what I rejected (and why).

---

## Step 1: Analyzing the Assignment

First thing I did was read the assignment front-to-back twice. Key observations:

1. **The scoring weights tell you where to spend time:** System Design (30%) + Engineering Quality (25%) = 55% of the score is about how well the backend is designed. Observability (20%) means traces are critical. AI Integration (15%) and Document Verification (10%) are important but secondary. This told me: spend 70% of time on backend architecture, 20% on OCR/LLM, 10% on UI.

2. **"What did you consider and reject?"** — They explicitly want to see decision-making process, not just the final product. Every choice needs documented alternatives.

3. **12 test cases define success** — before writing any code, I need to understand exactly what each test case expects. The system must produce correct decisions for all 12.

4. **"Handle failures gracefully"** — TC011 specifically tests this. The system cannot crash when a component fails.

5. **Multi-agent = bonus points** — this immediately pointed me toward LangGraph or CrewAI.

---

## Step 2: Analyzing the Test Cases

I read every test case carefully and categorized them:

**Document-problem cases (stop early, don't decide):** TC001 (wrong doc), TC002 (unreadable), TC003 (patient mismatch)

**Policy-logic cases (make a decision):** TC004-TC012

I noticed the test cases exercise very specific financial calculations:
- TC004: ₹1,500 → 10% co-pay → ₹1,350
- TC010: ₹4,500 → 20% network discount → ₹3,600 → 10% co-pay → ₹3,240

This told me: **the financial calculation order is critical and testable**. I need to get this exactly right.

I also noticed gaps — the 12 cases don't cover vision claims, dependents, annual limits, branded drugs, or submission deadlines. I created 10 additional test cases (TC013-TC022) to validate these untested rules.

---

## Step 3: Choosing the Architecture

### Decision: Multi-Agent Pipeline

I needed to choose how to orchestrate the processing stages.

**Options I considered:**

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| LangGraph StateGraph | Typed state, conditional routing, graph visualization, bonus points | Learning curve | **CHOSEN** |
| CrewAI | "Multi-agent" branding, higher-level API | Designed for conversational agents — agents "discuss" which is wrong for a deterministic pipeline | Rejected |
| AutoGen (Microsoft) | Good for complex agent interactions | Heavy dependency, too complex for linear pipeline | Rejected |
| Plain Python functions | Simplest, no dependencies | No conditional routing, no built-in error handling, no "multi-agent" bonus | Rejected |
| Celery + message queue | True async, scalable | Needs Redis/RabbitMQ — overkill for sync eval | Rejected |

**Why LangGraph won:** The pipeline is fundamentally a state machine — claim state flows through stages, with conditional exits at each stage. LangGraph models this perfectly. Each node is an "agent" (satisfies the bonus). The TypedDict state gives type safety. Conditional edges give early-termination for document errors.

### Decision: 6 Agents

I then decided how many agents to have and what each does.

**Options:**
- 3 agents (doc processing → policy → decision) — too coarse, hard to test individually
- **6 agents** (intake, doc_verifier, doc_extractor, cross_validator, policy_evaluator, decision_maker) — clear single responsibility each
- 8+ agents (separate fraud agent, separate amount calculator, etc.) — over-engineered, more complexity for no gain

**Why 6:** Each agent has one job. Four of six are pure logic (no LLM) — this means 4/6 agents are fully deterministic and testable without API keys. The two LLM agents (doc_verifier, doc_extractor) handle what requires vision/AI.

---

## Step 4: Data Architecture — JSON as the Database

Before choosing specific tools, I needed to decide how data flows through the system. There are two kinds of data:

1. **Business rules** — what the policy covers, who the members are, what's excluded
2. **System behavior** — how aggressively to flag unreadable documents, what confidence penalty to apply, what regex patterns to use for extraction

Both need to be configurable without code changes. In production claims systems, these change frequently — a new exclusion gets added, a threshold needs tuning, a network hospital joins.

### The Decision: Two JSON Files as Flat-File Database

| File | Role | What it stores |
|------|------|----------------|
| `policy_terms.json` | Business rules DB | Members, categories, limits, exclusions, waiting periods, fraud thresholds, network hospitals, document requirements |
| `app/pipeline_config.json` | System config DB | OCR thresholds, extraction patterns, classification keywords, similarity thresholds, confidence scoring, financial defaults |

**Why this split:** Business rules change when the policy changes (annually). System config changes when the engineering team tunes behavior (weekly during development). Different owners, different change frequencies.

### Options I Considered

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Two JSON files** | Simple, versionable in git, no deps, directly maps to DB tables later | No concurrent writes, no runtime schema validation | **CHOSEN** |
| SQLite | Real DB, SQL queries | Overkill for read-heavy config, harder to diff in git, adds complexity | Rejected |
| Environment variables | Standard for secrets | Terrible for nested config (keyword lists, regex patterns, member rosters) | Rejected — only used for API keys in `.env` |
| YAML | More readable than JSON | Extra `pyyaml` dependency, no real advantage for machine-consumed config | Rejected |
| Hardcoded Python constants | Zero indirection | Can't change without code edits, can't be managed by non-engineers, drift between files | Rejected |
| PostgreSQL / Redis from day 1 | Production-ready | External dependency, overkill for assignment — adds setup friction for evaluator | Rejected for now |

### The Key Design Principle

All config is loaded through exactly two functions: `load_policy()` and `load_pipeline_config()`. Both use `@lru_cache` so the JSON is read once and served from memory thereafter. **No agent, no utility, no service ever reads a threshold from anywhere else.**

This means:
- Python code contains ONLY control flow logic — zero magic numbers
- An ops engineer can change any threshold by editing JSON — no Python needed
- Swapping JSON for PostgreSQL later means changing these two functions — nothing else
- Tests run against the same config files production uses — no config drift

---

## Step 5: Choosing the Tech Stack

### LLM: Gemini 3.5 Flash

| Option | Cost | Vision? | Verdict |
|--------|------|---------|---------|
| **Gemini 3.5 Flash** | Free | Yes | **CHOSEN** |
| GPT-4o | $5/1M tokens | Yes | Rejected — costs money; can't run eval repeatedly for free |
| GPT-4o-mini | $0.15/1M tokens | Yes | Rejected — still paid |
| Claude 3.5 Sonnet | $3/1M tokens | Yes | Rejected — paid |
| Llama 3.2 Vision (local) | Free | Yes | Rejected — needs 16GB+ RAM, slow on CPU, complex setup |
| Tesseract only | Free | No | Rejected — can't interpret context, just OCR |

**Why Gemini:** Free tier with generous limits. Strong vision for reading medical docs. Supports structured JSON output. Fast. The evaluator can run the system without paying anything.

### OCR: EasyOCR

| Option | Install | Offline? | Indian Languages? | Verdict |
|--------|---------|----------|-------------------|---------|
| **EasyOCR** | `pip install` | Yes | Hindi, Tamil, Telugu, etc. | **CHOSEN** |
| Tesseract | System package | Yes | Yes (with trained data) | Rejected — poor on handwritten text, needs OS-level install |
| PaddleOCR | `pip install` (large) | Yes | Yes | Rejected — larger footprint, less familiar to most reviewers |
| Google Cloud Vision | API call | No | Yes | Rejected — paid, needs GCP credentials |

**Why EasyOCR:** Pure pip install (no system deps). Works offline. Handles Indian scripts. Combined with Gemini for interpretation — EasyOCR does raw text extraction, Gemini does structured understanding.

### Backend: FastAPI

| Option | Why chosen/rejected |
|--------|-------------------|
| **FastAPI** | Auto-generated OpenAPI docs, Pydantic validation, modern Python | **CHOSEN** |
| Flask | No auto docs, not async-native | Rejected |
| Django | Massive overhead for 3 endpoints | Rejected |

### Frontend: Streamlit

| Option | Dev Time | Why chosen/rejected |
|--------|----------|-------------------|
| **Streamlit** | ~2 hours | Built-in file upload, forms, JSON viewer — assignment requires UI, not beautiful UI | **CHOSEN** |
| React | ~8 hours | Full control but 4x the dev time — scoring weight is 0% for frontend beauty | Rejected |
| Gradio | ~2 hours | ML-focused, less flexible for form-heavy UIs | Rejected |
| No UI | 0 hours | Assignment explicitly requires running application with UI | Not an option |

---

## Step 6: Planning the Foundation

Now I know the architecture. Before writing any agent logic, I need the foundation:

1. **Pydantic models** — typed state schema for LangGraph, request/response models for the API
2. **Config loader** (`app/config.py`) — the two cached functions that everything reads from
3. **Financial calculator** (`app/utils/financial.py`) — the most testable unit, critical to get right first

### Financial Calculation Order (Critical Discovery)

From analyzing TC004 and TC010, the calculation order must be:

```
1. Filter excluded line items → eligible_amount
2. Apply network discount (20% if network hospital) → after_discount
3. Apply category sub-limit cap → after_sub_limit
4. Apply annual OPD remaining cap → after_annual_cap
5. Apply co-pay (10% consultation, 30% branded drugs, etc.) → final_approved
```

Network discount BEFORE co-pay. Sub-limit caps BEFORE co-pay. Getting this wrong means TC010 fails.

### Sub-limit Ambiguity

CONSULTATION has a ₹2,000 sub-limit in `policy_terms.json`. If always enforced, TC010 (₹4,500 at Apollo) would cap to ₹2,000 → ₹1,800. But TC010 expects ₹3,240.

**Options:**
- Always enforce sub-limit → TC010 fails
- Never enforce sub-limit → extended test cases fail
- **Make it opt-in (`apply_sub_limit` flag)** → both pass

I'll implement opt-in because TC010 is from Plum's assignment (authoritative).

---

## Step 6b: Implementing the Foundation

### Pydantic Models (`app/models/`)

- `state.py` — LangGraph `TypedDict` with all pipeline state fields (input, intake results, doc verification, extraction, policy checks, decision, trace)
- `claim.py` — `ClaimRequest` (validated API input), `ClaimResponse` (typed API output with trace steps and amount breakdown)

### Config Loader (`app/config.py`)

Two `@lru_cache` functions — `load_policy()` and `load_pipeline_config()` — are the only entry points for all configuration. Helper functions (`get_member`, `get_category_config`, `is_network_hospital`, `get_exclusions`, etc.) provide typed access to specific policy sections.

### Pipeline Config (`app/pipeline_config.json`)

All system-tuning parameters in one file: OCR thresholds, document classification keywords, extraction regex patterns, cross-validation similarity thresholds, confidence scoring parameters, exclusion matching rules, and financial defaults.

### Financial Calculator (`app/utils/financial.py`)

Returns a typed `AmountBreakdown` dataclass showing every step:
```
original → eligible (after exclusions) → after discount → after sub-limit → after annual cap → after co-pay → final
```

All defaults come from `pipeline_config.json`. The function accepts `apply_sub_limit=False` (default) to handle the TC010/TC022 ambiguity.

### Date Utils (`app/utils/date_utils.py`)

Waiting period math: `is_within_waiting_period()` and `eligibility_date()`.

### Extended Test Cases (`test_cases_extended.json`)

10 additional test cases (TC013-TC022) covering: vision claims, dependents, annual limit cap, initial waiting period, branded drug co-pay, submission deadline, below minimum amount, monthly limit fraud, and sub-limit enforcement.

### Unit Tests

- `test_config.py` — 15 tests verifying policy loading, member lookups, network hospital detection, waiting period resolution, exclusion access
- `test_financial.py` — 7 tests verifying exact amounts for TC004, TC006, TC010, TC015, TC016, TC018, TC022

All expected values loaded from JSON files — single source of truth, no hardcoded assertions.

---

## Step 6c: Intake Agent (`app/agents/intake.py`)

The intake agent validates basic eligibility before any document processing. Checks: member exists, category valid, minimum amount (₹500), submission deadline (30 days), initial 30-day waiting period.

**Per-claim limit placement — a hard problem:**

TC008 expects ₹7,500 to be rejected (per-claim limit ₹5,000). But TC006 (₹12,000 dental) and TC012 (₹8,000 consultation) expect the system to reach policy-level checks for exclusions.

**Options I tried:**
1. **Hard reject at intake** → TC006 and TC012 never reach policy evaluator. Wrong.
2. **No per-claim check anywhere** → TC008 doesn't get rejected. Wrong.
3. **Check in policy evaluator, after exclusion checks** → TC008 gets rejected (no exclusion applies), TC006 gets PARTIAL (exclusion found first), TC012 gets rejected for exclusion (found first). Correct!

I went with option 3. The per-claim limit is a "last resort" — it only fires when no more specific rule (exclusion, pre-auth, line-item exclusion) already handles the claim.

## Step 6d: Policy Evaluator (`app/agents/policy_evaluator.py`)

The most complex agent. Runs these checks in order:
1. Condition-specific waiting period (e.g., 90 days for diabetes)
2. Exclusions (obesity, cosmetic, etc.)
3. Pre-authorization (high-value diagnostics)
4. Line-item exclusions (teeth whitening, LASIK)
5. Per-claim limit (only if nothing above triggered)
6. Fraud signals (same-day count, monthly count)
7. Financial calculation (only if no hard rejects)

**Exclusion matching — a subtle bug:**

My first implementation used naive keyword matching: if any word >3 chars from the exclusion appears in the diagnosis, it's a match. This caused "Dental Caries" to match "Cosmetic dental procedures" because "dental" appears in both.

**Options I considered:**
- Require majority of keywords to match → "Morbid Obesity" only matches 1 of 3 keywords in "Obesity and weight loss programs" — misses a true positive
- Exact substring match → too strict
- LLM-based matching → too slow for a deterministic check
- **Filter out generic context words** and match only on specific medical terms → correctly rejects "Dental Caries" while matching "Morbid Obesity". The generic words list and minimum keyword length live in `pipeline_config.json["policy_matching"]`

## Step 8: Decision Maker and Graph Wiring

### Decision Maker Logic

Synthesizes all prior state into a final decision:

```
early_rejection → REJECTED
doc_errors → None (action required, not a claim decision)
cross_validation failure → None (action required)
hard_reject policy checks → REJECTED
fraud_signals → MANUAL_REVIEW
line-item exclusions OR limit caps → PARTIAL
everything else → APPROVED
```

**APPROVED vs PARTIAL — a subtle distinction:**

Every claim with co-pay has `approved_amount < claimed_amount`. If I used `approved < claimed` as the PARTIAL signal, every single approved claim becomes PARTIAL.

**My decision:** PARTIAL only when there's a *structural* reduction — items excluded, limits hit. Co-pay and network discount are normal policy mechanics → still APPROVED.

### Graceful Degradation

Each agent wrapped in try/except at the graph level. On failure: log to `component_failures`, skip agent, continue. Decision maker applies -0.2 confidence penalty per failed component.

### LangGraph Wiring (`app/agents/graph.py`)

Connected all agents with conditional edges:

```
intake → [early_rejection?] → decision_maker
         [else] → doc_verifier → [doc_errors?] → decision_maker
                                  [else] → doc_extractor → cross_validator → [mismatch?] → decision_maker
                                                                              [else] → policy_evaluator → decision_maker
```

This ensures document-problem cases (TC001-TC003) stop early without wasting LLM calls.

### Tests at This Stage

- `test_intake.py` — 9 tests: valid claims pass, member not found, below minimum, deadline exceeded, waiting periods
- `test_policy_evaluator.py` — 10 tests: exclusions, pre-auth, fraud signals, per-claim limit, financial calculations
- `test_integration.py` — 10 tests: full pipeline end-to-end for key scenarios (approval, rejection, partial, manual review)

---

## Step 7: Services, API, and UI (Day 2-3)

### Step 7a: OCR Service (`app/services/ocr.py`)

EasyOCR wrapper that extracts text from images and PDFs. Returns structured output: `raw_text`, `lines` (grouped by y-position), `fields` (with per-field confidence and bounding boxes), and `avg_confidence`. Also provides `assess_readability()` which rates documents as GOOD/DEGRADED/UNREADABLE based on configurable thresholds from `pipeline_config.json`.

PDF support via PyMuPDF: renders first page to image at configurable DPI, then runs OCR on the rasterized image.

### Step 7b: Gemini Service (`app/services/gemini.py`)

Uses `google.genai` SDK with Gemini 3.5 Flash (free tier, multimodal). Three functions:

1. **`extract_with_vision()`** — Dual-input: sends both OCR text AND the raw image as a `Part.from_bytes()` object. Gemini sees the layout, handwriting, and stamps while also getting reliable character-level text from EasyOCR. Returns a validated `GeminiExtractionResult` (Pydantic model).

2. **`classify_document_vision()`** — Sends just the image for document type classification (PRESCRIPTION, HOSPITAL_BILL, etc.).

3. **`interpret_document()`** — Text-only fallback when no image is available.

**Fallback chain:** Gemini validated → lenient parse (coerce types) → None (extraction skipped, confidence penalized).

### Step 7c: SQLite Storage (`app/services/storage.py`)

Persistent storage for claims and decisions:
- `claims` table: input metadata (member, category, amount, dates)
- `decisions` table: full output (decision, amounts, policy checks, trace as JSON)
- Auto-creates schema on first connection
- Clean interface: `save_claim()`, `save_decision()`, `get_claim()`, `get_decision()`, `list_claims()`

### Step 7d: FastAPI Endpoints (`app/main.py`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/claims/process` | Multipart form with file uploads (production) |
| POST | `/api/claims/process-json` | JSON body (eval/testing) |
| GET | `/api/claims/{claim_id}` | Retrieve past decision |
| GET | `/api/claims` | List claims with optional member filter |
| GET | `/api/members` | Member dropdown data |
| GET | `/api/policy/categories` | Category list |
| GET | `/api/health` | Health check (includes Gemini availability) |

Both process endpoints: run async pipeline → persist to SQLite → return typed ClaimResponse.

### Step 7e: Streamlit UI (`ui/app.py`)

Single-page app with claim submission form and decision viewer. Member dropdown, category selection, amount input, date picker, file upload. Results show decision with color coding, amount breakdown table, expandable trace steps, and fraud signals.

### Step 7f: Test Document Generation (`generate_test_documents.py`)

Generates mock medical documents for all 22 test cases using `fpdf2` (PDFs) and `Pillow` (JPGs). Includes configurable degradation (blur kernel) for TC002's unreadable document test. Each test case gets its own directory under `test_documents/`.

---

## Step 11: Evaluation

I needed a way to run all 22 test cases in one command and get a clear pass/fail with full details. I wanted something a non-engineer (or an interviewer) could open and immediately understand.

### Eval Design

The eval runner (`eval/run_eval_excel.py`) does one thing: loads all test cases from both JSON files, builds the pipeline state for each, runs it through `process_claim()`, compares against expected outcomes, and exports everything to Excel.

**Why Excel?** Three reasons:
1. The assignment asks for an eval report — a spreadsheet is immediately scannable (color-code PASS/FAIL, sort by decision type, filter failures)
2. Non-engineers (ops team, reviewers) can open it without any tooling
3. Four sheets give different levels of detail without cluttering a single view

### Output: `eval/eval_report.xlsx`

| Sheet | What it shows |
|-------|---------------|
| **Results** | One row per test case: expected vs actual decision, amounts, confidence, rejection reasons, trace path, duration, pass/fail |
| **Summary** | Pass rate, decision distribution (how many APPROVED/REJECTED/PARTIAL/MANUAL_REVIEW), average processing time |
| **Trace Details** | Every pipeline step for every case — agent, action, input/output summaries, duration |
| **Amount Breakdown** | Financial calculation steps for claims that reached the calculator — original → exclusions → discount → sub-limit → annual cap → co-pay → final |

### Result: **22/22 (100% pass rate)**

| Category | Cases | Result |
|----------|-------|--------|
| Document verification (TC001-TC003) | 3 | All pass (early stop, specific error messages) |
| Policy logic (TC004-TC012) | 9 | All pass (correct decisions and amounts) |
| Extended scenarios (TC013-TC022) | 10 | All pass |

Also produces `eval/eval_report.json` for programmatic consumption. Both regeneratable with a single command.
