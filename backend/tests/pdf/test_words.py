from decimal import Decimal as D

import pytest

from apps.documents.pdf.words import integer_in_words, rupees_in_words


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (0, "Zero"),
        (7, "Seven"),
        (19, "Nineteen"),
        (20, "Twenty"),
        (45, "Forty-Five"),
        (100, "One Hundred"),
        (101, "One Hundred One"),
        (1000, "One Thousand"),
        (11800, "Eleven Thousand Eight Hundred"),
        (100000, "One Lakh"),
        (341020, "Three Lakh Forty-One Thousand Twenty"),
        (9999999, "Ninety-Nine Lakh Ninety-Nine Thousand Nine Hundred Ninety-Nine"),
        (10000000, "One Crore"),
        (123456789, "Twelve Crore Thirty-Four Lakh Fifty-Six Thousand Seven Hundred Eighty-Nine"),
        (1000000000, "One Hundred Crore"),
    ],
)
def test_indian_grouping(n: int, words: str) -> None:
    assert integer_in_words(n) == words


def test_rupees_and_paise() -> None:
    assert (
        rupees_in_words(D("323680.00"))
        == "Rupees Three Lakh Twenty-Three Thousand Six Hundred Eighty Only"
    )
    assert rupees_in_words(D("118.5")) == "Rupees One Hundred Eighteen and Paise Fifty Only"
    assert rupees_in_words(D("0.05")) == "Rupees Zero and Paise Five Only"
