"""Shared test fixtures — loads test case data from JSON files."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
TEST_CASES_FILE = ROOT / "test_cases.json"
TEST_CASES_EXTENDED_FILE = ROOT / "test_cases_extended.json"


def _load_cases():
    cases = {}
    for path in (TEST_CASES_FILE, TEST_CASES_EXTENDED_FILE):
        if path.exists():
            data = json.loads(path.read_text())
            for tc in data["test_cases"]:
                cases[tc["case_id"]] = tc
    return cases


ALL_CASES = _load_cases()


def get_case(case_id: str) -> dict:
    return ALL_CASES[case_id]


def get_input(case_id: str) -> dict:
    return ALL_CASES[case_id]["input"]


def get_expected(case_id: str) -> dict:
    return ALL_CASES[case_id]["expected"]
