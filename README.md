# CreditCatch

An agent that does a small Indian business's monthly GST purchase reconciliation. It reads the purchase invoices from the inbox, matches them against the GSTR-2B statement in a sandbox, shows how much input tax credit (ITC) is at risk, and emails vendors whose filings are wrong, but only after you approve each email.

Built on [TrueForge](https://trueforge.dev) for the TrueFoundry × Polaris "Agents That Act" hackathon, 26 September 2026.

## Why this job

When a business buys something it pays GST to the supplier and can claim that tax back as ITC. It can only claim it if the supplier reported the same invoice to the government, which shows up in the buyer's monthly GSTR-2B statement. When an invoice is missing there, or the amount or tax head is wrong, the credit is lost until the supplier fixes it. Accountants match these by hand every month and then chase each vendor by email.

In the demo month, CreditCatch finds **₹1,05,000 of ITC at risk** across 15 invoices from 8 vendors.

## How it works

```mermaid
flowchart LR
  U([You in TrueForge chat]) --> A[CreditCatch agent<br/>instructions + model]
  A -- MCP tools --> M[creditcatch MCP server<br/>server/]
  M -- read-only --> G[(Inbox: invoice PDFs)]
  M --> P[(GSTR-2B JSON)]
  M -- guarded send --> V[Vendor email]
  M --> L[(state/audit.jsonl)]
  A -- writes and runs code --> S[Daytona sandbox<br/>gst-reconcile skill]
```

| Part | What it is |
|---|---|
| `server/` | The MCP server. Read tools for the inbox, GSTR-2B and vendor list. Two write tools, `send_vendor_email` and `save_itc_register`, marked destructive and guarded in code. Every call is logged to `state/audit.jsonl`. |
| `skills/gst-reconcile/` | The TrueForge skill: `SKILL.md` (the procedure), `extract.py` (invoice PDF to fields), `gstin.py` (GSTIN checksum), `reconcile.py` (books vs GSTR-2B). |
| `agent/instructions.md` | The agent's system prompt. |
| `data/generate.py` | Builds the synthetic demo data in `data/demo/`: invoice PDFs, the emails that carry them, a GSTR-2B file and a vendor master. |
| `scripts/seed_inbox.py` | Puts the demo emails into the inbox, and resets the demo. |

In a run, the agent writes a Python script that runs in the Daytona sandbox and pulls every PDF and the GSTR-2B through the MCP tools (TrueForge Code Mode, so no credentials enter the sandbox). It then runs the skill's scripts to extract and match, asks you about anything ambiguous, drafts one email per vendor, and saves the ITC register.

## What it catches

| Finding | Example in the demo data |
|---|---|
| Invoice missing from GSTR-2B | `MS/0823`: the supplier never filed it |
| Value differs from GSTR-2B | `SP/26-27/0419`: ₹2,50,000 in books, ₹2,05,000 reported |
| Wrong tax head | `PBE/26/0057`: a Maharashtra supplier charged CGST+SGST to a Karnataka buyer |
| Invalid GSTIN on the invoice | `CFS/AUG/044`: fails the GSTIN checksum |
| Same invoice, different number format | `KFM-118` vs `KFM/2026-27/118`: you're asked to confirm |
| Duplicate in the inbox | `DDP/0902` forwarded twice, counted once |
| In GSTR-2B but not in books | `SST/774`: reported by the supplier, never received |

## Safety boundaries

**Held for a human in TrueForge:** every `send_vendor_email` and `save_itc_register` call, plus a question whenever two invoices only look alike.

**Enforced by the server, whatever the model or the approver does:**
- The agent never types an email address. It names a vendor by GSTIN and the server looks up the address in the vendor master. Unknown GSTINs are refused.
- In demo mode the recipient must be a plus-alias of the demo inbox, so nothing can reach a real company.
- One email per vendor per run, and at most `MAX_EMAILS_PER_RUN` in total. Every invoice number the email is about must appear in its body.
- `save_itc_register` refuses any claim that isn't in that period's GSTR-2B, or that claims more tax than GSTR-2B shows.
- The inbox is opened read-only and fetched with `BODY.PEEK`, so nothing is even marked read. There is no delete tool and no tool that edits the books.
- Model and mail credentials stay on the TrueForge server and in `.env`; the sandbox only receives tool results.
- Every tool call, allowed or refused, is appended to `state/audit.jsonl`.

## Run it

You need Python 3.11+, Node 22.14+, a Daytona API key (permissions below), and an API key for a model TrueForge supports.

### 1. Start the MCP server

```bash
git clone https://github.com/divyansh0-ai/creditcatch.git
cd creditcatch
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # MAIL_BACKEND=local works with no accounts
python data/generate.py           # rebuilds data/demo (already committed)
python scripts/seed_inbox.py --reset
python -m server                  # http://127.0.0.1:8000/mcp
```

On Windows PowerShell:

```powershell
git clone https://github.com/divyansh0-ai/creditcatch.git
cd creditcatch
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python scripts/seed_inbox.py --reset
python -m server
```

If `python -m server` says the port is in use (`WinError 10048` on Windows), a server is already running on port 8000. Use that one or stop it first.

Check it without a model (in a second terminal):

```bash
python tests/e2e_mcp.py           # downloads every PDF over MCP, reconciles, tests the guards
```

### 2. Set up TrueForge

TrueForge blocks connectors on `localhost` by default, so start it with its network policy relaxed. Otherwise adding the connector fails with `Outbound URL blocked for host localhost`.

```bash
NETWORK_POLICY_ENABLED=false npx @truefoundry/trueforge@latest     # opens http://localhost:8790
```

On Windows PowerShell, set the variable in the same window first:

```powershell
$env:NETWORK_POLICY_ENABLED="false"
npx @truefoundry/trueforge@latest
```

1. **Settings → Models:** add your model provider.
2. **Settings → Sandbox providers:** add Daytona with your API key. The key needs `write:sandboxes`, `write:snapshots` and `delete:snapshots` (a Full access key works); with less, setup fails with "missing required permissions". The first setup builds a snapshot and takes a few minutes.
3. **Settings → Connectors → Add MCP Server:** name `creditcatch`, URL `http://localhost:8000/mcp`, no auth.
4. **Settings → Skills:** repository `https://github.com/divyansh0-ai/creditcatch`, path `skills/gst-reconcile`, ref `main`. The repository has to be public for TrueForge to fetch it.
5. **Build Agent:**
   - Name `CreditCatch`, pick your model, and paste `agent/instructions.md` as the instructions.
   - Attach the `creditcatch` connector with all tools, and set **require approval** for `send_vendor_email` and `save_itc_register`.
   - Add the `gst-reconcile` skill. Turn on the sandbox, clarifying questions, and file downloads.
6. Open a chat with the agent and send: **Reconcile our August 2026 purchases.**

### 3. Use a real Gmail inbox (optional)

Make a throwaway Gmail account, turn on 2-Step Verification, create an app password, then set this in `.env`:

```
MAIL_BACKEND=gmail
GMAIL_ADDRESS=your-demo@gmail.com
GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
```

Run `python scripts/seed_inbox.py --reset`. The demo emails are appended straight into the inbox over IMAP, and vendor emails go to plus-aliases like `your-demo+shreepack@gmail.com`, so they land back in the same inbox where you can show them. `--reset` moves every demo message to Trash and clears `state/`.

## Demo

The five-minute demo script is in [docs/DEMO.md](docs/DEMO.md) and the submission write-up in [docs/SUBMISSION.md](docs/SUBMISSION.md).

## Tests

```bash
python -m server &                # with MAIL_BACKEND=local and a seeded inbox
python tests/e2e_mcp.py
```

It checks that all seven planted problems are found, that ITC at risk is exactly ₹1,05,000, and that the server refuses an unknown GSTIN, a body that doesn't cite its invoices, a second email to the same vendor, and an ITC claim that GSTR-2B doesn't support.

## Limitations

- GSTR-2B comes from a saved file. The GST portal's API is only open to licensed GST Suvidha Providers, so the tool stands in for the file a taxpayer downloads from the portal.
- `extract.py` reads text PDFs, not scans. OCR would be the next step.
- All companies, GSTINs and amounts are synthetic.

## AI tools used

This project was built with help from Claude (Anthropic) through Claude Code, for planning, writing code and writing this README. The agent itself runs on TrueForge with whichever model you configure.

## License

MIT, see [LICENSE](LICENSE).
