"""Mailbox backends: a local folder of .eml files, or a real Gmail inbox.

Both expose the same three operations:
  list_messages()                 -> messages that carry PDF attachments
  get_attachment(msg_id, name)    -> bytes
  send(msg)                       -> message id
Reading never changes the mailbox: Gmail is opened read-only and fetched
with BODY.PEEK so nothing is even marked as read.
"""

import email
import imaplib
import smtplib
import uuid
from email import policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from . import config

DEMO_HEADER = "X-CreditCatch-Demo"


def _summary(msg_id: str, msg: email.message.Message) -> dict | None:
    pdfs = [part.get_filename() for part in msg.walk()
            if part.get_filename() and part.get_filename().lower().endswith(".pdf")]
    if not pdfs:
        return None
    try:
        sent = parsedate_to_datetime(msg["Date"]).isoformat()
    except (TypeError, ValueError):
        sent = msg.get("Date")
    return {"message_id": msg_id, "from": str(msg.get("From", "")), "subject": str(msg.get("Subject", "")),
            "date": sent, "attachments": pdfs}


def _attachment(msg: email.message.Message, name: str) -> bytes:
    for part in msg.walk():
        if part.get_filename() == name:
            return part.get_payload(decode=True)
    raise KeyError(f"No attachment named {name!r} on this message")


class LocalMailbox:
    def __init__(self):
        self.inbox = config.STATE_DIR / "mailbox" / "inbox"
        self.outbox = config.STATE_DIR / "mailbox" / "outbox"
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.outbox.mkdir(parents=True, exist_ok=True)

    def _load(self, msg_id: str):
        path = self.inbox / f"{msg_id}.eml"
        if not path.resolve().is_relative_to(self.inbox.resolve()) or not path.exists():
            raise KeyError(f"No message {msg_id!r}")
        return email.message_from_bytes(path.read_bytes(), policy=policy.default)

    def list_messages(self) -> list[dict]:
        out = []
        for path in sorted(self.inbox.glob("*.eml")):
            s = _summary(path.stem, email.message_from_bytes(path.read_bytes(), policy=policy.default))
            if s:
                out.append(s)
        return out

    def get_attachment(self, msg_id: str, name: str) -> bytes:
        return _attachment(self._load(msg_id), name)

    def append(self, msg: EmailMessage, msg_id: str):
        (self.inbox / f"{msg_id}.eml").write_bytes(bytes(msg))

    def send(self, msg: EmailMessage) -> str:
        msg_id = f"sent-{uuid.uuid4().hex[:10]}"
        (self.outbox / f"{msg_id}.eml").write_bytes(bytes(msg))
        return msg_id


class GmailMailbox:
    IMAP_HOST, SMTP_HOST = "imap.gmail.com", "smtp.gmail.com"

    def _imap(self, readonly=True):
        conn = imaplib.IMAP4_SSL(self.IMAP_HOST)
        conn.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
        conn.select("INBOX", readonly=readonly)
        return conn

    def _fetch(self, conn, uid: str):
        typ, data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
        if typ != "OK" or not data or data[0] is None:
            raise KeyError(f"No message {uid!r}")
        return email.message_from_bytes(data[0][1], policy=policy.default)

    def list_messages(self) -> list[dict]:
        conn = self._imap()
        try:
            typ, data = conn.uid("SEARCH", None, "ALL")
            uids = data[0].split()[-200:]   # most recent 200 is plenty for one month
            out = []
            for uid in uids:
                s = _summary(uid.decode(), self._fetch(conn, uid.decode()))
                if s:
                    out.append(s)
            return out
        finally:
            conn.logout()

    def get_attachment(self, msg_id: str, name: str) -> bytes:
        if not msg_id.isdigit():
            raise KeyError(f"No message {msg_id!r}")
        conn = self._imap()
        try:
            return _attachment(self._fetch(conn, msg_id), name)
        finally:
            conn.logout()

    def append(self, msg: EmailMessage, msg_id: str):
        conn = imaplib.IMAP4_SSL(self.IMAP_HOST)
        conn.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
        try:
            when = imaplib.Time2Internaldate(parsedate_to_datetime(msg["Date"]))
            conn.append("INBOX", "", when, bytes(msg))
        finally:
            conn.logout()

    def send(self, msg: EmailMessage) -> str:
        with smtplib.SMTP_SSL(self.SMTP_HOST, 465) as smtp:
            smtp.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        return str(msg["Message-ID"])

    def trash_demo_messages(self) -> int:
        """Used only by scripts/seed_inbox.py --reset, never by the agent."""
        conn = self._imap(readonly=False)
        try:
            typ, data = conn.uid("SEARCH", None, f'HEADER {DEMO_HEADER} ""')
            uids = data[0].split()
            for uid in uids:
                conn.uid("STORE", uid, "+X-GM-LABELS", "\\Trash")
            conn.expunge()
            return len(uids)
        finally:
            conn.logout()


def get_mailbox():
    return GmailMailbox() if config.MAIL_BACKEND == "gmail" else LocalMailbox()
