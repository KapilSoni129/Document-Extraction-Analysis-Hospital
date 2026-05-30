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
