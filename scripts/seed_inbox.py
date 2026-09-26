"""Put the demo invoice emails into the inbox, or reset the demo.

    python scripts/seed_inbox.py            # add the 16 demo emails
    python scripts/seed_inbox.py --reset    # remove demo emails and run state, then add them again

With MAIL_BACKEND=gmail the emails are appended straight into the Gmail
inbox over IMAP (no second account needed) and --reset moves every message
tagged X-CreditCatch-Demo to Trash. With MAIL_BACKEND=local they are .eml
files under state/mailbox/.
"""

import argparse
import json
import shutil
import sys
from email.message import EmailMessage
from email.utils import format_datetime, formataddr, make_msgid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import config  # noqa: E402
from server.mailbox import DEMO_HEADER, GmailMailbox, get_mailbox  # noqa: E402


def build(e: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((e["from_name"], config.vendor_address(e["from_alias"])))
    msg["To"] = config.GMAIL_ADDRESS or config.DEMO_INBOX
    msg["Subject"] = e["subject"]
    msg["Date"] = format_datetime(datetime.fromisoformat(e["date"]))
    msg["Message-ID"] = make_msgid(domain="creditcatch.local")
    msg[DEMO_HEADER] = "seed"
    msg.set_content(e["body"])
    pdf = (config.DATA_DIR / "invoices" / e["attachment"]).read_bytes()
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=e["attachment"])
    return msg


def reset():
    for name in ("audit.jsonl", "sent_log.jsonl"):
        (config.STATE_DIR / name).unlink(missing_ok=True)
    for p in config.STATE_DIR.glob("itc_register_*"):
        p.unlink()
    if config.MAIL_BACKEND == "gmail":
        n = GmailMailbox().trash_demo_messages()
        print(f"Moved {n} demo emails to Gmail Trash")
    else:
        shutil.rmtree(config.STATE_DIR / "mailbox", ignore_errors=True)
        print("Cleared the local mailbox")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="remove demo emails and state first")
    args = ap.parse_args()
    problems = config.check()
    if problems:
        sys.exit("\n".join(problems))
    if args.reset:
        reset()
    box = get_mailbox()
    emails = json.loads((config.DATA_DIR / "emails.json").read_text())
    for e in emails:
        box.append(build(e), e["id"])
    where = config.GMAIL_ADDRESS if config.MAIL_BACKEND == "gmail" else config.STATE_DIR / "mailbox" / "inbox"
    print(f"Added {len(emails)} invoice emails to {where}")


if __name__ == "__main__":
    main()
