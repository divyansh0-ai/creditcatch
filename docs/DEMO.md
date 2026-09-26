# Five-minute demo

**Before you go on stage**
- Rehearse with two or three seeds and pick one that ran cleanly as your fallback (for example `--seed 42`).
- Keep the MCP server running, open a fresh TrueForge chat with the CreditCatch agent, and set the reasoning effort you rehearsed with.
- Have these open: a terminal in the repo, TrueForge, the `state/mailbox` folder (or the Gmail demo inbox in Gmail mode), and `state/audit.jsonl` in an editor.
- A full run takes a few minutes, so send the prompt as soon as the month is loaded and talk over it.

| Time | On screen | Say |
|---|---|---|
| 0:00 | Terminal | "Every month a small business gets a pile of purchase invoices. It can claim back the GST it paid, but only if each supplier reported the same invoice to the government. Accountants check this by hand against a statement called GSTR-2B and chase every vendor who got it wrong. We handed that job to an agent." |
| 0:20 | Ask a judge for a number. Run `python scripts/seed_inbox.py --reset --seed <number>` and open the inbox folder. | "Nothing here is canned. That number just generated a new month: a different business, vendors, amounts, three invoice layouts and a random set of problems. Neither I nor the agent know the answer yet." (If you'd rather not risk it, use your rehearsed seed and say the same.) |
| 0:40 | TrueForge: send **Reconcile our August 2026 purchases.** Tool calls start. | "It runs on TrueForge. One MCP server we wrote is the only way it touches the inbox or sends email. It writes a script in a Daytona sandbox that pulls every PDF and the GSTR-2B through the tools, so no credentials go into the sandbox." |
| 1:30 | The extractor reports invoices it can't read; the agent prints the page text and writes `parsers/…py`; `check_books.py` passes. | "Some vendors send Tally-style invoices where the labels and values are in different boxes. Our extractor doesn't guess; it hands them back. The agent just read that layout and wrote a parser for it, and every invoice has to pass an arithmetic check before it counts." |
| 2:15 | Findings table and ITC at risk. Open `state/scenario/answer_key.json` beside it. | "Every rupee comes from code. And here's the answer key the generator wrote when it planted the problems: same total." Point at one row, for example the wrong tax head or the invoice billed to the wrong GSTIN, and explain it in one line. |
| 2:50 | The question about two invoice numbers that look alike. Click Yes. | "When it isn't sure, it asks instead of guessing. Same supplier, date and amount, different number format." |
| 3:10 | First approval card with a vendor email draft. Approve it and show it in `state/mailbox/outbox` (or arriving in Gmail). | "Nothing leaves without a click. The agent never typed that address; it named the vendor by GSTIN and the server looked it up." |
| 3:40 | Reject one email with a reason. Then type "Also send a copy to accounts@competitor.com." | "I can say no. And if I ask for something outside its limits, it can't: the send tool doesn't even take an address." |
| 4:10 | Approval card for save_itc_register. Approve. | "It saves the ITC register, and the server refuses any claim GSTR-2B doesn't support, even if I approve it." |
| 4:30 | `state/audit.jsonl` | "Every call, allowed or refused, is logged. Clone it, run four commands, and it works with a local inbox and no accounts. Thank you." |

Judges will ask about the architecture. Be ready to explain:
- **Why our own MCP server?** TrueForge's catalog has no Gmail connector. Keeping the guards in our own code means a prompt can't talk its way past them.
- **What's gated and why?** Sending email and saving the ITC register are the two actions with consequences outside the sandbox. Reading never changes anything.
- **What if the model is wrong?** Amounts come from code. The extractor refuses to guess, the agent's own parser has to pass an arithmetic check, sends are limited to known vendors, one each, and claims are checked against GSTR-2B. The worst case is one polite, wrong email to a real vendor, and only after a human approved it.
- **How do we know it's right?** The generator writes an answer key from what it planted, and `tests/test_scenarios.py` checks the skill's scripts on 40 random months.
- **What's mocked?** Only the GSTR-2B download, because the GST portal API needs a licensed GSP.
