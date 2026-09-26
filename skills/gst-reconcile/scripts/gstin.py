"""GSTIN helpers: format check, checksum and state code.

A GSTIN has 15 characters: 2-digit state code, 10-character PAN, entity
number, the letter Z, and a check character computed with a base-36
weighted sum over the first 14 characters.

Usage from the sandbox:
    python gstin.py 29AABCS1429B1ZB 27AAACP0001A1Z5
or
    import sys; sys.path.insert(0, "/opt/tfy/skills/gst-reconcile/scripts")
    from gstin import validate
"""

import re
import sys

CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "27": "Maharashtra", "29": "Karnataka", "30": "Goa",
    "32": "Kerala", "33": "Tamil Nadu", "36": "Telangana", "37": "Andhra Pradesh",
}


def check_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = CHARSET.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return CHARSET[(36 - total % 36) % 36]


def validate(gstin: str) -> dict:
    """Return {'gstin', 'valid', 'state_code', 'state', 'reason'}."""
    g = (gstin or "").strip().upper()
    result = {"gstin": g, "valid": False, "state_code": g[:2], "state": STATES.get(g[:2]), "reason": ""}
    if not PATTERN.match(g):
        result["reason"] = "format"
    elif check_char(g[:14]) != g[14]:
        result["reason"] = f"checksum (expected {check_char(g[:14])}, found {g[14]})"
    else:
        result["valid"] = True
    return result


def make(state_code: str, pan: str, entity: str = "1") -> str:
    body = f"{state_code}{pan}{entity}Z"
    return body + check_char(body)


if __name__ == "__main__":
    import json
    print(json.dumps([validate(a) for a in sys.argv[1:]], indent=2))
