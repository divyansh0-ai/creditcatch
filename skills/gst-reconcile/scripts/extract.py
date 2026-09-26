"""Extract structured fields from tax invoice PDFs.

Reads text-layer PDFs with pypdf (no OCR) and looks for the Rule 46 fields
by their labels: supplier and buyer GSTIN, invoice number and date, place of
supply, taxable value, the CGST/SGST/IGST lines and the invoice total.

It only accepts a value it can tie to a label on the same line ("Invoice
No: X", "Grand Total: Rs. Y"). When a layout puts labels and values in
different places, it does not guess: the row comes back with
needs_manual_parse = true and the reason, and the page's text is saved (with
its spatial layout kept) so a parser for that layout can be written.
A PDF that doesn't call itself a "Tax Invoice" (a price list, a statement of
account) comes back with looks_like_invoice = false.

CLI:
    python extract.py 'invoices/*.pdf' --text-dir text > books.json
Library:
    from extract import extract_invoice
    row = extract_invoice("invoice.pdf")
"""

import argparse
import glob
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

CUR = r"(?:INR|Rs\.?|₹)"
AMT = r"([\d,]+\.\d{2})"
GSTIN_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9])\b")
INUM_RE = re.compile(r"(?:Invoice|Inv\.?|Bill)\s*(?:No\.?|Number|#)\s*[:\-]\s*([A-Za-z0-9][A-Za-z0-9/_.\-]*)", re.I)
DATE_RE = re.compile(r"(?:Invoice|Bill)\s*Date\s*:\s*(\d{1,2}[/\-. ](?:\d{1,2}|[A-Za-z]{3})[/\-. ]\d{2,4})", re.I)
POS_RE = re.compile(r"Place of Supply\s*:\s*(?:(\d{2})\b|[^\n(]*\((\d{2})\))", re.I)
TAX_RE = re.compile(rf"\b(CGST|SGST|UTGST|IGST)\s*@?\s*([\d.]+)\s*%\s*:?\s*{CUR}\s*{AMT}", re.I)
TAXABLE_RE = re.compile(rf"(?:Taxable Value|Sub\s*Total|Taxable Amount|Total Taxable Value)\s*:?\s*{CUR}\s*{AMT}", re.I)
TOTAL_RE = re.compile(rf"(?:Invoice Total|Grand Total|Total Amount|Amount Payable|Total Invoice Value)\s*:?\s*{CUR}\s*{AMT}", re.I)
SUPPLIER_RE = re.compile(r"Original for Recipient\s*[\r\n]+([^\n]+)")
DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%d-%b-%y", "%d/%m/%y")
REQUIRED = ("supplier_gstin", "buyer_gstin", "invoice_number", "invoice_date", "place_of_supply",
            "taxable_value", "invoice_total")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_date(s: str):
    s = (s or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def page_text(path: str, layout: bool = False) -> str:
    reader = PdfReader(path)
    if layout:
        return "\n".join(p.extract_text(extraction_mode="layout") or "" for p in reader.pages)
    return "\n".join(p.extract_text() or "" for p in reader.pages)


def extract_invoice(path: str, text_dir: str | None = None) -> dict:
    text = page_text(path)
    row = {"source_file": Path(path).name, "looks_like_invoice": bool(re.search(r"\bTax\s+Invoice\b", text, re.I)),
           "supplier_name": None, "supplier_gstin": None, "buyer_gstin": None, "invoice_number": None,
           "invoice_date": None, "place_of_supply": None, "taxable_value": None, "tax_rate_pct": None,
           "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "invoice_total": None,
           "needs_manual_parse": False, "parse_warnings": []}
    if text_dir:
        out = Path(text_dir) / (Path(path).stem + ".txt")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page_text(path, layout=True), encoding="utf-8")
        row["text_file"] = str(out)
    if not text.strip():
        row["needs_manual_parse"] = True
        row["parse_warnings"].append("no text layer (scanned image?); needs OCR or manual entry")
        return row

    gstins = GSTIN_RE.findall(text)
    row["supplier_gstin"] = gstins[0] if gstins else None
    row["buyer_gstin"] = gstins[1] if len(gstins) > 1 else None
    if m := SUPPLIER_RE.search(text):
        row["supplier_name"] = m.group(1).strip()
    else:
        first = next((ln.strip() for ln in text.splitlines()
                      if ln.strip() and not re.search(r"invoice|original|duplicate|copy", ln, re.I)), None)
        row["supplier_name"] = first
    if m := INUM_RE.search(text):
        row["invoice_number"] = m.group(1).strip()
    if m := DATE_RE.search(text):
        row["invoice_date"] = parse_date(m.group(1))
    if m := POS_RE.search(text):
        row["place_of_supply"] = m.group(1) or m.group(2)
    if m := TAXABLE_RE.search(text):
        row["taxable_value"] = _num(m.group(1))
    if m := TOTAL_RE.search(text):
        row["invoice_total"] = _num(m.group(1))

    rates = set()
    for head, pct, amt in TAX_RE.findall(text):
        head = head.lower().replace("utgst", "sgst")
        row[head] = round(row[head] + _num(amt), 2)
        rates.add(float(pct) if head == "igst" else float(pct) * 2)
    if len(rates) == 1:
        row["tax_rate_pct"] = rates.pop()
    elif rates:
        row["tax_rate_pct"] = None
        row["tax_rates_pct"] = sorted(rates)

    for field in REQUIRED:
        if row[field] is None:
            row["parse_warnings"].append(f"could not read {field}")
    tax = row["cgst"] + row["sgst"] + row["igst"]
    if row["taxable_value"] is not None and row["invoice_total"] is not None:
        if row["invoice_total"] > row["taxable_value"] + 1 and tax == 0:
            row["parse_warnings"].append("could not read the tax lines")
        elif abs(row["taxable_value"] + tax - row["invoice_total"]) > 1:
            row["parse_warnings"].append(
                f"taxable {row['taxable_value']:,.2f} + tax {tax:,.2f} != total {row['invoice_total']:,.2f}")
    if row["looks_like_invoice"] and row["parse_warnings"]:
        row["needs_manual_parse"] = True
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description="Extract invoice fields from PDFs (JSON array to stdout).")
    ap.add_argument("paths", nargs="+", help="PDF files or glob patterns")
    ap.add_argument("--text-dir", help="also save each PDF's layout-preserving text here as <name>.txt")
    args = ap.parse_args(argv)
    paths = []
    for a in args.paths:
        paths.extend(sorted(glob.glob(a)) or [a])
    rows = [extract_invoice(p, args.text_dir) for p in paths]
    print(json.dumps(rows, indent=2))
    manual = [r["source_file"] for r in rows if r["needs_manual_parse"]]
    other = [r["source_file"] for r in rows if not r["looks_like_invoice"]]
    print(f"{len(rows)} PDFs: {len(rows) - len(manual) - len(other)} read, {len(manual)} need a parser "
          f"{manual}, {len(other)} are not tax invoices {other}", file=sys.stderr)


if __name__ == "__main__":
    main()
