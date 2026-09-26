"""Generate CreditCatch demo data.

Writes, under data/demo/:
  invoices/*.pdf          15 purchase invoices for August 2026
  emails.json             the 16 emails that carry them (one is a forwarded duplicate)
  portal/GSTR2B_082026.json  GSTR-2B for the buyer, in the GST portal's JSON layout
  vendor_master.csv       the buyer's vendor list (GSTIN, contact alias)
  company.json            the buyer
and tests/answer_key.json with the problems planted in the data.

Every GSTIN, PAN, company and amount here is synthetic. Output is deterministic.
"""

import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "gst-reconcile" / "scripts"))
from gstin import STATES, make  # noqa: E402

OUT = ROOT / "data" / "demo"
PERIOD = "082026"

COMPANY = {
    "name": "Namma Bakes Pvt Ltd",
    "gstin": make("29", "AAHCN4821K"),
    "address": "14, 3rd Cross, Jayanagar 4th Block, Bengaluru 560011",
    "state_code": "29",
}

VENDORS = [
    # slug, name, state, PAN, address
    ("shreepack", "Shree Packaging Pvt Ltd", "29", "AAKCS5512M", "Plot 22, Peenya Industrial Area, Bengaluru 560058"),
    ("kaveriflour", "Kaveri Flour Mills", "29", "AAJFK7730Q", "KIADB Hebbal, Mysuru 570016"),
    ("deccandairy", "Deccan Dairy Products Pvt Ltd", "29", "AAGCD2204R", "88, Hosur Road, Bengaluru 560068"),
    ("malnadspice", "Malnad Spices & Co", "29", "AAQFM6619L", "IG Road, Chikkamagaluru 577101"),
    ("punebakeq", "Pune Bakery Equipment Pvt Ltd", "27", "AAFCP3348H", "Bhosari MIDC, Pune 411026"),
    ("blrlogistics", "Bengaluru Logistics Services", "29", "AAVFB9027D", "Yeshwanthpur, Bengaluru 560022"),
    ("sunrisesugar", "Sunrise Sugar Traders", "29", "AAMFS4410C", "VV Nagar, Mandya 571401"),
    ("cleanco", "CleanCo Facility Services Pvt Ltd", "29", "AADCC8156E", "HSR Layout, Bengaluru 560102"),
]
VENDOR = {v[0]: {"slug": v[0], "name": v[1], "state_code": v[2], "gstin": make(v[2], v[3]), "address": v[4]} for v in VENDORS}

# Invoices as they exist in the buyer's inbox (the "books").
# lines: (description, hsn/sac, qty, unit, rate)
INVOICES = [
    ("shreepack", "SP/26-27/0412", "2026-08-04", 18, [("5-ply corrugated cake boxes 10x10", "4819", 2000, "pcs", 25)]),
    ("shreepack", "SP/26-27/0419", "2026-08-18", 18, [("5-ply corrugated cake boxes 10x10", "4819", 10000, "pcs", 25)]),
    ("shreepack", "SP/26-27/0431", "2026-08-28", 18, [("Printed bread bags 1 kg", "3923", 1500, "pcs", 25)]),
    ("kaveriflour", "KFM-118", "2026-08-06", 5, [("Maida, 50 kg bag", "1101", 40, "bags", 1850)]),
    ("kaveriflour", "KFM-131", "2026-08-22", 5, [("Maida, 50 kg bag", "1101", 30, "bags", 1850)]),
    ("deccandairy", "DDP/0871", "2026-08-09", 12, [("Unsalted white butter", "0405", 400, "kg", 480)]),
    ("deccandairy", "DDP/0902", "2026-08-23", 12, [("Unsalted white butter", "0405", 350, "kg", 480)]),
    ("deccandairy", "DDP/0934", "2026-08-30", 12, [("Unsalted white butter", "0405", 200, "kg", 480)]),
    ("malnadspice", "MS/0823", "2026-08-12", 5, [("Cardamom and cinnamon blend", "0910", 300, "kg", 400)]),
    ("malnadspice", "MS/0839", "2026-08-26", 5, [("Cardamom and cinnamon blend", "0910", 150, "kg", 400)]),
    ("punebakeq", "PBE/26/0057", "2026-08-14", 18, [("Two-deck electric baking oven", "8417", 1, "unit", 420000)]),
    ("blrlogistics", "BLS/2608/112", "2026-08-08", 18, [("Local delivery services, 1-15 Aug", "9968", 1, "lot", 38000)]),
    ("blrlogistics", "BLS/2608/131", "2026-08-29", 18, [("Local delivery services, 16-31 Aug", "9968", 1, "lot", 41500)]),
    ("sunrisesugar", "SST/761", "2026-08-11", 5, [("Refined sugar, 50 kg bag", "1701", 90, "bags", 2100)]),
    ("cleanco", "CFS/AUG/044", "2026-08-31", 18, [("Kitchen deep cleaning, August", "9985", 1, "month", 85000)]),
]

