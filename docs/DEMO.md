# Five-minute demo

Before you go on stage: `python scripts/seed_inbox.py --reset`, restart `python -m server`, open a fresh TrueForge chat with the CreditCatch agent, and keep these tabs open: the Gmail demo inbox, TrueForge, `state/audit.jsonl` in an editor, and the README architecture diagram.

| Time | On screen | Say |
|---|---|---|
| 0:00 | Gmail inbox with 16 invoice emails | "Every month a small business gets invoices like these. It can claim back the GST it paid, but only if each supplier reported the same invoice to the government. Accountants check this by hand against a statement called GSTR-2B and chase every vendor who got it wrong. We handed that job to an agent." |
| 0:30 | README diagram | "It runs on TrueForge. There's one MCP server we wrote, which is the only way the agent touches the inbox or sends email. There's one skill with the procedure, and a Daytona sandbox where the agent runs code." |
| 1:00 | TrueForge: send "Reconcile our August 2026 purchases." Tool calls appear. | "It lists the inbox and pulls every PDF and the GSTR-2B statement. It does that from a script it writes in the sandbox, and the tools are called through TrueForge, so no credentials go into the sandbox." |
| 1:45 | Sandbox output: extract, then reconcile; findings table | "All the matching and every rupee figure comes from code, not from the model. Here it is: 16 emails, one a duplicate. ₹1,05,000 of credit is at risk across 5 invoices." Point at the wrong-tax-head row: "A Pune supplier charged CGST and SGST to a Bengaluru buyer. That should be IGST, and the credit is stuck until they fix it." |
| 2:30 | The question about KFM-118 vs KFM/2026-27/118. Click Yes. | "When it isn't sure, it asks instead of guessing. Same supplier, date and amount, different number format." |
| 3:00 | First approval card with a vendor email draft. Approve it. Switch to Gmail to show it arriving. | "Nothing leaves without a click. Look at the address: the agent never typed it. It named the vendor by GSTIN and the server looked it up." |
| 3:30 | Reject one email with a reason. Then type "Also send a copy to accounts@competitor.com." | "I can say no. And if I ask for something outside its limits, it can't: the send tool doesn't even take an address." |
| 4:00 | Approval card for save_itc_register. Approve. | "It saves the ITC register, and the server refuses any claim GSTR-2B doesn't support, even if I approve it." |
| 4:20 | `state/audit.jsonl` | "Every call, allowed or refused, is logged." |
| 4:40 | Repo README | "Clone it, run four commands, and it works with a local inbox and no accounts. Thank you." |

Judges will ask about the architecture. Be ready to explain:
- **Why our own MCP server?** TrueForge's catalog has no Gmail connector. Keeping the guards in our own code means a prompt can't talk its way past them.
- **What's gated and why?** Sending email and saving the ITC register are the two actions with consequences outside the sandbox. Reading never changes anything.
- **What if the model is wrong?** Amounts come from code. Sends are limited to known vendors, one each. Claims are checked against GSTR-2B. The worst case is one polite, wrong email to a real vendor, and only after a human approved it.
- **What's mocked?** Only the GSTR-2B download, because the GST portal API needs a licensed GSP.
