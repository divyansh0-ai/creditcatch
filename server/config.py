"""Settings for the CreditCatch MCP server, read from the environment (.env)."""

import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# override: the .env file wins over values an IDE copied into the terminal when it opened.
load_dotenv(ROOT / ".env", override=True)


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


MAIL_BACKEND = os.getenv("MAIL_BACKEND", "local").strip().lower()      # "local" or "gmail"
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")

# The inbox whose plus-aliases stand in for vendor addresses in the demo.
DEMO_INBOX = GMAIL_ADDRESS if MAIL_BACKEND == "gmail" else os.getenv("DEMO_INBOX", "accounts@creditcatch.local")
DEMO_MODE = _bool("DEMO_MODE", True)

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data" / "demo"))
STATE_DIR = Path(os.getenv("STATE_DIR", ROOT / "state"))
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

MAX_EMAILS_PER_RUN = int(os.getenv("MAX_EMAILS_PER_RUN", "8"))


def data_dir() -> Path:
    """The month being served: a generated one in state/scenario if present, else the fixed demo month."""
    scenario = STATE_DIR / "scenario"
    return scenario if (scenario / "company.json").exists() else DATA_DIR


def vendor_address(alias: str) -> str:
    local, _, domain = DEMO_INBOX.partition("@")
    return f"{local}+{alias}@{domain}"


def demo_address_pattern() -> re.Pattern:
    local, _, domain = DEMO_INBOX.partition("@")
    return re.compile(rf"^{re.escape(local)}\+[a-z0-9-]+@{re.escape(domain)}$", re.I)


def check() -> list[str]:
    problems = []
    if MAIL_BACKEND not in ("local", "gmail"):
        problems.append(f"MAIL_BACKEND must be 'local' or 'gmail', got {MAIL_BACKEND!r}")
    if MAIL_BACKEND == "gmail":
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", GMAIL_ADDRESS):
            problems.append(f"GMAIL_ADDRESS in .env should be the demo inbox, e.g. you@gmail.com (got {GMAIL_ADDRESS!r})")
        if len(GMAIL_APP_PASSWORD) != 16:
            problems.append(f"GMAIL_APP_PASSWORD in .env should be Google's 16-letter app password "
                            f"(got {len(GMAIL_APP_PASSWORD)} characters). Make one at myaccount.google.com/apppasswords")
    if not (data_dir() / "vendor_master.csv").exists():
        problems.append(f"No demo data in {data_dir()}. Run: python data/generate.py")
    return problems