# Only in GSTR-2B: the supplier filed it but the buyer never received it.
ONLY_IN_2B = [("sunrisesugar", "SST/774", "2026-08-25", 5, [("Refined sugar, 50 kg bag", "1701", 50, "bags", 2100)])]

# How GSTR-2B differs from the books for specific invoices.
TWEAKS_2B = {
    "SP/26-27/0419": {"taxable": 205000},          # supplier reported a lower value
    "KFM-118": {"inum": "KFM/2026-27/118"},         # same invoice, different number format
    "MS/0823": {"missing": True},                   # supplier never filed it
}
# How the printed invoice differs from what the rules require.
INVOICE_DEFECTS = {
    "PBE/26/0057": "cgst_sgst_on_interstate",       # Maharashtra supplier charged CGST+SGST to a Karnataka buyer
    "CFS/AUG/044": "gstin_typo",                    # supplier GSTIN printed with a wrong character
}
DUPLICATE_EMAIL = "DDP/0902"


def money(x: float) -> str:
    return f"{x:,.2f}"


def taxable_of(lines) -> int:
    return sum(q * r for _, _, q, _, r in lines)


def taxes(taxable: float, rate: int, interstate: bool) -> dict:
    tax = round(taxable * rate / 100, 2)
    if interstate:
        return {"igst": tax, "cgst": 0.0, "sgst": 0.0}
    half = round(tax / 2, 2)
    return {"igst": 0.0, "cgst": half, "sgst": half}


def typo(gstin: str) -> str:
    # Swap two adjacent PAN digits; the checksum no longer matches.
    chars = list(gstin)
    chars[7], chars[8] = chars[8], chars[7]
    if chars[7] == chars[8]:
        chars[9] = "0" if chars[9] != "0" else "1"
    return "".join(chars)


def safe(inum: str) -> str:
    return inum.replace("/", "-")


