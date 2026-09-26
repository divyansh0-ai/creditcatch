"""Extract structured fields from a tax invoice PDF.

Works on text-layer PDFs (no OCR). Reads with pypdf and pulls fields with
regexes matched against Indian tax-invoice conventions (Rule 46 fields):
supplier name/GSTIN, invoice number/date, place of supply, taxable value,
tax rate and the CGST/SGST/IGST split.

CLI:
    python extract.py invoice.pdf            # one file, JSON to stdout
    python extract.py invoices/*.pdf          # many files, JSON array
Library:
    from extract import extract_invoice
    row = extract_invoice("invoice.pdf")
"""

import glob
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

GSTIN_RE = re.compile(r"GSTIN:?\s*([0-9]{2}[A-Z0-9]{13})")
INUM_RE = re.compile(r"Invoice\s*No:?\s*([^\n]+)", re.I)
DATE_RE = re.compile(r"Invoice\s*Date:?\s*(\d{2}/\d{2}/\d{4})", re.I)
POS_RE = re.compile(r"Place of Supply:.*?\((\d{2})\)")
RATE_RE = re.compile(r"(CGST|SGST|IGST)\s*@\s*([\d.]+)%\s*[\r\n]?INR\s*([\d,]+\.\d{2})", re.I)
TAXABLE_RE = re.compile(r"Taxable Value\s*[\r\n]?INR\s*([\d,]+\.\d{2})", re.I)
TOTAL_RE = re.compile(r"Invoice Total\s*[\r\n]?INR\s*([\d,]+\.\d{2})", re.I)
SUPPLIER_RE = re.compile(r"Original for Recipient\s*[\r\n]+([^\n]+)")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def extract_invoice(path: str) -> dict:
    text = PdfReader(path).pages[0].extract_text() or ""
    gstins = GSTIN_RE.findall(text)
    m_inum = INUM_RE.search(text)
    m_date = DATE_RE.search(text)
    m_pos = POS_RE.search(text)
    m_taxable = TAXABLE_RE.search(text)
    m_total = TOTAL_RE.search(text)
    m_supplier = SUPPLIER_RE.search(text)

    tax = {"cgst": 0.0, "sgst": 0.0, "igst": 0.0}
    rate = 0.0
    for head, pct, amt in RATE_RE.findall(text):
        tax[head.lower()] = _num(amt)
        rate += float(pct)

    d = None
    if m_date:
        dd, mm, yyyy = m_date.group(1).split("/")
        d = f"{yyyy}-{mm}-{dd}"

    row = {
        "source_file": Path(path).name,
        "supplier_name": m_supplier.group(1).strip() if m_supplier else None,
        "supplier_gstin": gstins[0] if gstins else None,
        "buyer_gstin": gstins[1] if len(gstins) > 1 else None,
        "invoice_number": m_inum.group(1).strip() if m_inum else None,
        "invoice_date": d,
        "place_of_supply": m_pos.group(1) if m_pos else None,
        "taxable_value": _num(m_taxable.group(1)) if m_taxable else None,
        "tax_rate_pct": round(rate, 2) if rate else None,
        "cgst": tax["cgst"], "sgst": tax["sgst"], "igst": tax["igst"],
        "invoice_total": _num(m_total.group(1)) if m_total else None,
        "parse_warnings": [],
    }
    for field in ("supplier_gstin", "invoice_number", "invoice_date", "taxable_value", "invoice_total"):
        if row[field] is None:
            row["parse_warnings"].append(f"could not read {field}")
    return row


def main(argv):
    paths = []
    for a in argv:
        paths.extend(sorted(glob.glob(a)) or [a])
    rows = [extract_invoice(p) for p in paths]
    print(json.dumps(rows if len(rows) != 1 else rows[0], indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
