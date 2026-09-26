"""Put the demo invoice emails into the inbox, or reset the demo.

    python scripts/seed_inbox.py                       # add the fixed demo month's 16 emails
    python scripts/seed_inbox.py --reset               # clear the inbox and run state, then add them again
    python scripts/seed_inbox.py --reset --seed 42     # clear, then generate and add a new random month
    python scripts/seed_inbox.py --reset --seed random # same, with a seed picked for you
    python scripts/seed_inbox.py --reset --seed 42 --hold-back   # keep one invoice out for a live email
    python scripts/seed_inbox.py --deliver-held        # deliver that held-back email now (no Gmail needed)

A random month has a different business, vendors, invoice layouts, amounts
and problems for every seed. It is written to state/scenario/ and the MCP
server serves it straight away (no restart). The answer key is in
state/scenario/answer_key.json. A plain --reset goes back to the fixed month.

With MAIL_BACKEND=gmail the emails are appended straight into the Gmail
inbox over IMAP (no second account needed) and --reset moves the ones it
added, plus any email carrying the held-back invoice, to Trash. With
MAIL_BACKEND=local they are .eml files under state/mailbox/.
"""

import argparse
import imaplib
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


def hold_back(emails: list[dict]) -> dict | None:
    """The latest email that carries only real invoices (not a forward, price list or statement)."""
    key_path = config.data_dir() / "answer_key.json"
    if not key_path.exists():
        key_path = Path(__file__).resolve().parent.parent / "tests" / "answer_key.json"
    invoices = set(json.loads(key_path.read_text()).get("layouts", {}))
    seen, candidates = set(), []
    for e in sorted(emails, key=lambda e: e["date"]):
        names = e.get("attachments") or [e["attachment"]]
        if all(n in invoices and n not in seen for n in names):
            candidates.append(e | {"attachments": names})
        seen.update(names)
    if not candidates:
        return None
    pick = candidates[-1]
    return next(e for e in emails if e["id"] == pick["id"]) | {"attachments": pick["attachments"]}


def reset():
    if config.MAIL_BACKEND == "gmail":
        # The held-back invoice may have been emailed in live; clear that email too.
        live = [p.name for p in (config.STATE_DIR / "live_demo").glob("*.pdf")]
        n = GmailMailbox().trash_demo_messages(live)
        print(f"Moved {n} demo emails to Gmail Trash")
    else:
        shutil.rmtree(config.STATE_DIR / "mailbox", ignore_errors=True)
        print("Cleared the local mailbox")
    for name in ("audit.jsonl", "sent_log.jsonl"):
        (config.STATE_DIR / name).unlink(missing_ok=True)
    shutil.rmtree(config.STATE_DIR / "live_demo", ignore_errors=True)
    for pattern in ("itc_register_*", "gstr3b_table4_*", "creditcatch.db"):
        for p in config.STATE_DIR.glob(pattern):
            p.unlink()
    shutil.rmtree(config.STATE_DIR / "scenario", ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="remove demo emails and state first")
    ap.add_argument("--seed", help="generate a random month from this number (or 'random') instead of the fixed one")
    ap.add_argument("--hold-back", action="store_true",
                    help="leave one vendor's invoice email out and save its PDF to state/live_demo/, "
                         "so you can email it to the inbox yourself during the demo")
    ap.add_argument("--deliver-held", action="store_true",
                    help="put the held-back invoice email into the inbox now, as if the vendor just sent it "
                         "(the live moment without sending a real email)")
    args = ap.parse_args()
    problems = [p for p in config.check() if "demo data" not in p]
    if problems:
        sys.exit("\n".join(problems))
    print(f"Mail: {config.GMAIL_ADDRESS + ' (Gmail)' if config.MAIL_BACKEND == 'gmail' else 'local folder (MAIL_BACKEND=local)'}")
    if args.deliver_held:
        return deliver_held()
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
    held = hold_back(emails) if args.hold_back else None
    if held:
        emails = [e for e in emails if e["id"] != held["id"]]
    for e in emails:
        box.append(build(e), f"{e['id']}-{batch}")
    where = config.GMAIL_ADDRESS if config.MAIL_BACKEND == "gmail" else config.STATE_DIR / "mailbox" / "inbox"
    print(f"Added {len(emails)} emails to {where}")
    if held:
        out = config.STATE_DIR / "live_demo"
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
        for name in held["attachments"]:
            shutil.copy(config.data_dir() / "invoices" / name, out / name)
        (out / "email.json").write_text(json.dumps(held, indent=2))
        print(f"Held back {held['from_name']}'s invoice email. During the demo, email "
              f"{', '.join(held['attachments'])} from {out} to {config.GMAIL_ADDRESS or 'the inbox'} "
              f"(subject: {held['subject']!r}), or run: python scripts/seed_inbox.py --deliver-held")


def deliver_held():
    path = config.STATE_DIR / "live_demo" / "email.json"
    if not path.exists():
        sys.exit("Nothing held back. Run: python scripts/seed_inbox.py --reset --seed <n> --hold-back")
    e = json.loads(path.read_text())
    msg = build(e)
    del msg["Date"]
    msg["Date"] = format_datetime(datetime.now().astimezone())
    get_mailbox().append(msg, f"{e['id']}-live-{uuid.uuid4().hex[:6]}")
    where = config.GMAIL_ADDRESS if config.MAIL_BACKEND == "gmail" else config.STATE_DIR / "mailbox" / "inbox"
    print(f"Delivered {e['from_name']}'s invoice email ({', '.join(e['attachments'])}) to {where}")


if __name__ == "__main__":
    try:
        main()
    except imaplib.IMAP4.error as e:
        sys.exit(f"Gmail refused the login or a command: {e}\n"
                 "Check GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env (an app password, not your normal password; "
                 "it needs 2-Step Verification on that account).")
