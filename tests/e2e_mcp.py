"""End-to-end check over real MCP: does what the agent will do, without the model.

Start the server first (python -m server), seed the inbox, then:
    python tests/e2e_mcp.py [http://127.0.0.1:8000/mcp]

It lists the invoice emails, downloads every PDF, runs the skill's
extract + reconcile scripts (with the reference parser standing in for the
one the agent writes for Tally-style invoices), compares the result with the
answer key of the month being served (tests/answer_key.json, or
state/scenario/answer_key.json after seed_inbox.py --seed), and checks the
send/save guards refuse what they should.
"""

import asyncio
import base64
import json
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "gst-reconcile" / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
from extract import extract_invoice  # noqa: E402
from reconcile import reconcile  # noqa: E402
from reference_tally_parser import parse  # noqa: E402
from server import config  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/mcp"


async def call(session, name, **args):
    res = await session.call_tool(name, args)
    if res.isError:
        raise RuntimeError(f"{name} failed: {res.content}")
    if res.structuredContent is not None:
        return res.structuredContent.get("result", res.structuredContent)
    return json.loads(res.content[0].text)


async def main():
    key_path = config.data_dir() / "answer_key.json"
    key = json.loads((key_path if key_path.exists() else ROOT / "tests" / "answer_key.json").read_text())
    print(f"Answer key: seed {key.get('seed')}, company {key['company_gstin']}")
    failures = []

    def check(ok, what):
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            failures.append(what)

    async with streamablehttp_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name: t for t in (await session.list_tools()).tools}
            check({"send_vendor_email", "save_itc_register"} <= set(tools), "write tools are exposed")
            check(tools["send_vendor_email"].annotations.destructiveHint is True, "send_vendor_email is marked destructive")
            check(tools["list_invoice_emails"].annotations.readOnlyHint is True, "list_invoice_emails is read-only")

            inbox = await call(session, "list_invoice_emails")
            check(inbox["count"] == key["emails"], f"inbox has {key['emails']} invoice emails (got {inbox['count']})")

            books = []
            with tempfile.TemporaryDirectory() as tmp:
                for m in inbox["messages"]:
                    for name in m["attachments"]:
                        pdf = await call(session, "get_invoice_pdf", message_id=m["message_id"], filename=name)
                        path = Path(tmp) / f"{m['message_id']}_{name}"
                        path.write_bytes(base64.b64decode(pdf["content_base64"]))
                        row = extract_invoice(str(path), str(Path(tmp) / "text"))
                        if row["needs_manual_parse"]:
                            row = parse((Path(tmp) / "text" / (path.stem + ".txt")).read_text(encoding="utf-8"), path.name)
                        books.append(row)
            gstr2b = await call(session, "get_gstr2b", period=key["period"])
            report = reconcile(books, gstr2b)

            got = {}
            for f in report["findings"]:
                got.setdefault(f["category"], []).append(f["invoice_number"])
            for cat in set(got) | set(key["findings"]):
                want = [i[0] if isinstance(i, list) else i for i in key["findings"].get(cat, [])]
                check(sorted(got.get(cat, [])) == sorted(want), f"{cat}: {want} (got {got.get(cat)})")
            check(report["summary"]["itc_at_risk"] == key["itc_at_risk_total"],
                  f"ITC at risk {key['itc_at_risk_total']} (got {report['summary']['itc_at_risk']})")

            vendors = (await call(session, "get_vendor_master"))["vendors"]
            v = vendors[0]
            r = await call(session, "send_vendor_email", supplier_gstin="29ZZZZZ9999Z1Z9",
                           subject="x", body="INV-1", invoice_numbers=["INV-1"])
            check(r["status"] == "refused", "refuses an unknown GSTIN")
            r = await call(session, "send_vendor_email", supplier_gstin=v["gstin"],
                           subject="Invoice query", body="Please check.", invoice_numbers=["INV-1"])
            check(r["status"] == "refused", "refuses a body that doesn't cite the invoice")
            r = await call(session, "send_vendor_email", supplier_gstin=v["gstin"], subject="Invoice INV-1",
                           body="Please check invoice INV-1.", invoice_numbers=["INV-1"])
            check(r["status"] == "sent" and r["to"] == v["contact_email"], "sends to the vendor-master address")
            r = await call(session, "send_vendor_email", supplier_gstin=v["gstin"], subject="Again",
                           body="Invoice INV-1 again.", invoice_numbers=["INV-1"])
            check(r["status"] == "refused", "refuses a second email to the same vendor")

            r = await call(session, "save_itc_register", period=key["period"],
                           claims=[{"supplier_gstin": v["gstin"], "gstr2b_invoice_number": "NOPE-1", "itc": 100}])
            check(r["status"] == "refused", "refuses to claim ITC on an invoice not in GSTR-2B")
            na = [(s["ctin"], i["inum"]) for s in gstr2b.get("data", gstr2b)["docdata"]["b2b"]
                  for i in s["inv"] if i.get("itcavl") == "N"]
            if na:
                r = await call(session, "save_itc_register", period=key["period"],
                               claims=[{"supplier_gstin": na[0][0], "gstr2b_invoice_number": na[0][1], "itc": 1}])
                check(r["status"] == "refused", "refuses to claim ITC that GSTR-2B marks not available")
            ok_claims = [{"supplier_gstin": m["supplier_gstin"], "gstr2b_invoice_number": m["invoice_number"],
                          "itc": m["itc"]} for m in report["matched"]]
            r = await call(session, "save_itc_register", period=key["period"], claims=ok_claims)
            check(r["status"] == "saved", f"saves the clean claims ({r})")

            log = await call(session, "get_audit_log", limit=5)
            check(len(log["entries"]) == 5, "audit log records calls")

    print(f"\n{len(failures)} failed" if failures else "\nAll checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
