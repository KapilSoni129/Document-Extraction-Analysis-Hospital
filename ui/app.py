"""Streamlit UI for claims processing system."""

import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.graph import process_claim
from app.config import load_policy

st.set_page_config(page_title="Plum Claims Processing", layout="wide")
st.title("Plum OPD Claims Processing System")

policy = load_policy()
members = policy["members"]
categories = policy["opd_categories"]

tab1, tab2 = st.tabs(["Submit Claim", "View Decision"])

with tab1:
    st.header("Submit a New Claim")

    col1, col2 = st.columns(2)
    with col1:
        member_options = {f"{m['member_id']} - {m['name']}": m["member_id"] for m in members}
        selected_member = st.selectbox("Member", options=list(member_options.keys()))
        member_id = member_options[selected_member]

        category_options = [k.upper() for k, v in categories.items() if v.get("covered", True)]
        claim_category = st.selectbox("Claim Category", options=category_options)

        claimed_amount = st.number_input("Claimed Amount (₹)", min_value=0.0, value=1500.0, step=100.0)

    with col2:
        treatment_date = st.date_input("Treatment Date").isoformat()
        submission_date = st.date_input("Submission Date").isoformat()
        hospital_name = st.text_input("Hospital Name (optional)")
        ytd_claims = st.number_input("YTD Claims Amount (₹)", min_value=0.0, value=0.0, step=500.0)

    uploaded_files = st.file_uploader("Upload Documents (PDF/JPG)", accept_multiple_files=True, type=["pdf", "jpg", "jpeg", "png"])

    if st.button("Process Claim", type="primary"):
        with st.spinner("Processing claim..."):
            doc_list = []
            if uploaded_files:
                import tempfile, os
                for f in uploaded_files:
                    suffix = os.path.splitext(f.name)[1]
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(f.read())
                        doc_list.append({"file_name": f.name, "file_path": tmp.name})

            state = {
                "claim_id": f"UI_{member_id}_{treatment_date}",
                "member_id": member_id,
                "policy_id": "PLUM_GHI_2024",
                "claim_category": claim_category,
                "treatment_date": treatment_date,
                "submission_date": submission_date,
                "claimed_amount": claimed_amount,
                "hospital_name": hospital_name or None,
                "ytd_claims_amount": ytd_claims,
                "claims_history": [],
                "documents": doc_list,
                "simulate_component_failure": False,
            }

            result = process_claim(state)
            st.session_state["last_result"] = result
            st.session_state["last_state"] = state

            # Clean up temp files
            for doc in doc_list:
                try:
                    import os
                    os.unlink(doc["file_path"])
                except OSError:
                    pass

        # Display results
        decision = result.get("decision", "UNKNOWN")
        color_map = {"APPROVED": "green", "PARTIAL": "orange", "REJECTED": "red", "MANUAL_REVIEW": "blue"}
        color = color_map.get(decision, "gray")

        st.markdown(f"### Decision: :{color}[{decision}]")
        st.metric("Approved Amount", f"₹{result.get('approved_amount', 0):,.0f}")
        st.metric("Confidence", f"{result.get('confidence_score', 0):.0%}")
        st.info(result.get("message", ""))

        if result.get("amount_breakdown"):
            st.subheader("Amount Breakdown")
            bd = result["amount_breakdown"]
            breakdown_data = {
                "Step": ["Claimed", "After Exclusions", "After Network Discount",
                         "After Sub-Limit", "After Annual Cap", "Co-pay Deducted", "Final Approved"],
                "Amount (₹)": [
                    bd["original_claimed"], bd["eligible_after_exclusions"],
                    bd["after_network_discount"], bd["after_sub_limit_cap"],
                    bd["after_annual_limit_cap"], f"-{bd['copay_amount']}", bd["final_approved"]
                ]
            }
            st.table(breakdown_data)

        if result.get("fraud_signals"):
            st.subheader("Fraud Signals")
            for sig in result["fraud_signals"]:
                st.warning(f"**{sig['signal']}**: {sig['details']}")

        if result.get("policy_checks"):
            st.subheader("Policy Checks")
            for check in result["policy_checks"]:
                icon = "✓" if check.get("passed") else "✗"
                st.write(f"{icon} **{check['rule_name']}** — {check['details']}")

with tab2:
    st.header("Decision Trace Viewer")

    if "last_result" in st.session_state:
        result = st.session_state["last_result"]
        trace = result.get("trace", [])

        if trace:
            st.subheader(f"Pipeline Trace ({len(trace)} steps)")
            for i, step in enumerate(trace):
                with st.expander(f"Step {i+1}: [{step['agent']}] {step['action']} ({step['duration_ms']}ms)"):
                    st.json({"input": step.get("input_summary"), "output": step.get("output_summary")})

        if result.get("component_failures"):
            st.subheader("Component Failures")
            for fail in result["component_failures"]:
                st.error(f"**{fail['agent']}**: {fail['error']}")

        st.subheader("Full Result JSON")
        st.json(result)
    else:
        st.info("Submit a claim first to see the decision trace here.")
