"""CreditCatch MCP server ("gst-desk").

The only way the agent touches the outside world. Read tools are free; the
two tools that change something (sending a vendor email, saving the ITC
register) are marked destructive so TrueForge holds them for approval, and
they also enforce hard limits here in code, so an approved call still
can't do more than it should.
"""

import base64
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from functools import wraps

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import config
from .mailbox import DEMO_HEADER, get_mailbox

mcp = FastMCP(
    "creditcatch",
    instructions=(
        "Tools for reconciling a business's purchase invoices with its GSTR-2B statement. "
        "Read tools are safe. send_vendor_email and save_itc_register change the world and "
        "need human approval; they also refuse anything outside their limits."
    ),
    host=config.HOST,
    port=config.PORT,
)

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)

PERIOD_RE = re.compile(r"^(0[1-9]|1[0-2])20\d{2}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _audit(tool: str, args: dict, outcome: dict):
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    safe_args = {k: (v[:200] + "..." if isinstance(v, str) and len(v) > 200 else v) for k, v in args.items()}
    with open(config.STATE_DIR / "audit.jsonl", "a") as f:
        f.write(json.dumps({"ts": _now(), "tool": tool, "args": safe_args, **outcome}) + "\n")


def audited(fn):
    @wraps(fn)
    def wrapper(**kwargs):
        try:
            result = fn(**kwargs)
        except Exception as e:
            _audit(fn.__name__, kwargs, {"status": "error", "error": str(e)})
            raise
        status = result.get("status", "ok") if isinstance(result, dict) else "ok"
        extra = {"reason": result.get("reason")} if isinstance(result, dict) and result.get("reason") else {}
        _audit(fn.__name__, kwargs, {"status": status, **extra})
        return result
    return wrapper


def _vendors() -> dict:
    with open(config.DATA_DIR / "vendor_master.csv") as f:
        return {row["gstin"]: row for row in csv.DictReader(f)}


def _company() -> dict:
    return json.loads((config.DATA_DIR / "company.json").read_text())


def _gstr2b(period: str) -> dict:
    if not PERIOD_RE.match(period):
        raise ValueError("period must look like MMYYYY, e.g. 082026")
    path = config.DATA_DIR / "portal" / f"GSTR2B_{period}.json"
    if not path.exists():
        raise FileNotFoundError(f"No GSTR-2B download for period {period}")
    return json.loads(path.read_text())


def _sent_log() -> list[dict]:
    path = config.STATE_DIR / "sent_log.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------- read tools

@mcp.tool(annotations=READ)
@audited
def get_company_profile() -> dict:
    """The business being reconciled: name, GSTIN, address and state code."""
    return _company()


@mcp.tool(annotations=READ)
@audited
def list_invoice_emails() -> dict:
    """List inbox emails that carry PDF attachments (purchase invoices).

    Read-only: the inbox is opened read-only and nothing is marked as read.
    Returns message_id, sender, subject, date and attachment file names.
    """
    msgs = get_mailbox().list_messages()
    return {"count": len(msgs), "messages": msgs}


@mcp.tool(annotations=READ)
@audited
def get_invoice_pdf(message_id: str, filename: str) -> dict:
    """Download one PDF attachment. Returns it base64-encoded with its SHA-256.

    Decode content_base64 and write it to a file in the sandbox to parse it.
    """
    data = get_mailbox().get_attachment(message_id, filename)
    return {"filename": filename, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "content_base64": base64.b64encode(data).decode()}


@mcp.tool(annotations=READ)
@audited
def get_gstr2b(period: str) -> dict:
    """The GSTR-2B statement for a tax period (MMYYYY, e.g. "082026").

    This is the JSON the GST portal lets a taxpayer download. The demo serves
    a saved file, because live portal API access requires a licensed GSP.
    """
    return _gstr2b(period)


@mcp.tool(annotations=READ)
@audited
def get_vendor_master() -> dict:
    """The business's registered vendors: GSTIN, name, state code and contact email."""
    vendors = [{"gstin": v["gstin"], "name": v["name"], "state_code": v["state_code"],
                "contact_email": config.vendor_address(v["contact_alias"])} for v in _vendors().values()]
    return {"count": len(vendors), "vendors": vendors}


@mcp.tool(annotations=READ)
@audited
def get_audit_log(limit: int = 20) -> dict:
    """The most recent tool calls made through this server, newest last."""
    path = config.STATE_DIR / "audit.jsonl"
    lines = path.read_text().splitlines() if path.exists() else []
    return {"entries": [json.loads(line) for line in lines[-max(1, min(limit, 200)):]]}


# --------------------------------------------------------------- write tools

def _refuse(reason: str) -> dict:
    return {"status": "refused", "reason": reason}


@mcp.tool(annotations=WRITE)
@audited
def send_vendor_email(supplier_gstin: str, subject: str, body: str, invoice_numbers: list[str]) -> dict:
    """Send one email to a vendor about specific invoices. Needs human approval.

    You choose the vendor by GSTIN; the address comes from the vendor master,
    so you never type an email address. Limits enforced by the server:
    the GSTIN must be a registered vendor; every invoice number listed must
    appear in the body; at most one email per vendor per run and
    MAX_EMAILS_PER_RUN in total; in demo mode the recipient must be a
    plus-alias of the demo inbox.
    """
    vendor = _vendors().get(supplier_gstin.strip().upper())
    if not vendor:
        return _refuse(f"{supplier_gstin} is not in the vendor master")
    to = config.vendor_address(vendor["contact_alias"])
    if config.DEMO_MODE and not config.demo_address_pattern().match(to):
        return _refuse("demo mode only sends to plus-aliases of the demo inbox")
    if not invoice_numbers or len(invoice_numbers) > 10:
        return _refuse("list between 1 and 10 invoice numbers")
    missing = [n for n in invoice_numbers if n not in body]
    if missing:
        return _refuse(f"body must mention every listed invoice; missing {missing}")
    if not subject.strip() or len(subject) > 150 or len(body) > 4000:
        return _refuse("subject must be 1-150 characters and body at most 4000")
    log = _sent_log()
    if any(e["supplier_gstin"] == vendor["gstin"] for e in log):
        return _refuse(f"already emailed {vendor['name']} this run; one email per vendor")
    if len(log) >= config.MAX_EMAILS_PER_RUN:
        return _refuse(f"reached the limit of {config.MAX_EMAILS_PER_RUN} emails per run")

    company = _company()
    sender = config.GMAIL_ADDRESS or config.DEMO_INBOX
    msg = EmailMessage()
    msg["From"] = formataddr((f"{company['name']} Accounts", sender))
    msg["To"] = formataddr((vendor["name"], to))
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="creditcatch.local")
    msg[DEMO_HEADER] = "vendor-email"
    msg.set_content(body.rstrip() + "\n\n--\nSent by CreditCatch, an AI assistant, for "
                    f"{company['name']} (GSTIN {company['gstin']}).\n")
    message_id = get_mailbox().send(msg)

    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.STATE_DIR / "sent_log.jsonl", "a") as f:
        f.write(json.dumps({"ts": _now(), "supplier_gstin": vendor["gstin"], "to": to,
                            "subject": subject, "invoice_numbers": invoice_numbers}) + "\n")
    return {"status": "sent", "to": to, "vendor": vendor["name"], "message_id": message_id}


