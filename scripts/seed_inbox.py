"""Put the demo invoice emails into the inbox, or reset the demo.

    python scripts/seed_inbox.py                       # add the fixed demo month's 16 emails
    python scripts/seed_inbox.py --reset               # clear the inbox and run state, then add them again
    python scripts/seed_inbox.py --reset --seed 42     # clear, then generate and add a new random month
    python scripts/seed_inbox.py --reset --seed random # same, with a seed picked for you

A random month has a different business, vendors, invoice layouts, amounts
and problems for every seed. It is written to state/scenario/ and the MCP
server serves it straight away (no restart). The answer key is in
state/scenario/answer_key.json. A plain --reset goes back to the fixed month.

With MAIL_BACKEND=gmail the emails are appended straight into the Gmail
inbox over IMAP (no second account needed) and --reset moves every message
tagged X-CreditCatch-Demo to Trash. With MAIL_BACKEND=local they are .eml
files under state/mailbox/.
"""

import argparse
import json
import random
import shutil
import sys
import uuid
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
    for name in e.get("attachments") or [e["attachment"]]:
        pdf = (config.data_dir() / "invoices" / name).read_bytes()
        msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=name)
    return msg


def reset():
    for name in ("audit.jsonl", "sent_log.jsonl"):
        (config.STATE_DIR / name).unlink(missing_ok=True)
    for p in config.STATE_DIR.glob("itc_register_*"):
        p.unlink()
    shutil.rmtree(config.STATE_DIR / "scenario", ignore_errors=True)
    if config.MAIL_BACKEND == "gmail":
        n = GmailMailbox().trash_demo_messages()
        print(f"Moved {n} demo emails to Gmail Trash")
    else:
        shutil.rmtree(config.STATE_DIR / "mailbox", ignore_errors=True)
        print("Cleared the local mailbox")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="remove demo emails and state first")
    ap.add_argument("--seed", help="generate a random month from this number (or 'random') instead of the fixed one")
    args = ap.parse_args()
    if args.reset:
        reset()
    if args.seed:
        seed = random.SystemRandom().randint(1, 9999) if args.seed == "random" else int(args.seed)
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
        import generate
        generate.main(["--seed", str(seed), "--out", str(config.STATE_DIR / "scenario")])
        print(f"Seed {seed}. Answer key: {config.STATE_DIR / 'scenario' / 'answer_key.json'}")
    problems = config.check()
    if problems:
        sys.exit("\n".join(problems))
    box = get_mailbox()
    emails = json.loads((config.data_dir() / "emails.json").read_text())
    batch = uuid.uuid4().hex[:6]  # fresh ids, so the inbox watcher sees a reseeded month as new mail
    for e in emails:
        box.append(build(e), f"{e['id']}-{batch}")
    where = config.GMAIL_ADDRESS if config.MAIL_BACKEND == "gmail" else config.STATE_DIR / "mailbox" / "inbox"
    print(f"Added {len(emails)} emails to {where}")


if __name__ == "__main__":
    main()
