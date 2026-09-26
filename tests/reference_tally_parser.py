"""A parser for the Tally-style invoice layout, written the way the agent is
asked to write one in the sandbox (SKILL.md step 2b). The tests use it to
prove that layout is parseable from extract.py's saved text; the agent does
not get this file and has to write its own.

    python tests/reference_tally_parser.py text/<name>.txt <name>.pdf
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "gst-reconcile" / "scripts"))
from extract import parse_date  # noqa: E402
from gstin import STATES  # noqa: E402

AMT = re.compile(r"[\d,]+\.\d{2}")


def value_below(lines, label):
    for i, line in enumerate(lines):
        col = line.find(label)
        if col >= 0:
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    return nxt[col:].split()[0] if len(nxt) > col and nxt[col:].strip() else None
    return None


def parse(text: str, source_file: str) -> dict:
    lines = text.splitlines()
    gstins = re.findall(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b", text)
    pos_name = re.search(r"Place of Supply\s*:\s*([A-Za-z ]+)", text).group(1).strip()
    pos = next(code for code, name in STATES.items() if name.lower() == pos_name.lower())
    tax = {"cgst": 0.0, "sgst": 0.0, "igst": 0.0}
    rates = set()
    for head, rate, amt in re.findall(r"\b(CGST|SGST|IGST) @ ([\d.]+)\s+.*?([\d,]+\.\d{2})\s*$", text, re.M):
        tax[head.lower()] += float(amt.replace(",", ""))
        rates.add(float(rate) * (1 if head == "IGST" else 2))
    total = float(AMT.findall(next(l for l in lines if re.match(r"^\s+Total\s", l)))[-1].replace(",", ""))
    taxable = round(total - sum(tax.values()), 2)
    return {"source_file": source_file, "looks_like_invoice": True,
            "supplier_name": next(l for l in lines if l.strip() and "Tax Invoice" not in l).split("  ")[0].strip(),
            "supplier_gstin": gstins[0], "buyer_gstin": gstins[1],
            "invoice_number": value_below(lines, "Invoice No."),
            "invoice_date": parse_date(value_below(lines, "Dated")),
            "place_of_supply": pos, "taxable_value": taxable,
            "tax_rate_pct": rates.pop() if len(rates) == 1 else None,
            **{k: round(v, 2) for k, v in tax.items()}, "invoice_total": total,
            "needs_manual_parse": False, "parse_warnings": []}


if __name__ == "__main__":
    print(json.dumps(parse(Path(sys.argv[1]).read_text(encoding="utf-8"), sys.argv[2]), indent=2))
