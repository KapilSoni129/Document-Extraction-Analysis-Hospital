"""Streamlit UI for claims processing system — calls FastAPI backend via HTTP."""

import os

import httpx
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "https://plum-claims-api.onrender.com")

st.set_page_config(page_title="Plum Claims Processing", layout="wide")
st.title("Plum OPD Claims Processing System")


@st.cache_data(ttl=300)
def fetch_members():
    resp = httpx.get(f"{API_BASE}/api/members", timeout=90)
    if resp.status_code != 200 or "application/json" not in resp.headers.get("content-type", ""):
        return None
    return resp.json()["members"]


@st.cache_data(ttl=300)
def fetch_categories():
    resp = httpx.get(f"{API_BASE}/api/policy/categories", timeout=90)
    if resp.status_code != 200 or "application/json" not in resp.headers.get("content-type", ""):
        return None
    return resp.json()["categories"]


try:
    members = fetch_members()
    categories = fetch_categories()
except (httpx.ConnectError, httpx.TimeoutException):
    st.warning("⏳ Backend is waking up (free tier cold start). Please refresh in 30 seconds.")
    st.stop()
except Exception as e:
    st.error(f"API connection error: {e}")
    st.stop()

if not members or not categories:
    st.warning("⏳ Backend is starting up. Please refresh in 30 seconds.")
    st.stop()

tab1, tab2 = st.tabs(["Submit Claim", "View Decision"])

with tab1:
    st.header("Submit a New Claim")

    col1, col2 = st.columns(2)
    with col1:
        member_options = {f"{m['id']} - {m['name']}": m["id"] for m in members}
        selected_member = st.selectbox("Member", options=list(member_options.keys()))
        member_id = member_options[selected_member]

        category_options = [c["id"] for c in categories if c.get("covered", True)]
        claim_category = st.selectbox("Claim Category", options=category_options)

        claimed_amount = st.number_input("Claimed Amount (₹)", min_value=0.0, value=1500.0, step=100.0)

    with col2:
        treatment_date = st.date_input("Treatment Date").isoformat()
        submission_date = st.date_input("Submission Date").isoformat()
        hospital_name = st.text_input("Hospital Name (optional)")
        ytd_claims = st.number_input("YTD Claims Amount (₹)", min_value=0.0, value=0.0, step=500.0)

    uploaded_files = st.file_uploader("Upload Documents (PDF/JPG)", accept_multiple_files=True, type=["pdf", "jpg", "jpeg", "png"])

    if st.button("Process Claim", type="primary"):
        with st.spinner("Processing claim (may take 30s on cold start)..."):
            files = []
            if uploaded_files:
                for f in uploaded_files:
                    files.append(("documents", (f.name, f.read(), f.type)))

            data = {
                "member_id": member_id,
                "claim_category": claim_category,
                "treatment_date": treatment_date,
                "submission_date": submission_date,
                "claimed_amount": str(claimed_amount),
                "hospital_name": hospital_name or "",
                "ytd_claims_amount": str(ytd_claims),
            }

            try:
                resp = httpx.post(
                    f"{API_BASE}/api/claims/process",
                    data=data,
                    files=files if files else None,
                    timeout=120,
                )
                resp.raise_for_status()
                result = resp.json()
            except httpx.TimeoutException:
                st.error("Request timed out. The backend may be waking up — try again in 30s.")
                st.stop()
            except httpx.HTTPStatusError as e:
                st.error(f"API error {e.response.status_code}: {e.response.text}")
                st.stop()
            except Exception as e:
                st.error(f"Connection error: {e}")
                st.stop()

            st.session_state["last_result"] = result

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