def draw_invoice(path: Path, v: dict, inum: str, inv_date: str, rate: int, lines, printed_gstin: str, tax: dict):
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    c.setTitle(f"Tax Invoice {inum}")
    w, h = A4
    y = h - 50
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y, "TAX INVOICE")
    c.setFont("Helvetica", 9)
    c.drawRightString(w - 40, y, "Original for Recipient")
    y -= 28
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, v["name"])
    c.setFont("Helvetica", 9)
    y -= 14
    c.drawString(40, y, v["address"])
    y -= 13
    c.drawString(40, y, f"GSTIN: {printed_gstin}")
    y -= 13
    c.drawString(40, y, f"State: {STATES[v['state_code']]} ({v['state_code']})")

    d = datetime.strptime(inv_date, "%Y-%m-%d").strftime("%d/%m/%Y")
    c.drawString(360, h - 78, f"Invoice No: {inum}")
    c.drawString(360, h - 91, f"Invoice Date: {d}")
    c.drawString(360, h - 104, "Reverse Charge: No")

    y -= 30
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "Bill To")
    c.setFont("Helvetica", 9)
    y -= 14
    c.drawString(40, y, COMPANY["name"])
    y -= 13
    c.drawString(40, y, COMPANY["address"])
    y -= 13
    c.drawString(40, y, f"GSTIN: {COMPANY['gstin']}")
    y -= 13
    c.drawString(40, y, f"Place of Supply: {STATES[COMPANY['state_code']]} ({COMPANY['state_code']})")

    y -= 30
    cols = [40, 250, 310, 370, 440]
    c.setFont("Helvetica-Bold", 9)
    for x, t in zip(cols, ["Description", "HSN/SAC", "Qty", "Rate (INR)", "Taxable Value (INR)"]):
        c.drawString(x, y, t)
    c.line(40, y - 4, w - 40, y - 4)
    c.setFont("Helvetica", 9)
    for desc, hsn, qty, unit, r in lines:
        y -= 16
        c.drawString(cols[0], y, desc)
        c.drawString(cols[1], y, hsn)
        c.drawString(cols[2], y, f"{qty} {unit}")
        c.drawString(cols[3], y, money(r))
        c.drawString(cols[4], y, money(qty * r))
    c.line(40, y - 6, w - 40, y - 6)

    taxable = taxable_of(lines)
    y -= 24
    rows = [("Taxable Value", taxable)]
    if tax["igst"]:
        rows.append((f"IGST @ {rate}%", tax["igst"]))
    else:
        rows.append((f"CGST @ {rate / 2:g}%", tax["cgst"]))
        rows.append((f"SGST @ {rate / 2:g}%", tax["sgst"]))
    total = taxable + tax["igst"] + tax["cgst"] + tax["sgst"]
    rows.append(("Invoice Total", total))
    for label, amt in rows:
        c.setFont("Helvetica-Bold" if label == "Invoice Total" else "Helvetica", 9)
        c.drawString(330, y, label)
        c.drawRightString(w - 40, y, f"INR {money(amt)}")
        y -= 14

    y -= 20
    c.setFont("Helvetica", 8)
    c.drawString(40, y, "Payment terms: 30 days. This is a computer generated invoice.")
    c.drawString(40, y - 11, f"For {v['name']} - Authorised Signatory")
    c.showPage()
    c.save()
    return total


