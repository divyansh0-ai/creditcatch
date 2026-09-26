"""Match purchase invoices (books) against a GSTR-2B statement.

Input:
  books:  list of rows from extract.py (one per invoice PDF)
  gstr2b: the parsed GSTR-2B JSON (the "data" object, or the whole file)

For each book invoice, looks for the same (supplier GSTIN, invoice number)
in GSTR-2B. If the number differs but the supplier, date and amount are
close, it's reported as a fuzzy match that needs a human's yes/no rather
than a guess. Every book invoice also gets its GSTIN checked, is checked
to be billed to this business's GSTIN, and, for an inter-state supplier,
is checked for the right tax head (IGST, not CGST+SGST). GSTR-2B rows the
portal marks as ITC not available (itcavl = N) are never counted as clean.
Rows that aren't tax invoices are skipped; rows still needing a parser are
reported as unreadable rather than matched on guessed values.

CLI:
    python reconcile.py --books books.json --gstr2b GSTR2B_082026.json
Library:
    from reconcile import reconcile
    report = reconcile(books, gstr2b)

Nothing here computes tax rates or invents thresholds beyond what's below;
every number in the output traces back to a field in books or gstr2b.
"""

import argparse
import json
from datetime import datetime
from difflib import SequenceMatcher

# GSTR-2B reasons for itcavl = "N".
RSN = {
    "P": "the place of supply is in the supplier's state, not yours (for example a hotel stay in another "
         "state), so the tax was charged as CGST+SGST of that state and can't be claimed by a buyer registered elsewhere",
    "C": "the supplier reported it after the Section 16(4) time limit",
}

AMOUNT_TOLERANCE = 1.0       # rupees; below this, two totals count as "same"
FUZZY_SCORE_MIN = 0.55       # invoice-number similarity needed to suggest a fuzzy match
FUZZY_DATE_DAYS = 3          # dates must be within this many days


def _norm_num(s: str) -> str:
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm_num(a), _norm_num(b)).ratio()


def _parse_date(s: str):
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _2b_invoices(gstr2b: dict):
    """Flatten GSTR-2B into one row per invoice, with the supplier attached."""
    data = gstr2b.get("data", gstr2b)
    rows = []
    for supplier in data.get("docdata", {}).get("b2b", []):
        ctin = supplier["ctin"]
        for inv in supplier.get("inv", []):
            taxable = sum(i.get("txval", 0) for i in inv.get("items", []))
            tax = sum(i.get("igst", 0) + i.get("cgst", 0) + i.get("sgst", 0) for i in inv.get("items", []))
            rows.append({
                "ctin": ctin, "supplier_name": supplier.get("trdnm"),
                "inum": inv["inum"], "date": _parse_date(inv["dt"]), "val": inv.get("val"),
                "taxable": taxable, "tax": tax, "pos": inv.get("pos"), "itcavl": inv.get("itcavl"),
                "rsn": inv.get("rsn"),
            })
    return rows


def _book_tax(book: dict) -> float:
    return round(book.get("cgst", 0) + book.get("sgst", 0) + book.get("igst", 0), 2)


def _book_total(book: dict) -> float:
    return round((book.get("taxable_value") or 0) + _book_tax(book), 2)


def _finding(category, book, gstr2b_row, itc_at_risk, detail, action):
    return {
        "category": category,
        "invoice_number": book.get("invoice_number") if book else gstr2b_row["inum"],
        "supplier_gstin": (gstr2b_row or {}).get("ctin") or (book or {}).get("supplier_gstin"),
        "supplier_name": (book or {}).get("supplier_name") or (gstr2b_row or {}).get("supplier_name"),
        "invoice_date": (book or {}).get("invoice_date") or ((gstr2b_row or {}).get("date") and gstr2b_row["date"].strftime("%Y-%m-%d")),
        "book_total": _book_total(book) if book else None,
        "gstr2b_total": (gstr2b_row or {}).get("val"),
        "itc_at_risk": round(itc_at_risk, 2),
        "book_tax": _book_tax(book) if book else None,
        "gstr2b_invoice_number": (gstr2b_row or {}).get("inum"),
        "gstr2b_tax": round(gstr2b_row["tax"], 2) if gstr2b_row else None,
        "detail": detail,
        "suggested_action": action,
        "source_file": (book or {}).get("source_file"),
    }


