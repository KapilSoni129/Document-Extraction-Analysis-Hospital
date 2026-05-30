"""Tests for config.py — policy loading and lookups."""

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from app.config import (
    get_category_config,
    get_document_requirements,
    get_exclusions,
    get_fraud_thresholds,
    get_member,
    get_primary_member,
    get_waiting_period_days,
    is_network_hospital,
    load_policy,
)


def test_load_policy():
    policy = load_policy()
    assert policy["policy_id"] == "PLUM_GHI_2024"
    assert policy["coverage"]["per_claim_limit"] == 5000
    assert policy["coverage"]["annual_opd_limit"] == 50000


def test_get_member_exists():
    member = get_member("EMP001")
    assert member is not None
    assert member["name"] == "Rajesh Kumar"
    assert member["join_date"] == "2024-04-01"


def test_get_member_not_found():
    assert get_member("EMP999") is None


def test_get_dependent():
    dep = get_member("DEP001")
    assert dep is not None
    assert dep["name"] == "Sunita Kumar"
    assert dep["relationship"] == "SPOUSE"


def test_get_primary_member_for_dependent():
    primary = get_primary_member("DEP001")
    assert primary is not None
    assert primary["member_id"] == "EMP001"
    assert primary["name"] == "Rajesh Kumar"


def test_get_primary_member_for_employee():
    primary = get_primary_member("EMP001")
    assert primary["member_id"] == "EMP001"


def test_get_category_config():
    config = get_category_config("CONSULTATION")
    assert config["copay_percent"] == 10
    assert config["network_discount_percent"] == 20
    assert config["sub_limit"] == 2000


def test_get_category_config_pharmacy():
    config = get_category_config("PHARMACY")
    assert config["branded_drug_copay_percent"] == 30
    assert config["sub_limit"] == 15000


def test_get_category_config_invalid():
    assert get_category_config("INVALID") is None


def test_get_document_requirements():
    reqs = get_document_requirements("CONSULTATION")
    assert "PRESCRIPTION" in reqs["required"]
    assert "HOSPITAL_BILL" in reqs["required"]


def test_get_document_requirements_pharmacy():
    reqs = get_document_requirements("PHARMACY")
    assert "PRESCRIPTION" in reqs["required"]
    assert "PHARMACY_BILL" in reqs["required"]


def test_is_network_hospital():
    assert is_network_hospital("Apollo Hospitals") is True
    assert is_network_hospital("Fortis Healthcare") is True
    assert is_network_hospital("Random Clinic") is False
    assert is_network_hospital("") is False
    assert is_network_hospital(None) is False


def test_get_waiting_period_days():
    assert get_waiting_period_days("Type 2 Diabetes Mellitus") == 90
    assert get_waiting_period_days("Hypertension") == 90
    assert get_waiting_period_days("Morbid Obesity - BMI 37") == 365
    assert get_waiting_period_days("Viral Fever") is None
    assert get_waiting_period_days("Acute Bronchitis") is None


def test_get_exclusions():
    exc = get_exclusions()
    assert "Bariatric surgery" in exc["conditions"]
    assert "Teeth whitening" in exc["dental_exclusions"]
    assert "LASIK" in exc["vision_exclusions"]


def test_get_fraud_thresholds():
    th = get_fraud_thresholds()
    assert th["same_day_claims_limit"] == 2
    assert th["monthly_claims_limit"] == 6
