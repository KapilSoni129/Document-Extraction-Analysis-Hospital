"""LangGraph StateGraph: orchestrates the claims processing pipeline."""

import asyncio
import time

from langgraph.graph import END, StateGraph

from app.agents.cross_validator import cross_validator
from app.agents.decision_maker import decision_maker
from app.agents.doc_extractor import doc_extractor
from app.agents.doc_verifier import doc_verifier
from app.agents.intake import intake_agent
from app.agents.policy_evaluator import policy_evaluator
from app.logging_config import get_logger
from app.models.state import ClaimProcessingState
from app.services.tracing import agent_span, pipeline_span

logger = get_logger("pipeline")


def _wrap_agent(agent_fn, agent_name):
    """Wrap an agent function with graceful degradation and tracing."""

    def wrapped(state: ClaimProcessingState) -> dict:
        claim_id = state.get("claim_id", "unknown")
        if state.get("simulate_component_failure") and agent_name == "doc_verifier":
            logger.warning("[%s] Simulated failure for %s", claim_id, agent_name)
            failures = state.get("component_failures", [])
            failures.append({"agent": agent_name, "error": "Simulated component failure"})
            return {"component_failures": failures}
        with agent_span(agent_name, claim_id=claim_id) as span:
            try:
                logger.debug("[%s] Running agent: %s", claim_id, agent_name)
                result = agent_fn(state)
                span.set_attribute("agent.status", "SUCCESS")
                logger.debug("[%s] Agent %s completed", claim_id, agent_name)
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_attribute("agent.status", "FAILED")
                logger.error("[%s] Agent %s failed: %s", claim_id, agent_name, str(e))
                failures = state.get("component_failures", [])
                failures.append({"agent": agent_name, "error": str(e)})
                return {"component_failures": failures}

    return wrapped


def _route_after_intake(state: ClaimProcessingState) -> str:
    if state.get("early_rejection"):
        return "decision_maker"
    return "doc_verifier"


def _route_after_doc_verifier(state: ClaimProcessingState) -> str:
    doc_errors = state.get("doc_errors", [])
    critical_errors = [
        e for e in doc_errors if e["type"] in ("WRONG_DOCUMENT_TYPE", "UNREADABLE_DOCUMENT", "NO_DOCUMENTS")
    ]
    if critical_errors:
        return "decision_maker"
    return "doc_extractor"


def _route_after_cross_validator(state: ClaimProcessingState) -> str:
    if not state.get("cross_validation_passed", True):
        return "decision_maker"
    return "policy_evaluator"


def build_graph() -> StateGraph:
    graph = StateGraph(ClaimProcessingState)

    graph.add_node("intake", _wrap_agent(intake_agent, "intake"))
    graph.add_node("doc_verifier", _wrap_agent(doc_verifier, "doc_verifier"))
    graph.add_node("doc_extractor", _wrap_agent(doc_extractor, "doc_extractor"))
    graph.add_node("cross_validator", _wrap_agent(cross_validator, "cross_validator"))
    graph.add_node("policy_evaluator", _wrap_agent(policy_evaluator, "policy_evaluator"))
    graph.add_node("decision_maker", _wrap_agent(decision_maker, "decision_maker"))

    graph.set_entry_point("intake")

    graph.add_conditional_edges(
        "intake", _route_after_intake, {"decision_maker": "decision_maker", "doc_verifier": "doc_verifier"}
    )
    graph.add_conditional_edges(
        "doc_verifier",
        _route_after_doc_verifier,
        {"decision_maker": "decision_maker", "doc_extractor": "doc_extractor"},
    )
    graph.add_edge("doc_extractor", "cross_validator")
    graph.add_conditional_edges(
        "cross_validator",
        _route_after_cross_validator,
        {"decision_maker": "decision_maker", "policy_evaluator": "policy_evaluator"},
    )
    graph.add_edge("policy_evaluator", "decision_maker")
    graph.add_edge("decision_maker", END)

    return graph


def get_compiled_graph():
    return build_graph().compile()


def process_claim(initial_state: dict) -> dict:
    """Run the full claims processing pipeline (synchronous)."""
    logger.info(
        "Processing claim %s | member=%s category=%s amount=%.0f",
        initial_state.get("claim_id"),
        initial_state.get("member_id"),
        initial_state.get("claim_category"),
        initial_state.get("claimed_amount", 0),
    )
    defaults = {
        "claim_id": None,
        "member_id": None,
        "policy_id": "PLUM_GHI_2024",
        "claim_category": None,
        "treatment_date": None,
        "submission_date": None,
        "claimed_amount": 0,
        "hospital_name": None,
        "ytd_claims_amount": 0,
        "claims_history": [],
        "documents": [],
        "simulate_component_failure": False,
        "trace": [],
        "extracted_data": [],
        "component_failures": [],
    }
    defaults.update(initial_state)

    app = get_compiled_graph()
    result = app.invoke(defaults)
    logger.info(
        "Claim %s completed | decision=%s amount=%.0f confidence=%.2f",
        result.get("claim_id", initial_state.get("claim_id")),
        result.get("decision"),
        result.get("approved_amount", 0),
        result.get("confidence_score", 0),
    )
    return result


async def async_process_claim(initial_state: dict) -> dict:
    """Run the full claims processing pipeline (async for API use)."""
    start = time.time()
    defaults = {
        "claim_id": None,
        "member_id": None,
        "policy_id": "PLUM_GHI_2024",
        "claim_category": None,
        "treatment_date": None,
        "submission_date": None,
        "claimed_amount": 0,
        "hospital_name": None,
        "ytd_claims_amount": 0,
        "claims_history": [],
        "documents": [],
        "simulate_component_failure": False,
        "trace": [],
        "extracted_data": [],
        "component_failures": [],
    }
    defaults.update(initial_state)

    with pipeline_span(defaults.get("claim_id", "unknown")) as span:
        compiled_app = get_compiled_graph()
        result = await asyncio.to_thread(compiled_app.invoke, defaults)
        elapsed = int((time.time() - start) * 1000)
        span.set_attribute("pipeline.duration_ms", elapsed)
        span.set_attribute("pipeline.decision", result.get("decision", "unknown"))
        result["_processing_time_ms"] = elapsed
    return result
