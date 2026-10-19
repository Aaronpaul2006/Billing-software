"""Indian identifiers: GST state codes, GSTIN (with check digit), PAN, PIN code.

Pure functions, no Django: used by serializers and services alike.
"""

import re

# GST state / UT codes (first two digits of a GSTIN).
STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "25": "Daman and Diu (before 2020)",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "28": "Andhra Pradesh (before 2014)",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory",
}

_GSTIN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_PAN = re.compile(r"^[A-Z]{3}[ABCFGHJLPT][A-Z][0-9]{4}[A-Z]$")  # 4th letter: holder type
_PIN = re.compile(r"^[1-9][0-9]{5}$")
_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_char(first14: str) -> str:
    """The GSTIN check character (mod-36, alternating weights 1 and 2)."""
    total = 0
    for i, ch in enumerate(first14):
        product = _ALPHABET.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _ALPHABET[(36 - total % 36) % 36]


def gstin_problem(gstin: str) -> str | None:
    """Why `gstin` is invalid, or None if it is valid."""
    if not _GSTIN.match(gstin):
        return "A GSTIN has 15 characters: 2-digit state code, PAN, entity code, Z, check digit."
    if gstin[:2] not in STATE_CODES:
        return f"{gstin[:2]} is not a GST state code."
    if gstin[2:12] != gstin[2:12].upper() or not is_valid_pan(gstin[2:12]):
        return "The PAN inside this GSTIN is not valid."
    if gstin_check_char(gstin[:14]) != gstin[14]:
        return "The check digit does not match: there is a typo in this GSTIN."
    return None


def is_valid_pan(pan: str) -> bool:
    return bool(_PAN.match(pan))


def is_valid_pincode(pin: str) -> bool:
    return bool(_PIN.match(pin))
