from datetime import date


def days_between(d1: date | str, d2: date | str) -> int:
    if isinstance(d1, str):
        d1 = date.fromisoformat(d1)
    if isinstance(d2, str):
        d2 = date.fromisoformat(d2)
    return (d2 - d1).days


def is_within_waiting_period(join_date: str, treatment_date: str, waiting_days: int) -> bool:
    elapsed = days_between(join_date, treatment_date)
    return elapsed < waiting_days


def eligibility_date(join_date: str, waiting_days: int) -> date:
    from datetime import timedelta

    d = date.fromisoformat(join_date)
    return d + timedelta(days=waiting_days)
