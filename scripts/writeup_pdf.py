"""Render the README's "## Write-up" section as WRITEUP.pdf in the repo root.

    python scripts/writeup_pdf.py

Run it again after editing the write-up so the two stay the same.
"""

import html
import re
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/divyansh0-ai/creditcatch"


def section() -> list[str]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    body = text.split("\n## Write-up\n", 1)[1].split("\n## ", 1)[0]
    return [p.strip() for p in body.split("\n\n") if p.strip() and not p.startswith("The same write-up is in")]


def inline(md: str) -> str:
    s = html.escape(md.replace("→", "->"), quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`(.+?)`", r"<font face='Courier'>\1</font>", s)
    return re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", s)


def main():
    styles = getSampleStyleSheet()
    body = styles["BodyText"].clone("body", fontSize=10.5, leading=14.5, spaceAfter=7)
    story = [Paragraph("CreditCatch: write-up", styles["Title"]),
             Paragraph(f"GST purchase reconciliation agent on TrueForge. Code: {REPO}", body),
             Spacer(1, 4 * mm)]
    story += [Paragraph(inline(p), body) for p in section()]
    out = ROOT / "WRITEUP.pdf"
    SimpleDocTemplate(str(out), pagesize=A4, title="CreditCatch: write-up", author="CreditCatch",
                      leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm).build(story)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
