"""Unit tests for financial calculations — expected values loaded from test_cases JSON."""

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from tests.conftest import get_expected, get_input
from app.utils.financial import calculate_approved_amount


def test_tc004_clean_consultation():
    """TC004: ₹1,500 consultation, 10% co-pay."""
    expected = get_expected("TC004")
    inp = get_input("TC004")
    config = {"sub_limit": 2000, "copay_percent": 10, "network_discount_percent": 20}
    result = calculate_approved_amount(
        claimed_amount=inp["claimed_amount"],
        category_config=config,
        is_network=False,
        ytd_claims_amount=inp.get("ytd_claims_amount", 0),
    )
    assert result.final_approved == float(expected["approved_amount"])


def test_tc010_network_no_sublimit():
    """TC010: Network hospital discount before co-pay, no sub-limit enforcement."""
    expected = get_expected("TC010")
    inp = get_input("TC010")
    config = {"sub_limit": 2000, "copay_percent": 10, "network_discount_percent": 20}
    result = calculate_approved_amount(
        claimed_amount=inp["claimed_amount"],
        category_config=config,
        is_network=True,
        ytd_claims_amount=inp.get("ytd_claims_amount", 0),
        apply_sub_limit=False,
    )
    assert result.after_network_discount == 3600.0
    assert result.final_approved == float(expected["approved_amount"])


def test_tc006_partial_dental_exclusion():
    """TC006: Root canal approved, teeth whitening excluded."""
    expected = get_expected("TC006")
    inp = get_input("TC006")
    line_items = inp["documents"][0]["content"]["line_items"]
    config = {"sub_limit": 10000, "copay_percent": 0}
    result = calculate_approved_amount(
        claimed_amount=inp["claimed_amount"],
        category_config=config,
        is_network=False,
        line_items=line_items,
        excluded_descriptions=["Teeth Whitening"],
    )
    assert result.eligible_after_exclusions == 8000.0
    assert result.final_approved == float(expected["approved_amount"])


def test_tc016_annual_limit_cap():
    """TC016: Annual limit nearly exhausted, partial approval."""
    expected = get_expected("TC016")
    inp = get_input("TC016")
    config = {"sub_limit": 50000, "copay_percent": 10, "network_discount_percent": 20}
    result = calculate_approved_amount(
        claimed_amount=inp["claimed_amount"],
        category_config=config,
        is_network=True,
        ytd_claims_amount=inp["ytd_claims_amount"],
        annual_opd_limit=50000,
    )
    assert result.after_network_discount == 3200.0
    assert result.after_annual_limit_cap == 2000.0
    assert result.final_approved == float(expected["approved_amount"])


def test_tc018_branded_drug_copay():
    """TC018: Branded drug 30% co-pay."""
    expected = get_expected("TC018")
    inp = get_input("TC018")
    config = {"sub_limit": 15000, "copay_percent": 0, "branded_drug_copay_percent": 30}
    result = calculate_approved_amount(
        claimed_amount=inp["claimed_amount"],
        category_config=config,
        is_network=False,
        is_branded_drug=True,
    )
    assert result.copay_amount == 720.0
    assert result.final_approved == float(expected["approved_amount"])


def test_tc022_sub_limit_cap():
    """TC022: Sub-limit cap enforced at Fortis (network)."""
    expected = get_expected("TC022")
    inp = get_input("TC022")
    config = {"sub_limit": 2000, "copay_percent": 10, "network_discount_percent": 20}
    result = calculate_approved_amount(
        claimed_amount=inp["claimed_amount"],
        category_config=config,
        is_network=True,
        ytd_claims_amount=inp["ytd_claims_amount"],
        apply_sub_limit=True,
    )
    assert result.after_network_discount == 3600.0
    assert result.after_sub_limit_cap == 2000.0
    assert result.final_approved == float(expected["approved_amount"])


def test_tc015_dependent_consultation():
    """TC015: Dependent claim, 10% co-pay, no sub-limit enforcement."""
    expected = get_expected("TC015")
    inp = get_input("TC015")
    config = {"sub_limit": 2000, "copay_percent": 10, "network_discount_percent": 20}
    result = calculate_approved_amount(
        claimed_amount=inp["claimed_amount"],
        category_config=config,
        is_network=False,
        apply_sub_limit=False,
    )
    assert result.final_approved == float(expected["approved_amount"])


if __name__ == "__main__":
    test_tc004_clean_consultation()
    test_tc010_network_no_sublimit()
    test_tc006_partial_dental_exclusion()
    test_tc016_annual_limit_cap()
    test_tc018_branded_drug_copay()
    test_tc022_sub_limit_cap()
    test_tc015_dependent_consultation()
    print("All financial tests passed!")
