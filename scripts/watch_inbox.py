"""Start CreditCatch by itself when invoice emails arrive.

    python scripts/watch_inbox.py
    python scripts/watch_inbox.py --agent creditcatch --every 15 --month "August 2026"

Watches the inbox the MCP server reads: the Gmail inbox over IMAP when
MAIL_BACKEND=gmail, the local folder otherwise. When new emails with PDF
attachments arrive, it waits a few seconds for the rest of the batch, then
opens a new TrueForge session with the saved CreditCatch agent, tells it
what arrived, and opens that session in your browser. Nothing is sent
without you: vendor emails and the ITC register still stop in TrueForge for
your approval.

Only emails that arrive after the watcher starts count (use
--include-existing to treat what's already there as new). The watcher only
reads mail; it never marks, moves or deletes anything. Leave it running in
its own terminal next to the MCP server and TrueForge.
"""

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import config, ledger  # noqa: E402
from server.mailbox import get_mailbox  # noqa: E402


def log(msg: str):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


class TrueForge:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def _call(self, method: str, path: str, body=None) -> dict:
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"TrueForge {method} {path} -> {e.code}: {e.read()[:300].decode(errors='replace')}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"can't reach TrueForge at {self.base} ({e.reason}). Is it running?") from e

    def agent_names(self) -> list[str]:
        data = self._call("GET", "/api/v1/agents?limit=100").get("data", [])
        return [a.get("name") for a in data if isinstance(a, dict)]

    def resolve_agent(self, wanted: str) -> str:
        names = self.agent_names()
        for n in names:
            if n == wanted:
                return n
        for n in names:
            if wanted.lower().replace(" ", "-") in n.lower():
                return n
        raise RuntimeError(f"no saved agent named {wanted!r}. Saved agents: {names or 'none'}. "
                           "Save the agent in Build Agent first (Save Agent), then pass --agent <name>.")

    def start(self, agent: str, message: str) -> tuple[str, str]:
        session = self._call("POST", "/api/v1/sessions", {"agent": {"name": agent}})["data"]
        turn = self._call("POST", f"/api/v1/sessions/{session['id']}/turns",
                          {"input": [{"type": "user.message", "content": message}], "stream": False})["data"]
        return session["id"], turn["id"]

    def turn_status(self, session_id: str, turn_id: str) -> dict:
        return self._call("GET", f"/api/v1/sessions/{session_id}/turns/{turn_id}")["data"]["state"]


def follow(tf: TrueForge, session_id: str, turn_id: str, url: str):
    """Report how the first turn of a run ends, so the terminal says when approval is needed."""
    last = None
    for _ in range(720):
        try:
            state = tf.turn_status(session_id, turn_id)
        except RuntimeError as e:
            log(f"  could not check the run: {e}")
            return
        status = state.get("status")
        if status != last:
            if status == "paused" or (status == "done" and state.get("required_actions")):
                log(f"  run is waiting for you (approval or a question): {url}")
            elif status == "done":
                log(f"  run finished: {url}")
            elif status in ("error", "cancelled"):
                log(f"  run {status}: {json.dumps(state)[:300]}")
            last = status
        if status in ("paused", "done", "error", "cancelled"):
            return
        time.sleep(5)


def describe(msgs: list[dict], month: str) -> str:
    lines = [f"- {m['from']}: \"{m['subject']}\" ({len(m['attachments'])} PDF: {', '.join(m['attachments'])})"
             for m in msgs]
    return ("New email with invoices just arrived in the inbox:\n" + "\n".join(lines) +
            f"\n\nReconcile our {month} purchases with everything now in the inbox, and follow up with any "
            "vendor whose filing is wrong. Anything you send or save waits for my approval.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent", default="creditcatch", help="saved TrueForge agent name (default: creditcatch)")
    ap.add_argument("--trueforge", default="http://localhost:8790", help="TrueForge URL")
    ap.add_argument("--month", default="August 2026", help="tax period to reconcile")
    ap.add_argument("--every", type=float, default=15, help="seconds between inbox checks")
    ap.add_argument("--settle", type=float, default=20, help="seconds with no new mail before starting a run")
    ap.add_argument("--include-existing", action="store_true", help="treat mail already in the inbox as new")
    ap.add_argument("--no-browser", action="store_true", help="don't open the run in a browser")
    ap.add_argument("--once", action="store_true", help="start at most one run, then exit")
    args = ap.parse_args(argv)

    problems = config.check()
    if problems:
        sys.exit("\n".join(problems))
    tf = TrueForge(args.trueforge)
    try:
        agent = tf.resolve_agent(args.agent)
    except RuntimeError as e:
        sys.exit(f"Can't start: {e}")

    box = get_mailbox()
    seen = set() if args.include_existing else set(box.ids())
    where = config.GMAIL_ADDRESS if config.MAIL_BACKEND == "gmail" else config.STATE_DIR / "mailbox" / "inbox"
    log(f"Watching {where} every {args.every:g}s for invoice emails ({len(seen)} already there). "
        f"New ones start agent '{agent}'. Ctrl+C to stop.")

    pending, last_new = [], 0.0
    while True:
        try:
            ids = box.ids()
            fresh = [i for i in ids if i not in seen]
            for msg_id in fresh:
                seen.add(msg_id)
                s = box.summary(msg_id)
                if s:
                    ledger.record_emails([s])
                    pending.append(s)
                    last_new = time.time()
                    log(f"Invoice email from {s['from']}: {s['subject']} ({len(s['attachments'])} PDF)")
            if pending and time.time() - last_new >= args.settle:
                batch, pending = pending, []
                log(f"Starting CreditCatch for {len(batch)} new email(s)...")
                try:
                    session_id, turn_id = tf.start(agent, describe(batch, args.month))
                except RuntimeError as e:
                    log(f"  couldn't start the run: {e}")
                    pending = batch + pending
                    last_new = time.time()
                else:
                    url = f"{args.trueforge.rstrip('/')}/sessions/{session_id}"
                    log(f"  run started: {url}")
                    if not args.no_browser:
                        webbrowser.open(url)
                    if args.once:
                        follow(tf, session_id, turn_id, url)
                        return
                    threading.Thread(target=follow, args=(tf, session_id, turn_id, url), daemon=True).start()
        except KeyboardInterrupt:
            raise
        except Exception as e:  # a dropped IMAP connection shouldn't kill the watcher
            log(f"Inbox check failed ({e}); trying again.")
        time.sleep(args.every if not pending else min(args.every, 3))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
