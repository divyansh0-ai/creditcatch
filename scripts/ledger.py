"""Show what CreditCatch has recorded: invoice emails received and ITC claimed.

    python scripts/ledger.py              # everything, with GSTR-3B Table 4 for each period
    python scripts/ledger.py --period 082026

Reads state/creditcatch.db. Invoice emails are recorded when the agent (or
the inbox watcher) lists the inbox; claims when an ITC register is approved
and saved. The Table 4 figures are what you check against the auto-filled
GSTR-3B on the GST portal before you file it there yourself.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import config, ledger  # noqa: E402


def money(x: float) -> str:
    return f"{x:>12,.2f}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--period", help="only this period, MMYYYY")
    args = ap.parse_args(argv)
    if not ledger.path().exists():
        sys.exit(f"Nothing recorded yet ({ledger.path()} doesn't exist). Run the agent first.")
    with ledger.connect() as conn:
        received = conn.execute("select count(*), count(distinct sender) from received").fetchone()
        pdfs = sum(len(json.loads(a)) for (a,) in conn.execute("select attachments from received"))
        periods = [p for (p,) in conn.execute("select distinct period from itc_claims order by period")]
    print(f"Invoice emails received: {received[0]} from {received[1]} senders, {pdfs} PDFs")
    for period in [args.period] if args.period else periods:
        path = config.STATE_DIR / f"gstr3b_table4_{period}.json"
        with ledger.connect() as conn:
            n, itc = conn.execute("select count(*), coalesce(sum(itc), 0) from itc_claims where period = ?",
                                  (period,)).fetchone()
        print(f"\nPeriod {period}: {n} invoices claimed, ITC {itc:,.2f}")
        if not path.exists():
            continue
        t = json.loads(path.read_text())
        print(f"  {'GSTR-3B Table 4':<40}{'IGST':>12}{'CGST':>12}{'SGST':>12}{'Cess':>12}")
        for k, v in t.items():
            if isinstance(v, dict):
                print(f"  {k[:40]:<40}" + "".join(money(v[h]) for h in ("igst", "cgst", "sgst", "cess")))
        print(f"  In GSTR-2B but not claimed this month: {t['itc_in_gstr2b_not_claimed_this_month']:,.2f}")
        print(f"  {t['note']}")


if __name__ == "__main__":
    main()