def main():
    (OUT / "invoices").mkdir(parents=True, exist_ok=True)
    (OUT / "portal").mkdir(parents=True, exist_ok=True)
    for old in (OUT / "invoices").glob("*.pdf"):
        old.unlink()

    emails, books = [], []
    for slug, inum, inv_date, rate, lines in INVOICES:
        v = VENDOR[slug]
        defect = INVOICE_DEFECTS.get(inum)
        interstate = v["state_code"] != COMPANY["state_code"]
        tax = taxes(taxable_of(lines), rate, interstate and defect != "cgst_sgst_on_interstate")
        printed = typo(v["gstin"]) if defect == "gstin_typo" else v["gstin"]
        fname = f"{slug}_{safe(inum)}.pdf"
        total = draw_invoice(OUT / "invoices" / fname, v, inum, inv_date, rate, lines, printed, tax)
        books.append({"vendor": slug, "inum": inum, "date": inv_date, "rate": rate,
                      "taxable": taxable_of(lines), **tax, "total": total, "printed_gstin": printed})
        sent = datetime.strptime(inv_date, "%Y-%m-%d") + timedelta(days=1, hours=10, minutes=len(inum) * 3)
        emails.append({
            "from_name": v["name"], "from_alias": slug,
            "subject": f"Invoice {inum} from {v['name']}",
            "body": f"Dear Accounts Team,\n\nPlease find attached our invoice {inum} dated "
                    f"{datetime.strptime(inv_date, '%Y-%m-%d').strftime('%d %b %Y')}.\n\nRegards,\n{v['name']}",
            "date": sent.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
            "attachment": fname,
        })
        if inum == DUPLICATE_EMAIL:
            emails.append({
                "from_name": "Ravi (Store Manager)", "from_alias": "store",
                "subject": f"Fwd: Invoice {inum} from {v['name']}",
                "body": "Forwarding this one again in case accounts missed it.\n\n-- Ravi",
                "date": "2026-09-02T09:40:00+05:30",
                "attachment": fname,
            })
    emails.sort(key=lambda e: e["date"])
    for i, e in enumerate(emails, 1):
        e["id"] = f"demo-{i:03d}"
    (OUT / "emails.json").write_text(json.dumps(emails, indent=2) + "\n")

    # GSTR-2B, grouped by supplier, in the portal's JSON layout.
    by_ctin = {}
    for slug, inum, inv_date, rate, lines in INVOICES + ONLY_IN_2B:
        tw = TWEAKS_2B.get(inum, {})
        if tw.get("missing"):
            continue
        v = VENDOR[slug]
        taxable = tw.get("taxable", taxable_of(lines))
        tax = taxes(taxable, rate, v["state_code"] != COMPANY["state_code"])
        val = round(taxable + sum(tax.values()), 2)
        entry = by_ctin.setdefault(v["gstin"], {
            "ctin": v["gstin"], "trdnm": v["name"].upper(), "supfildt": "11-09-2026", "supprd": PERIOD, "inv": []})
        entry["inv"].append({
            "inum": tw.get("inum", inum),
            "dt": datetime.strptime(inv_date, "%Y-%m-%d").strftime("%d-%m-%Y"),
            "val": val, "typ": "R", "pos": COMPANY["state_code"], "rev": "N",
            "itcavl": "Y", "rsn": "", "diffprcnt": 1, "srctyp": "",
            "items": [{"num": 1, "rt": rate, "txval": taxable, **tax, "cess": 0}],
        })
    gstr2b = {"data": {
        "gstin": COMPANY["gstin"], "rtnprd": PERIOD, "version": "1.0", "gendt": "14-09-2026",
        "docdata": {"b2b": list(by_ctin.values())},
    }}
    (OUT / "portal" / f"GSTR2B_{PERIOD}.json").write_text(json.dumps(gstr2b, indent=2) + "\n")

    with open(OUT / "vendor_master.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["gstin", "name", "state_code", "contact_alias", "address"])
        for v in VENDOR.values():
            wr.writerow([v["gstin"], v["name"], v["state_code"], v["slug"], v["address"]])
    (OUT / "company.json").write_text(json.dumps(COMPANY, indent=2) + "\n")

    b = {x["inum"]: x for x in books}

    def tax_of(x):
        return x["igst"] + x["cgst"] + x["sgst"]

    at_risk = {
        "MS/0823": tax_of(b["MS/0823"]),
        "SP/26-27/0419": round(tax_of(b["SP/26-27/0419"]) - 205000 * 0.18, 2),
        "PBE/26/0057": tax_of(b["PBE/26/0057"]),
        "CFS/AUG/044": tax_of(b["CFS/AUG/044"]),
    }
    key = {
        "company_gstin": COMPANY["gstin"],
        "period": PERIOD,
        "invoices_in_books": len(INVOICES),
        "emails": len(emails),
        "findings": {
            "missing_in_2b": ["MS/0823"],
            "value_mismatch": ["SP/26-27/0419"],
            "number_format_needs_confirmation": [["KFM-118", "KFM/2026-27/118"]],
            "invalid_gstin_on_invoice": ["CFS/AUG/044"],
            "wrong_tax_head": ["PBE/26/0057"],
            "in_2b_not_in_books": ["SST/774"],
            "duplicate_in_books": ["DDP/0902"],
        },
        "itc_at_risk_by_invoice": at_risk,
        "itc_at_risk_total": round(sum(at_risk.values()), 2),
        "itc_unclaimed_in_2b_only": 105000 * 0.05,
    }
    (ROOT / "tests" / "answer_key.json").write_text(json.dumps(key, indent=2) + "\n")
    print(f"Wrote {len(INVOICES)} invoices, {len(emails)} emails, GSTR-2B with "
          f"{sum(len(e['inv']) for e in by_ctin.values())} invoices. ITC at risk: INR {money(key['itc_at_risk_total'])}")


if __name__ == "__main__":
    main()
