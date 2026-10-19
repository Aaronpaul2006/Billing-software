"""GSTIN / PAN / PIN validation (apps/core/india.py)."""

import pytest

from apps.core.india import gstin_check_char, gstin_problem, is_valid_pan, is_valid_pincode


@pytest.mark.parametrize("gstin", ["27AAPFU0939F1ZV", "29AAGCB7383J1Z4"])  # published examples
def test_real_gstins_are_valid(gstin: str) -> None:
    assert gstin_problem(gstin) is None


@pytest.mark.parametrize(
    ("gstin", "reason"),
    [
        ("27AAPFU0939F1ZX", "check digit"),  # one-character typo
        ("27AAPFU0939F1Z", "15 characters"),
        ("99AAPFU0939F1ZV", "not a GST state code"),
        ("27AAPDU0939F1Z" + gstin_check_char("27AAPDU0939F1Z"), "PAN inside"),  # D: no holder
        ("27aapfu0939f1zv", "15 characters"),  # serializers upper-case first
    ],
)
def test_invalid_gstins_say_why(gstin: str, reason: str) -> None:
    problem = gstin_problem(gstin)
    assert problem is not None
    assert reason in problem


@pytest.mark.parametrize(
    ("pan", "ok"),
    [("AAPFU0939F", True), ("AAACA1234A", True), ("ABCDE1234F", False), ("AAPF0939F", False)],
)
def test_pan(pan: str, ok: bool) -> None:
    assert is_valid_pan(pan) is ok


@pytest.mark.parametrize(("pin", "ok"), [("682016", True), ("012345", False), ("68201", False)])
def test_pincode(pin: str, ok: bool) -> None:
    assert is_valid_pincode(pin) is ok
