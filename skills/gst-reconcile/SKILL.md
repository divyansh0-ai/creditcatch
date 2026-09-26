---
name: gst-reconcile
description: Reconcile a month's purchase invoices from the inbox against the GSTR-2B statement, find input tax credit at risk, and follow up with vendors. Use when asked to reconcile purchases, check ITC, or match invoices with GSTR-2B.
---

# GST purchase reconciliation

You reconcile one tax period for one business. The `creditcatch` MCP server gives you the inbox, the GSTR-2B statement and the vendor list, and it is the only way to send email or save the ITC register.

The scripts next to this file do the parsing and matching. Find them with:

```bash
SKILL_DIR=$(dirname "$(find /opt/tfy/skills -name reconcile.py -path '*gst-reconcile*' | head -1)")
```

## Rules

- **Never do arithmetic yourself.** Every amount you show comes from `report.json`. If a number isn't there, compute it with code in the sandbox and show the code.
- **Say what you are about to do before every write.** One sentence: who, what, why, how much.
- **If a tool refuses, report the reason and stop that action.** Do not rephrase the call to get around a refusal.
- **Ask, don't guess.** Every `number_format_needs_confirmation` finding goes to the user with `ask_user_question`.
- Keep bulk data out of the chat. Print counts and the findings table, not raw JSON or PDF text.

## Steps

### 1. Collect everything in the sandbox (Code Mode)

Write and run a Python script that calls the MCP tools with `from mcp_client import call_tool` and saves results under `/workspace/creditcatch/`:

- `get_company_profile` → `company.json`
- `list_invoice_emails` → for every message and every PDF attachment, `get_invoice_pdf(message_id, filename)`, base64-decode `content_base64`, save as `invoices/<message_id>_<filename>`
- `get_gstr2b(period)` → `gstr2b.json` (period is MMYYYY, e.g. `082026` for August 2026)
- `get_vendor_master` → `vendors.json`

A tool result may arrive as a dict or as a JSON string; handle both. Print only counts (emails, PDFs saved, GSTR-2B suppliers and invoices).

### 2. Read the invoices

```bash
pip install -q pypdf
cd /workspace/creditcatch
python "$SKILL_DIR/extract.py" 'invoices/*.pdf' --text-dir text > books.json
```

`extract.py` only takes a value it can tie to a label, and never guesses. Its last line (on stderr) says how many PDFs it read, which ones need a parser and which ones aren't tax invoices.

- **Not tax invoices** (`looks_like_invoice: false`, e.g. a price list or a statement of account): remove them from `books.json` and mention them in one line. A statement of account repeats invoice numbers; never count one as an invoice.
- **Need a parser** (`needs_manual_parse: true`): these came in a layout the extractor doesn't know. Do step 2b.

### 2b. Write a parser for any layout the extractor can't read

The page text of every PDF, with its spatial layout kept, is in `text/<name>.txt` (the row's `text_file`).

1. Print one of those text files and look at where each field sits. In some layouts the label and the value are in different lines or columns.
2. Write `/workspace/creditcatch/parsers/<layout>.py` with a function that takes the text and returns a row with the same keys as `extract.py`: `source_file`, `supplier_name`, `supplier_gstin`, `buyer_gstin`, `invoice_number`, `invoice_date` (YYYY-MM-DD), `place_of_supply` (2-digit state code), `taxable_value`, `cgst`, `sgst`, `igst`, `tax_rate_pct`, `invoice_total`, `looks_like_invoice: true`, `needs_manual_parse: false`, `parse_warnings: []`. Helpers you can import after `sys.path.insert(0, SKILL_DIR)`: `from gstin import STATES` (state code to name) and `from extract import parse_date`. The supplier's GSTIN comes first on the page and the buyer's second.
3. Run it on every file that needs it, put those rows into `books.json` in place of the unread ones, and check the whole file:

```bash
python "$SKILL_DIR/check_books.py" books.json
```

It must end with every row OK. It checks that each invoice's numbers add up (taxable + tax = total, CGST = SGST, tax matches the rate), so a mis-read field shows up here. Fix the parser and rerun until it passes.
4. If a file still fails after two fixes, don't guess its numbers. Leave it out, and in your summary name it as not read and ask the user to check it.

Tell the user in one line that you found a layout the extractor couldn't read, wrote a parser for it, and how many invoices it read.

### 2c. Match against GSTR-2B

```bash
python "$SKILL_DIR/reconcile.py" --books books.json --gstr2b gstr2b.json > report.json
```

Then write a short script that prints `report["summary"]` and one line per finding: category, invoice number, supplier, ITC at risk, suggested action.

What each category means:

| category | meaning | what to do |
|---|---|---|
| `missing_in_2b` | supplier hasn't reported the invoice; ITC can't be claimed | email supplier to file it in GSTR-1 |
| `value_mismatch` | supplier reported a different value; only the GSTR-2B tax is claimable | email supplier to amend GSTR-1 |
| `wrong_tax_head` | inter-state supply charged as CGST+SGST instead of IGST | email supplier for a corrected invoice |
| `invalid_gstin_on_invoice` | GSTIN on the invoice fails the checksum | email supplier for a corrected invoice |
| `billed_to_other_gstin` | invoice is made out to a different GSTIN, so the credit won't reach this business | email supplier to cancel it and reissue to the right GSTIN |
| `itc_not_available_in_2b` | supplier reported it, but GSTR-2B marks the ITC as not available | tell the user; don't claim it; no email |
| `number_format_needs_confirmation` | same supplier, date and amount, different invoice number | ask the user |
| `duplicate_in_books` | the same invoice arrived twice; counted once | mention it, no email |
| `in_2b_not_in_books` | supplier reported an invoice the business never received | tell the user, no email |
| `unreadable_invoice` | a row still needs a parser | go back to step 2b before reporting |

### 3. Show the result

Lead with the headline: invoices checked, clean matches, and **ITC at risk** (`summary.itc_at_risk`). Then the findings table, grouped by category. Use a rendered table if the UI supports it.

### 4. Confirm fuzzy matches

For each `number_format_needs_confirmation` finding, call `ask_user_question` with the finding's `detail`. A yes makes it a match (claim it under the GSTR-2B invoice number). A no makes it `missing_in_2b`.

### 5. Email vendors

One email per vendor, covering all of that vendor's actionable findings (`missing_in_2b`, `value_mismatch`, `wrong_tax_head`, `invalid_gstin_on_invoice`, `billed_to_other_gstin`). If a supplier isn't in the vendor master, the server will refuse; tell the user instead. Write it like an accounts executive would: polite, specific, short. Include the invoice number, date, amounts from the report, what is wrong, and exactly what you need them to do and by when (before the 11th of next month, the GSTR-1 due date). Sign it as the business's Accounts team.

Call `send_vendor_email(supplier_gstin, subject, body, invoice_numbers)`. You pick the vendor by GSTIN; the server looks up the address. Every invoice number you list must appear in the body. Each call waits for human approval.

### 6. Save the ITC register

Build the claims with code from `report.json`:
- every `matched` invoice at its ITC,
- every confirmed fuzzy match, under its GSTR-2B invoice number,
- every `value_mismatch` at the GSTR-2B tax only.

Hold back everything else, including `itc_not_available_in_2b`. Call `save_itc_register(period, claims, notes)`; it waits for approval, and the server refuses any claim that GSTR-2B doesn't support.

### 7. Wrap up

Two or three sentences: ITC claimed now, ITC at risk and which vendors were emailed, and anything the user still needs to check (`in_2b_not_in_books`, `itc_not_available_in_2b`, any invoice you couldn't read).
