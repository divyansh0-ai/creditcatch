"""The business's own record, kept in a small SQLite file (state/creditcatch.db).

Two tables:
- received: every invoice email seen in the inbox (sender, subject, PDFs), so
  invoices pile up month by month as they arrive.
- itc_claims: every claim in a saved ITC register, split into IGST, CGST and
  SGST using the GSTR-2B row it was matched to.

gstr3b_table4() turns a period's claims and its GSTR-2B into the numbers for
Table 4 of GSTR-3B (eligible ITC), which is where the credit is claimed.
CreditCatch never files anything: the summary is for a person to check
against the portal's auto-filled GSTR-3B and enter there.
"""

import json
import sqlite3
from datetime import datetime, timezone

from . import config

SCHEMA = """
create table if not exists received (
    message_id text primary key, first_seen text, sender text, subject text, sent_at text, attachments text);
create table if not exists itc_claims (
    period text, supplier_gstin text, supplier_name text, invoice_number text, invoice_date text,
    igst real, cgst real, sgst real, itc real, saved_at text,
    primary key (period, supplier_gstin, invoice_number));
"""


def path():
    return config.STATE_DIR / "creditcatch.db"


def connect() -> sqlite3.Connection:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path())
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_emails(msgs: list[dict]) -> int:
    """Add invoice emails not seen before. Returns how many were new."""
    with connect() as conn:
        before = conn.total_changes
        conn.executemany(
            "insert or ignore into received values (?, ?, ?, ?, ?, ?)",
            [(m["message_id"], _now(), m.get("from"), m.get("subject"), m.get("date"),
              json.dumps(m.get("attachments", []))) for m in msgs])
        return conn.total_changes - before


def save_claims(period: str, rows: list[dict]):
    """Replace the period's claims with a newly approved register."""
    at = _now()
    with connect() as conn:
        conn.execute("delete from itc_claims where period = ?", (period,))
        conn.executemany(
            "insert into itc_claims values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(period, r["supplier_gstin"], r.get("supplier_name"), r["gstr2b_invoice_number"], r.get("invoice_date"),
              r["igst"], r["cgst"], r["sgst"], r["itc"], at) for r in rows])


def split_by_head(itc: float, row: dict) -> dict:
    """Split a claimed amount into IGST/CGST/SGST in the same shares as its GSTR-2B row."""
    heads = {h: sum(i.get(h, 0) for i in row.get("items", [])) for h in ("igst", "cgst", "sgst")}
    total = sum(heads.values())
    if not total:
        return {h: 0.0 for h in heads}
    out = {h: round(itc * v / total, 2) for h, v in heads.items()}
    # Keep the parts adding up to the claim exactly after rounding.
    biggest = max(out, key=lambda h: heads[h])
    out[biggest] = round(out[biggest] + itc - sum(out.values()), 2)
    return out


def gstr3b_table4(period: str, claims: list[dict], gstr2b_data: dict) -> dict:
    """GSTR-3B Table 4 for the period, from the approved claims and GSTR-2B."""
    def total(rows):
        return {h: round(sum(r[h] for r in rows), 2) for h in ("igst", "cgst", "sgst")} | {"cess": 0.0}

    ineligible = []
    claimable_in_2b = 0.0
    for s in gstr2b_data.get("docdata", {}).get("b2b", []):
        for inv in s.get("inv", []):
            heads = {h: sum(i.get(h, 0) for i in inv.get("items", [])) for h in ("igst", "cgst", "sgst")}
            if str(inv.get("itcavl", "Y")).upper() == "N":
                ineligible.append(heads | {"invoice_number": inv["inum"], "supplier_gstin": s["ctin"],
                                           "reason": inv.get("rsn")})
            else:
                claimable_in_2b += sum(heads.values())
    a5 = total(claims)
    b = {"igst": 0.0, "cgst": 0.0, "sgst": 0.0, "cess": 0.0}
    claimed = round(sum(r["itc"] for r in claims), 2)
    return {
        "period": period,
        "4A(5) All other ITC": a5,
        "4B(1) Reversed as per rules 38, 42, 43 and section 17(5)": b,
        "4B(2) Reversed, others": b,
        "4C Net ITC available (4A - 4B)": a5,
        "4D(2) Ineligible ITC under section 16(4) and ITC restricted due to PoS rules": total(ineligible),
        "invoices_claimed": len(claims),
        "itc_claimed": claimed,
        "itc_in_gstr2b_not_claimed_this_month": round(claimable_in_2b - claimed, 2),
        "ineligible_invoices": [i["invoice_number"] for i in ineligible],
        "note": "Check these against the auto-filled GSTR-3B on the GST portal and enter them there. "
                "CreditCatch does not file returns. Credit not claimed this month (supplier hasn't "
                "filed, amounts differ) can be claimed in a later month once the supplier fixes it.",
    }