def reconcile(books: list, gstr2b: dict) -> dict:
    from gstin import validate  # local import: script also runs standalone

    unmatched_2b = _2b_invoices(gstr2b)
    company_gstin = gstr2b.get("data", gstr2b).get("gstin")
    findings, matched, skipped = [], [], []
    seen = {}
    # A GSTR-2B row whose number exactly matches some invoice in the books belongs to that invoice,
    # so it is never offered as a fuzzy match for a different one.
    book_keys = {(b.get("supplier_gstin") or "", _norm_num(b.get("invoice_number"))) for b in books
                 if b.get("looks_like_invoice") is not False and not b.get("needs_manual_parse")}

    def take(pred):
        row = next((r for r in unmatched_2b if pred(r)), None)
        if row:
            unmatched_2b.remove(row)
        return row

    for book in books:
        if book.get("looks_like_invoice") is False:
            skipped.append(book.get("source_file"))
            continue
        if book.get("needs_manual_parse"):
            findings.append(_finding("unreadable_invoice", book, None, 0,
                "Not read yet: " + "; ".join(book.get("parse_warnings") or []) + ". Parse it before trusting this report.",
                "write a parser for this layout, or enter it by hand"))
            continue
        num = _norm_num(book.get("invoice_number"))
        gstin = book.get("supplier_gstin") or ""

        # 1. Duplicate copies of the same invoice (same supplier + number).
        key = (gstin, num)
        if key in seen:
            findings.append(_finding("duplicate_in_books", book, None, 0,
                f"Same invoice also in {seen[key]}; counted once.", "none"))
            continue
        seen[key] = book.get("source_file")

        # 2. GSTIN printed on the invoice must be valid.
        check = validate(gstin)
        if not check["valid"]:
            twin = take(lambda r: _norm_num(r["inum"]) == num
                        and abs((r["val"] or 0) - _book_total(book)) <= AMOUNT_TOLERANCE)
            detail = f"GSTIN {gstin} on the invoice fails validation ({check['reason']})."
            if twin:
                detail += f" GSTR-2B has this invoice under {twin['ctin']} ({twin['supplier_name']})."
            findings.append(_finding("invalid_gstin_on_invoice", book, twin, _book_tax(book), detail,
                "ask supplier for a corrected invoice"))
            continue

        # 3. It must be billed to this business, or the credit isn't ours to claim.
        buyer = book.get("buyer_gstin")
        if company_gstin and buyer and buyer != company_gstin:
            findings.append(_finding("billed_to_other_gstin", book, None, _book_tax(book),
                f"Invoice is billed to GSTIN {buyer}, not this business's {company_gstin}, so it won't reach "
                f"this GSTR-2B.", "ask supplier to cancel it and reissue to the right GSTIN"))
            continue

        # 4. Tax head: supplier state differs from place of supply -> IGST only.
        pos = book.get("place_of_supply") or (book.get("buyer_gstin") or company_gstin or "")[:2]
        interstate = pos and gstin[:2] != pos
        wrong_head = interstate and (book.get("cgst") or book.get("sgst")) and not book.get("igst")

        # 5. Find the invoice in GSTR-2B.
        exact = take(lambda r: r["ctin"] == gstin and _norm_num(r["inum"]) == num)
        if not exact:
            best, best_score = None, 0.0
            for r in unmatched_2b:
                if r["ctin"] != gstin or (r["ctin"], _norm_num(r["inum"])) in book_keys:
                    continue
                d = _parse_date(book.get("invoice_date"))
                if r["date"] and d and abs((r["date"] - d).days) > FUZZY_DATE_DAYS:
                    continue
                if abs((book.get("taxable_value") or 0) - r["taxable"]) > AMOUNT_TOLERANCE:
                    continue
                score = _similar(book["invoice_number"], r["inum"])
                if score > best_score:
                    best, best_score = r, score
            if best and best_score >= FUZZY_SCORE_MIN:
                unmatched_2b.remove(best)
                findings.append(_finding("number_format_needs_confirmation", book, best, 0,
                    f"Book has {book['invoice_number']!r}, GSTR-2B has {best['inum']!r}: same supplier, "
                    f"date and amount (similarity {best_score:.2f}). Needs a yes/no from you.",
                    "ask the user to confirm"))
                continue
            findings.append(_finding("missing_in_2b", book, None, _book_tax(book),
                "Supplier has not reported this invoice, so its ITC cannot be claimed yet.",
                "email supplier to file it in GSTR-1"))
            continue

        if wrong_head:
            findings.append(_finding("wrong_tax_head", book, exact, _book_tax(book),
                f"Supplier is in state {gstin[:2]} and place of supply is {pos}, "
                f"so IGST applies, but the invoice charges CGST+SGST.",
                "email supplier for a corrected invoice with IGST"))
            continue

        if str(exact.get("itcavl") or "Y").upper() == "N":
            why = RSN.get(str(exact.get("rsn") or "").upper(), f"reason code {exact.get('rsn') or 'not given'}")
            findings.append(_finding("itc_not_available_in_2b", book, exact, _book_tax(book),
                f"GSTR-2B lists this invoice with ITC not available: {why}.",
                "check the reason with the supplier; don't claim it this month"))
            continue

        diff = round(_book_total(book) - (exact["val"] or 0), 2)
        if abs(diff) > AMOUNT_TOLERANCE:
            risk = max(0.0, _book_tax(book) - exact["tax"])
            findings.append(_finding("value_mismatch", book, exact, risk,
                f"Book taxable value {book.get('taxable_value'):,.2f} vs GSTR-2B {exact['taxable']:,.2f}; "
                f"only the GSTR-2B tax ({exact['tax']:,.2f}) is claimable.",
                "email supplier to amend GSTR-1"))
            continue

        matched.append({"invoice_number": book["invoice_number"], "supplier_gstin": gstin,
                        "gstr2b_invoice_number": exact["inum"],
                        "itc": round(min(_book_tax(book), exact["tax"]), 2), "source_file": book.get("source_file")})

    for r in unmatched_2b:
        findings.append(_finding("in_2b_not_in_books", None, r, 0,
            f"Supplier reported this invoice (tax {r['tax']:,.2f}) but it is not in your books.",
            "check with the supplier and record it if genuine"))

    by_cat = {}
    for f in findings:
        by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
    return {
        "summary": {
            "book_invoices": len(books),
            "matched_clean": len(matched),
            "itc_claimable_clean": round(sum(m["itc"] for m in matched), 2),
            "itc_at_risk": round(sum(f["itc_at_risk"] for f in findings), 2),
            "itc_in_2b_not_in_books": round(sum(r["tax"] for r in unmatched_2b), 2),
            "findings_by_category": by_cat,
            "skipped_not_invoices": skipped,
            "invoices_checked": len(books) - len(skipped) - by_cat.get("duplicate_in_books", 0),
            **({"warning": f"{by_cat['unreadable_invoice']} invoice(s) not read yet; their GSTR-2B rows show up as "
                           "in_2b_not_in_books until they are parsed"} if by_cat.get("unreadable_invoice") else {}),
        },
        "findings": findings,
        "matched": matched,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", required=True, help="JSON file: list of extract.py rows")
    ap.add_argument("--gstr2b", required=True, help="GSTR-2B JSON file")
    args = ap.parse_args()
    books = json.load(open(args.books))
    gstr2b = json.load(open(args.gstr2b))
    print(json.dumps(reconcile(books, gstr2b), indent=2, default=str))


if __name__ == "__main__":
    main()
