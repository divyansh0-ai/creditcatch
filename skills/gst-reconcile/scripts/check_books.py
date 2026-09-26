"""Check a books.json before reconciling it.

Every row must be a readable tax invoice whose numbers add up: taxable value
plus tax equals the total, CGST equals SGST, IGST isn't mixed with
CGST/SGST, and the tax matches the rate. Run it after extract.py and again
after merging rows from any parser you wrote. It exits 1 and lists every
problem if anything is off, so a mis-read invoice never reaches the
reconciliation.

    python check_books.py books.json
"""

import json
import re
import sys
from datetime import datetime

GSTIN_SHAPE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]$")
TOL = 1.0


def check_row(r: dict) -> list[str]:
    out = []
    if r.get("looks_like_invoice") is False:
        return ["not a tax invoice; remove it from books.json"]
    if r.get("needs_manual_parse"):
        out.append("still marked needs_manual_parse")
    for f in ("supplier_gstin", "invoice_number", "invoice_date", "taxable_value", "invoice_total"):
        if r.get(f) in (None, ""):
            out.append(f"missing {f}")
    for f in ("supplier_gstin", "buyer_gstin"):
        if r.get(f) and not GSTIN_SHAPE.match(r[f]):
            out.append(f"{f} {r[f]!r} is not shaped like a GSTIN")
    if r.get("invoice_date"):
        try:
            datetime.strptime(r["invoice_date"], "%Y-%m-%d")
        except ValueError:
            out.append(f"invoice_date {r['invoice_date']!r} is not YYYY-MM-DD")
    if r.get("place_of_supply") and not re.fullmatch(r"\d{2}", str(r["place_of_supply"])):
        out.append(f"place_of_supply {r['place_of_supply']!r} should be a 2-digit state code")
    cgst, sgst, igst = (float(r.get(k) or 0) for k in ("cgst", "sgst", "igst"))
    tax = cgst + sgst + igst
    if igst and (cgst or sgst):
        out.append("has both IGST and CGST/SGST")
    if abs(cgst - sgst) > TOL:
        out.append(f"CGST {cgst:,.2f} != SGST {sgst:,.2f}")
    taxable, total = r.get("taxable_value"), r.get("invoice_total")
    if taxable is not None and total is not None and abs(float(taxable) + tax - float(total)) > TOL:
        out.append(f"taxable {float(taxable):,.2f} + tax {tax:,.2f} != total {float(total):,.2f}")
    rate = r.get("tax_rate_pct")
    if rate and taxable is not None and abs(float(taxable) * float(rate) / 100 - tax) > TOL:
        out.append(f"tax {tax:,.2f} is not {rate}% of {float(taxable):,.2f}")
    return out


def main(path: str) -> int:
    rows = json.load(open(path))
    bad = 0
    for r in rows:
        problems = check_row(r)
        if problems:
            bad += 1
            print(f"FAIL {r.get('source_file')}: " + "; ".join(problems))
    print(f"{len(rows) - bad} of {len(rows)} rows OK" + ("" if not bad else f", {bad} to fix"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "books.json"))
