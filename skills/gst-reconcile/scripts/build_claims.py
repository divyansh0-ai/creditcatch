"""Build the ITC register claims from report.json, after the user's answers.

    python build_claims.py --report report.json --confirm KFM-118 --reject INV-9 > claims.json

--confirm / --reject take the book invoice numbers of number_format_needs_confirmation
findings the user said yes / no to. Claims are, per GSTR-2B invoice:
  - every clean match, at its ITC
  - every confirmed fuzzy match, at the GSTR-2B tax, under the GSTR-2B number
  - every value_mismatch, at the GSTR-2B tax only
Everything else is held back. A rejected fuzzy match is treated as missing from
GSTR-2B, so its tax is added to ITC at risk. Unanswered fuzzy matches are held back
and listed. Pass the "claims" list to save_itc_register as it is.
"""

import argparse
import json


def build(report: dict, confirm=(), reject=()) -> dict:
    confirm, reject = set(confirm), set(reject)
    claims, held, unanswered = [], [], []
    at_risk = report["summary"]["itc_at_risk"]

    def add(gstin, inum, itc, basis):
        claims.append({"supplier_gstin": gstin, "gstr2b_invoice_number": inum, "itc": round(itc, 2), "basis": basis})

    for m in report["matched"]:
        add(m["supplier_gstin"], m.get("gstr2b_invoice_number") or m["invoice_number"], m["itc"], "matched")
    for f in report["findings"]:
        cat, num = f["category"], f["invoice_number"]
        if cat == "number_format_needs_confirmation":
            if num in confirm:
                add(f["supplier_gstin"], f["gstr2b_invoice_number"], min(f["gstr2b_tax"], f["book_tax"]),
                    f"confirmed same as {num}")
            elif num in reject:
                at_risk += f["book_tax"]
                held.append({"invoice_number": num, "reason": "user said it is not the GSTR-2B invoice; treat as missing"})
            else:
                unanswered.append(num)
        elif cat == "value_mismatch":
            add(f["supplier_gstin"], f["gstr2b_invoice_number"], min(f["gstr2b_tax"], f["book_tax"]),
                "GSTR-2B value only")
        elif cat not in ("duplicate_in_books", "in_2b_not_in_books"):
            held.append({"invoice_number": num, "reason": cat})
    return {"claims": claims, "total_itc": round(sum(c["itc"] for c in claims), 2),
            "itc_at_risk": round(at_risk, 2), "held_back": held, "unanswered_fuzzy_matches": unanswered}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", default="report.json")
    ap.add_argument("--confirm", nargs="*", default=[], help="fuzzy matches the user confirmed (book invoice numbers)")
    ap.add_argument("--reject", nargs="*", default=[], help="fuzzy matches the user rejected")
    args = ap.parse_args()
    print(json.dumps(build(json.load(open(args.report)), args.confirm, args.reject), indent=2))


if __name__ == "__main__":
    main()