@mcp.tool(annotations=WRITE)
@audited
def save_itc_register(period: str, claims: list[dict], notes: str = "") -> dict:
    """Save the list of invoices to claim input tax credit on. Needs human approval.

    Each claim is {"supplier_gstin", "gstr2b_invoice_number", "itc"}. The
    server refuses any claim that is not in that period's GSTR-2B, or whose
    ITC is more than GSTR-2B shows, so credit is never claimed on an
    invoice the supplier hasn't reported.
    """
    data = _gstr2b(period).get("data", {})
    supported = {}
    for s in data.get("docdata", {}).get("b2b", []):
        for inv in s.get("inv", []):
            tax = sum(i.get("igst", 0) + i.get("cgst", 0) + i.get("sgst", 0) for i in inv.get("items", []))
            supported[(s["ctin"], inv["inum"])] = tax
    if not claims:
        return _refuse("no claims given")
    problems, rows, seen = [], [], set()
    for c in claims:
        key = (str(c.get("supplier_gstin", "")).upper(), str(c.get("gstr2b_invoice_number", "")))
        itc = float(c.get("itc", 0))
        if key in seen:
            problems.append(f"{key[1]} listed twice")
        elif key not in supported:
            problems.append(f"{key[1]} from {key[0]} is not in GSTR-2B for {period}")
        elif itc > supported[key] + 1:
            problems.append(f"{key[1]}: ITC {itc:,.2f} is more than GSTR-2B's {supported[key]:,.2f}")
        seen.add(key)
        rows.append({"supplier_gstin": key[0], "gstr2b_invoice_number": key[1], "itc": round(itc, 2)})
    if problems:
        return _refuse("; ".join(problems))

    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    total = round(sum(r["itc"] for r in rows), 2)
    out = config.STATE_DIR / f"itc_register_{period}.json"
    out.write_text(json.dumps({"period": period, "saved_at": _now(), "total_itc": total,
                               "claims": rows, "notes": notes}, indent=2))
    with open(config.STATE_DIR / f"itc_register_{period}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["supplier_gstin", "gstr2b_invoice_number", "itc"])
        w.writeheader()
        w.writerows(rows)
    return {"status": "saved", "claims": len(rows), "total_itc": total, "file": str(out.name)}
