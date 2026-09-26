"""Offline check that the skill's scripts get random months right.

    python tests/test_scenarios.py            # seeds 1-40
    python tests/test_scenarios.py 7 8 9      # just these seeds

For each seed it generates a month, reads every attachment in inbox order
with extract.py, parses the Tally-layout invoices with the reference parser
(standing in for the parser the agent writes), runs check_books and
reconcile, and compares the result with the generator's answer key.
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "gst-reconcile" / "scripts"))
sys.path.insert(0, str(ROOT / "data"))
sys.path.insert(0, str(ROOT / "tests"))
import generate  # noqa: E402
from check_books import check_row  # noqa: E402
from extract import extract_invoice  # noqa: E402
from reconcile import reconcile  # noqa: E402
from reference_tally_parser import parse  # noqa: E402


def run(seed: int, verbose=False) -> list[str]:
    errs = []
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        key = generate.main(["--seed", str(seed), "--out", str(out), "--key", str(out / "key.json")]) if seed else \
            generate.main(["--out", str(out), "--key", str(out / "key.json")])
        emails = json.loads((out / "emails.json").read_text())
        books = []
        for e in emails:
            for name in e["attachments"]:
                row = extract_invoice(str(out / "invoices" / name), str(out / "text"))
                layout = key["layouts"].get(name)
                if row["looks_like_invoice"] != (name not in key["non_invoice_documents"]):
                    errs.append(f"{name}: looks_like_invoice={row['looks_like_invoice']}")
                if layout == "tally":
                    if not row["needs_manual_parse"]:
                        errs.append(f"{name}: tally layout was not flagged for a parser")
                    row = parse((out / "text" / (Path(name).stem + ".txt")).read_text(encoding="utf-8"), name)
                elif row["needs_manual_parse"]:
                    errs.append(f"{name} ({layout}): stock extractor failed: {row['parse_warnings']}")
                books.append(row)
        invoices = [b for b in books if b["looks_like_invoice"]]
        for b in invoices:
            for p in check_row(b):
                errs.append(f"{b['source_file']}: check_books: {p}")
        gstr2b = json.loads((out / "portal" / "GSTR2B_082026.json").read_text())
        rep = reconcile(books, gstr2b)
    got = {}
    for f in rep["findings"]:
        got.setdefault(f["category"], []).append(f["invoice_number"])
    got["number_format_needs_confirmation"] = [
        [f["invoice_number"], f["detail"].split("GSTR-2B has ")[1].split("'")[1]]
        for f in rep["findings"] if f["category"] == "number_format_needs_confirmation"]
    if not got["number_format_needs_confirmation"]:
        del got["number_format_needs_confirmation"]
    for cat in set(got) | set(key["findings"]):
        if sorted(map(str, got.get(cat, []))) != sorted(map(str, key["findings"].get(cat, []))):
            errs.append(f"{cat}: want {key['findings'].get(cat)} got {got.get(cat)}")
    if abs(rep["summary"]["itc_at_risk"] - key["itc_at_risk_total"]) > 0.01:
        errs.append(f"ITC at risk want {key['itc_at_risk_total']} got {rep['summary']['itc_at_risk']}")
    if abs(rep["summary"]["itc_claimable_clean"] - key["itc_claimable_clean"]) > 0.01:
        errs.append(f"clean ITC want {key['itc_claimable_clean']} got {rep['summary']['itc_claimable_clean']}")
    if verbose:
        print(json.dumps(rep["summary"], indent=1))
    return errs


def main(argv):
    seeds = [int(a) for a in argv] or list(range(0, 41))
    failed = 0
    for s in seeds:
        errs = run(s)
        print(("PASS" if not errs else "FAIL") + f" seed {s}" + "".join(f"\n    {e}" for e in errs))
        failed += bool(errs)
    print(f"\n{len(seeds) - failed}/{len(seeds)} seeds pass (seed 0 is the fixed demo month)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
