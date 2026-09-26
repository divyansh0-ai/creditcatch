# CreditCatch: submission write-up

**Repo:** https://github.com/divyansh0-ai/creditcatch

## The problem

Indian businesses can claim back the GST they pay on purchases (input tax credit, ITC), but only for invoices their suppliers reported correctly. Each month an accountant matches every purchase invoice against the government's GSTR-2B statement by hand, works out which credit is at risk, and chases each vendor by email. It's tedious and needs care, and a missed mismatch costs real money, which makes it a good job to hand to an agent that has a human sign-off.

## What the agent does

Asked to "Reconcile our August 2026 purchases", CreditCatch, running on TrueForge:

1. Reads the invoice emails and downloads each PDF through our MCP server, from code it writes and runs in a Daytona sandbox.
2. Runs the `gst-reconcile` skill's scripts in the sandbox to extract invoice fields, validate GSTIN checksums and match the books against GSTR-2B. Every rupee figure comes from code, not the model.
3. Asks the user when two invoices only look alike (`KFM-118` vs `KFM/2026-27/118`).
4. Drafts one email per vendor with a problem and holds each one for approval.
5. Saves the ITC register after approval.

On the demo data (15 invoices, 8 vendors, 7 planted problems) it finds all 7 and reports ₹1,05,000 of ITC at risk. It claims ₹1,40,605 that GSTR-2B supports and emails the 4 vendors at fault.

## Safety boundaries

- **Held for a human in TrueForge:** `send_vendor_email` and `save_itc_register`, plus a question on any fuzzy invoice match.
- **Enforced in the MCP server regardless of the model or the approver:**
  - The agent can't type an email address. It names a vendor by GSTIN and the server looks up the address.
  - Unknown GSTINs are refused.
  - One email per vendor per run, and the body must cite the invoices it's about.
  - Register claims not backed by GSTR-2B are refused.
  - The inbox is read-only.
  - Every call is written to an audit log.
- Credentials never enter the sandbox. It only sees tool results.

## Architecture

TrueForge agent (model, instructions, skill) → our own FastMCP server (inbox, GSTR-2B, vendor master, guarded send and save) → Daytona sandbox running the agent's generated Python plus the skill scripts. It works with no accounts at all using a local inbox, or with a real Gmail inbox via an app password.

## What's mocked

Only the GSTR-2B download: the GST portal API is open only to licensed GST Suvidha Providers, so the server serves the JSON file a taxpayer would download. All companies and amounts are synthetic.

## Built with

TrueForge, Daytona, the MCP Python SDK, pypdf and reportlab. The model we used was OpenAI's gpt-5.4-mini. We used Claude Code to help plan and write code.
