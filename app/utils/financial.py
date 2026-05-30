from dataclasses import dataclass

from app.config import load_pipeline_config


@dataclass
class AmountBreakdown:
    original_claimed: float
    eligible_after_exclusions: float
    after_network_discount: float
    discount_amount: float
    after_sub_limit_cap: float
    sub_limit_applied: float | None
    after_annual_limit_cap: float
    annual_limit_remaining: float | None
    copay_amount: float
    copay_type: str
    final_approved: float


def calculate_approved_amount(
    claimed_amount: float,
    category_config: dict,
    is_network: bool = False,
    ytd_claims_amount: float = 0.0,
    annual_opd_limit: float | None = None,
    line_items: list[dict] | None = None,
    excluded_descriptions: list[str] | None = None,
    is_branded_drug: bool = False,
    apply_sub_limit: bool = False,
) -> AmountBreakdown:
    """
    Calculate the approved amount following the correct order:
    1. Filter excluded line items
    2. Apply network discount (BEFORE co-pay)
    3. Apply category sub-limit cap
    4. Apply annual OPD remaining cap
    5. Apply co-pay
    """
    financial_config = load_pipeline_config()["financial"]
    annual_opd_limit = annual_opd_limit or financial_config["default_annual_opd_limit"]

    # Step 1: Filter excluded line items
    if excluded_descriptions and line_items:
        eligible = sum(
            li["amount"]
            for li in line_items
            if not any(exc.lower() in li["description"].lower() for exc in excluded_descriptions)
        )
    else:
        eligible = claimed_amount

    # Step 2: Network discount
    discount_pct = category_config.get("network_discount_percent", 0) if is_network else 0
    discount_amount = eligible * (discount_pct / 100)
    after_discount = eligible - discount_amount

    # Step 3: Sub-limit cap (only when explicitly enforced)
    sub_limit = category_config.get("sub_limit", float("inf")) if apply_sub_limit else float("inf")
    after_sub_limit = min(after_discount, sub_limit)
    sub_limit_applied = sub_limit if after_discount > sub_limit else None

    # Step 4: Annual OPD remaining cap
    remaining_annual = max(0, annual_opd_limit - ytd_claims_amount)
    after_annual_cap = min(after_sub_limit, remaining_annual)
    annual_remaining = remaining_annual if after_sub_limit > remaining_annual else None

    # Step 5: Co-pay
    if is_branded_drug:
        copay_pct = category_config.get(
            "branded_drug_copay_percent", financial_config["default_branded_drug_copay_percent"]
        )
        copay_type = f"branded_drug_{copay_pct}%"
    else:
        copay_pct = category_config.get("copay_percent", 0)
        copay_type = f"category_copay_{copay_pct}%"
    copay_amount = after_annual_cap * (copay_pct / 100)
    final = after_annual_cap - copay_amount

    return AmountBreakdown(
        original_claimed=claimed_amount,
        eligible_after_exclusions=eligible,
        after_network_discount=after_discount,
        discount_amount=discount_amount,
        after_sub_limit_cap=after_sub_limit,
        sub_limit_applied=sub_limit_applied,
        after_annual_limit_cap=after_annual_cap,
        annual_limit_remaining=annual_remaining,
        copay_amount=copay_amount,
        copay_type=copay_type,
        final_approved=final,
    )
