import json
from functools import lru_cache
from pathlib import Path

POLICY_PATH = Path(__file__).parent.parent / "policy_terms.json"
PIPELINE_CONFIG_PATH = Path(__file__).parent / "pipeline_config.json"


@lru_cache(maxsize=1)
def load_policy() -> dict:
    with open(POLICY_PATH) as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_pipeline_config() -> dict:
    with open(PIPELINE_CONFIG_PATH) as f:
        return json.load(f)


def get_member(member_id: str) -> dict | None:
    policy = load_policy()
    for member in policy["members"]:
        if member["member_id"] == member_id:
            return member
    return None


def get_primary_member(member_id: str) -> dict | None:
    """For dependents, get the primary member."""
    member = get_member(member_id)
    if not member:
        return None
    if "primary_member_id" in member:
        return get_member(member["primary_member_id"])
    return member


def get_category_config(category: str) -> dict | None:
    policy = load_policy()
    key = category.lower()
    return policy["opd_categories"].get(key)


def get_document_requirements(category: str) -> dict:
    policy = load_policy()
    return policy["document_requirements"].get(category.upper(), {"required": [], "optional": []})


def is_network_hospital(name: str) -> bool:
    if not name:
        return False
    policy = load_policy()
    name_lower = name.lower()
    return any(h.lower() in name_lower or name_lower in h.lower() for h in policy["network_hospitals"])


def get_waiting_period_days(diagnosis: str) -> int | None:
    """Check if a diagnosis triggers a condition-specific waiting period."""
    policy = load_policy()
    pipeline_config = load_pipeline_config()
    conditions = policy["waiting_periods"]["specific_conditions"]
    diagnosis_lower = diagnosis.lower()
    keyword_map = pipeline_config["policy_matching"]["diagnosis_keyword_map"]
    for condition_key, keywords in keyword_map.items():
        if any(kw in diagnosis_lower for kw in keywords):
            return conditions.get(condition_key)
    return None


def get_exclusions() -> dict:
    policy = load_policy()
    return policy["exclusions"]


def get_fraud_thresholds() -> dict:
    policy = load_policy()
    return policy["fraud_thresholds"]
