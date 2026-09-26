"""Generate CreditCatch demo data.

    python data/generate.py                  # the fixed demo month in data/demo/
    python data/generate.py --seed 42        # a random month in state/scenario/
    python data/generate.py --seed 42 --out /tmp/x --key /tmp/x/answer_key.json

Writes, under the output folder:
  invoices/*.pdf               purchase invoices (and the odd non-invoice PDF)
  emails.json                  the emails that carry them
  portal/GSTR2B_082026.json    GSTR-2B for the buyer, in the GST portal's JSON layout
  vendor_master.csv            the buyer's vendor list (GSTIN, contact alias)
  company.json                 the buyer
and an answer key with the problems planted in the data.

Without --seed you get the fixed month the tests and docs describe. With
--seed you get a different buyer, vendors, amounts, invoice layouts and
problems for every seed, so nothing is baked in. Every GSTIN, PAN, company
and amount is synthetic.
"""

import argparse
import csv
import json
import random
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "gst-reconcile" / "scripts"))
from gstin import STATES, make  # noqa: E402
from reconcile import _norm_num, _similar  # noqa: E402

PERIOD = "082026"
MONTH = "August 2026"


# ------------------------------------------------------------------ helpers

def money(x: float) -> str:
    return f"{x:,.2f}"


def split_tax(taxable: float, rate: float, interstate: bool) -> dict:
    tax = round(taxable * rate / 100, 2)
    if interstate:
        return {"igst": tax, "cgst": 0.0, "sgst": 0.0}
    half = round(tax / 2, 2)
    return {"igst": 0.0, "cgst": half, "sgst": half}


def rate_groups(lines) -> dict:
    """{rate: taxable} over an invoice's lines. A line is (desc, hsn, qty, unit, price, rate)."""
    out = {}
    for _, _, qty, _, price, rate in lines:
        out[rate] = round(out.get(rate, 0) + qty * price, 2)
    return out


def taxable_of(lines) -> float:
    return round(sum(q * p for _, _, q, _, p, _ in lines), 2)


def typo(gstin: str) -> str:
    # Swap two adjacent PAN digits; the checksum no longer matches.
    chars = list(gstin)
    chars[7], chars[8] = chars[8], chars[7]
    if chars[7] == chars[8]:
        chars[9] = "0" if chars[9] != "0" else "1"
    return "".join(chars)


def safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", s).strip("-")


def fmt_date(d: str, style: str) -> str:
    dt = datetime.strptime(d, "%Y-%m-%d")
    return {"dmy": dt.strftime("%d/%m/%Y"), "dmon": dt.strftime("%d-%b-%Y"),
            "tally": f"{dt.day}-{dt.strftime('%b-%y')}"}[style]


# ------------------------------------------------------ the fixed demo month

def classic() -> dict:
    company = {"name": "Namma Bakes Pvt Ltd", "gstin": make("29", "AAHCN4821K"),
               "address": "14, 3rd Cross, Jayanagar 4th Block, Bengaluru 560011", "state_code": "29"}
    vendors = {}
    for slug, name, st, pan, addr in [
        ("shreepack", "Shree Packaging Pvt Ltd", "29", "AAKCS5512M", "Plot 22, Peenya Industrial Area, Bengaluru 560058"),
        ("kaveriflour", "Kaveri Flour Mills", "29", "AAJFK7730Q", "KIADB Hebbal, Mysuru 570016"),
        ("deccandairy", "Deccan Dairy Products Pvt Ltd", "29", "AAGCD2204R", "88, Hosur Road, Bengaluru 560068"),
        ("malnadspice", "Malnad Spices & Co", "29", "AAQFM6619L", "IG Road, Chikkamagaluru 577101"),
        ("punebakeq", "Pune Bakery Equipment Pvt Ltd", "27", "AAFCP3348H", "Bhosari MIDC, Pune 411026"),
        ("blrlogistics", "Bengaluru Logistics Services", "29", "AAVFB9027D", "Yeshwanthpur, Bengaluru 560022"),
        ("sunrisesugar", "Sunrise Sugar Traders", "29", "AAMFS4410C", "VV Nagar, Mandya 571401"),
        ("cleanco", "CleanCo Facility Services Pvt Ltd", "29", "AADCC8156E", "HSR Layout, Bengaluru 560102"),
    ]:
        vendors[slug] = {"slug": slug, "name": name, "state_code": st, "gstin": make(st, pan), "address": addr}

    def inv(slug, inum, d, rate, lines, **kw):
        return {"vendor": slug, "inum": inum, "date": d, "layout": "classic",
                "lines": [(a, b, c, e, f, rate) for a, b, c, e, f in lines],
                "defect": kw.get("defect"), "tweak": kw.get("tweak", {})}

    invoices = [
        inv("shreepack", "SP/26-27/0412", "2026-08-04", 18, [("5-ply corrugated cake boxes 10x10", "4819", 2000, "pcs", 25)]),
        inv("shreepack", "SP/26-27/0419", "2026-08-18", 18, [("5-ply corrugated cake boxes 10x10", "4819", 10000, "pcs", 25)],
            tweak={"taxable": 205000}),
        inv("shreepack", "SP/26-27/0431", "2026-08-28", 18, [("Printed bread bags 1 kg", "3923", 1500, "pcs", 25)]),
        inv("kaveriflour", "KFM-118", "2026-08-06", 5, [("Maida, 50 kg bag", "1101", 40, "bags", 1850)],
            tweak={"inum": "KFM/2026-27/118"}),
        inv("kaveriflour", "KFM-131", "2026-08-22", 5, [("Maida, 50 kg bag", "1101", 30, "bags", 1850)]),
        inv("deccandairy", "DDP/0871", "2026-08-09", 5, [("Unsalted white butter", "0405", 400, "kg", 480)]),
        inv("deccandairy", "DDP/0902", "2026-08-23", 5, [("Unsalted white butter", "0405", 350, "kg", 480)]),
        inv("deccandairy", "DDP/0934", "2026-08-30", 5, [("Unsalted white butter", "0405", 200, "kg", 480)]),
        inv("malnadspice", "MS/0823", "2026-08-12", 5, [("Cardamom and cinnamon blend", "0910", 300, "kg", 400)],
            tweak={"missing": True}),
        inv("malnadspice", "MS/0839", "2026-08-26", 5, [("Cardamom and cinnamon blend", "0910", 150, "kg", 400)]),
        inv("punebakeq", "PBE/26/0057", "2026-08-14", 18, [("Two-deck electric baking oven", "8417", 1, "unit", 420000)],
            defect="cgst_sgst_on_interstate"),
        inv("blrlogistics", "BLS/2608/112", "2026-08-08", 18, [("Local delivery services, 1-15 Aug", "9968", 1, "lot", 38000)]),
        inv("blrlogistics", "BLS/2608/131", "2026-08-29", 18, [("Local delivery services, 16-31 Aug", "9968", 1, "lot", 41500)]),
        inv("sunrisesugar", "SST/761", "2026-08-11", 5, [("Refined sugar, 50 kg bag", "1701", 90, "bags", 2100)]),
        inv("cleanco", "CFS/AUG/044", "2026-08-31", 18, [("Kitchen deep cleaning, August", "9985", 1, "month", 85000)],
            defect="gstin_typo"),
    ]
    only_in_2b = [inv("sunrisesugar", "SST/774", "2026-08-25", 5, [("Refined sugar, 50 kg bag", "1701", 50, "bags", 2100)])]

    emails = []
    for i in invoices:
        v = vendors[i["vendor"]]
        fname = f"{i['vendor']}_{safe(i['inum'])}.pdf"
        i["filename"] = fname
        sent = datetime.strptime(i["date"], "%Y-%m-%d") + timedelta(days=1, hours=10, minutes=len(i["inum"]) * 3)
        emails.append({
            "from_name": v["name"], "from_alias": i["vendor"],
            "subject": f"Invoice {i['inum']} from {v['name']}",
            "body": f"Dear Accounts Team,\n\nPlease find attached our invoice {i['inum']} dated "
                    f"{datetime.strptime(i['date'], '%Y-%m-%d').strftime('%d %b %Y')}.\n\nRegards,\n{v['name']}",
            "date": sent.strftime("%Y-%m-%dT%H:%M:%S+05:30"), "attachments": [fname]})
        if i["inum"] == "DDP/0902":
            emails.append({
                "from_name": "Ravi (Store Manager)", "from_alias": "store",
                "subject": f"Fwd: Invoice {i['inum']} from {v['name']}",
                "body": "Forwarding this one again in case accounts missed it.\n\n-- Ravi",
                "date": "2026-09-02T09:40:00+05:30", "attachments": [fname], "duplicate_of": i["inum"]})
    return {"seed": None, "company": company, "vendors": vendors, "extra_vendors": [],
            "invoices": invoices, "only_in_2b": only_in_2b, "emails": emails, "documents": []}


# ------------------------------------------------------------- random months

BUYERS = [
    {"name": "Namma Bakes Pvt Ltd", "pan": "AAHCN4821K", "state": "29", "city": "Bengaluru", "industry": "bakery",
     "address": "14, 3rd Cross, Jayanagar 4th Block, Bengaluru 560011"},
    {"name": "Tiruppur Threads Apparel Pvt Ltd", "pan": "AAECT5190P", "state": "33", "city": "Tiruppur", "industry": "garments",
     "address": "42, Kumar Nagar, Tiruppur 641603"},
    {"name": "Charminar Brew Cafe LLP", "pan": "AAOFC7734R", "state": "36", "city": "Hyderabad", "industry": "cafe",
     "address": "Road No. 10, Banjara Hills, Hyderabad 500034"},
    {"name": "Sahyadri Print Works Pvt Ltd", "pan": "AAKCS2087N", "state": "27", "city": "Pune", "industry": "print",
     "address": "S. No. 41, Bhosari, Pune 411026"},
]

# slug, name, state, PAN, address, items [(description, HSN/SAC, unit, price low, price high, GST rate)]
RAW_VENDORS = {
    "bakery": [
        ("kaveriflour", "Kaveri Flour Mills", "29", "AAJFK7730Q", "KIADB Hebbal, Mysuru 570016",
         [("Maida, 50 kg bag", "1101", "bags", 1700, 1950, 5), ("Whole wheat atta, 50 kg bag", "1101", "bags", 1550, 1800, 5)]),
        ("deccandairy", "Deccan Dairy Products Pvt Ltd", "29", "AAGCD2204R", "88, Hosur Road, Bengaluru 560068",
         [("Unsalted white butter", "0405", "kg", 440, 520, 5)]),
        ("sunrisesugar", "Sunrise Sugar Traders", "29", "AAMFS4410C", "VV Nagar, Mandya 571401",
         [("Refined sugar, 50 kg bag", "1701", "bags", 2000, 2250, 5)]),
        ("malnadspice", "Malnad Spices & Co", "29", "AAQFM6619L", "IG Road, Chikkamagaluru 577101",
         [("Cardamom and cinnamon blend", "0910", "kg", 380, 450, 5)]),
        ("punebakeq", "Pune Bakery Equipment Pvt Ltd", "27", "AAFCP3348H", "Bhosari MIDC, Pune 411026",
         [("Planetary mixer 20 L", "8438", "unit", 85000, 120000, 18), ("Oven heating element", "8516", "pcs", 4000, 6500, 18)]),
    ],
    "garments": [
        ("cbeyarn", "Coimbatore Cotton Yarns Pvt Ltd", "33", "AAFCC6621L", "Avinashi Road, Coimbatore 641018",
         [("Combed cotton yarn 30s", "5205", "kg", 260, 310, 5)]),
        ("suratsynth", "Surat Synthetic Fabrics", "24", "AAPFS8812D", "Ring Road, Surat 395002",
         [("Polyester knit fabric", "6006", "m", 95, 140, 5)]),
        ("erodedye", "Erode Dyeing Works", "33", "AAMFE4471K", "Perundurai SIPCOT, Erode 638052",
         [("Fabric dyeing job work", "9988", "kg", 55, 80, 5)]),
        ("ludhianapack", "Ludhiana Poly Packers", "03", "AALFL3390H", "Industrial Area B, Ludhiana 141003",
         [("Printed LDPE garment polybags", "3923", "kg", 180, 240, 18)]),
    ],
    "cafe": [
        ("chikcoffee", "Chikmagalur Coffee Estates", "29", "AABFC5528G", "Kadur Road, Chikkamagaluru 577101",
         [("Arabica roasted beans", "0901", "kg", 850, 1150, 5)]),
        ("hydcheese", "Hyderabad Dairy Fresh Pvt Ltd", "36", "AADCH6630T", "Uppal, Hyderabad 500039",
         [("Mozzarella cheese block", "0406", "kg", 420, 520, 5)]),
        ("sunrisesugar", "Sunrise Sugar Traders", "29", "AAMFS4410C", "VV Nagar, Mandya 571401",
         [("Refined sugar, 50 kg bag", "1701", "bags", 2000, 2250, 5)]),
        ("mumbaicoffeemc", "Mumbai Coffee Machines Pvt Ltd", "27", "AAECM4402J", "Andheri East, Mumbai 400093",
         [("Espresso machine service and descaling", "9987", "visit", 3500, 6000, 18)]),
        ("hydplastics", "Deccan Food Packaging", "36", "AAKFD2291M", "Kattedan, Hyderabad 500077",
         [("Food-grade takeaway containers", "3923", "pcs", 6, 11, 18)]),
    ],
    "print": [
        ("ahmedabadink", "Ahmedabad Inks & Coatings", "24", "AAHFA5561C", "Vatva GIDC, Ahmedabad 382445",
         [("Offset printing ink, process cyan", "3215", "kg", 520, 700, 18), ("Offset printing ink, black", "3215", "kg", 380, 480, 18)]),
        ("puneadhesive", "Pune Adhesives Pvt Ltd", "27", "AAGCP7780E", "Chakan MIDC, Pune 410501",
         [("Hot-melt binding glue", "3506", "kg", 210, 290, 18)]),
        ("lamifilm", "Chennai Lamination Films", "33", "AAQFC3190H", "Ambattur Industrial Estate, Chennai 600058",
         [("BOPP thermal lamination film", "3920", "roll", 2400, 3600, 18)]),
        ("heidelservice", "Precision Press Services", "29", "AAJFP8841K", "Peenya 2nd Stage, Bengaluru 560058",
         [("Offset press maintenance visit", "9987", "visit", 9000, 16000, 18)]),
    ],
}

# Services a business buys locally; the vendor is in the buyer's own state.
LOCAL_SERVICES = [
    ("facility", "{city} Facility Services Pvt Ltd", "C", "9985", "Housekeeping and deep cleaning, {month}", 25000, 90000),
    ("security", "{city} Security Services", "F", "9985", "Security guard services, {month}", 40000, 80000),
    ("ca", "Iyer Rao & Co, Chartered Accountants", "F", "9982", "Accounting and GST compliance fee, {month}", 15000, 35000),
    ("courier", "{city} Express Couriers", "F", "9968", "Courier and local delivery, {month}", 8000, 45000),
    ("fibernet", "{city} Fibernet Pvt Ltd", "C", "9984", "Leased line internet, {month}", 3000, 9000),
]
ELSEWHERE = [
    ("cloudbooks", "CloudBooks Software Pvt Ltd", "29", "AAHCC4410B", "Koramangala, Bengaluru 560034",
     [("Accounting software subscription, annual", "9973", "licence", 18000, 42000, 18)]),
    ("swiftlog", "Swift Logistics India Pvt Ltd", "27", "AAMCS9031Q", "Bhiwandi, Thane 421302",
     [("Line-haul freight forwarding services", "9967", "lot", 22000, 60000, 18)]),
]

NUMBER_STYLES = ["{P}/{FY}/{n:04d}", "{P}-{n}", "{P}/{n:04d}", "INV-{n:05d}", "{P}/AUG/{n:03d}", "{n}", "2608/{n:03d}"]
FILE_STYLES = ["{slug}_{inum}.pdf", "Invoice_{inum}.pdf", "TaxInvoice-{inum}.pdf", "invoice.pdf", "scan_{r}.pdf",
               "{P}_Aug26_{inum}.pdf"]
LAYOUTS = ["classic", "modern", "tally"]


def _pan(rng, name: str, kind: str) -> str:
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    first = next((ch for ch in name.upper() if ch.isalpha()), "X")
    return "AA" + rng.choice(letters) + kind + first + f"{rng.randint(1000, 9999)}" + rng.choice(letters)


def _initials(name: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z]+", name) if w.lower() not in ("pvt", "ltd", "and", "co", "llp", "india")]
    return "".join(w[0] for w in words[:3]).upper() or "INV"


def _variant(rng, inum: str):
    """A differently formatted invoice number a supplier might report for the same invoice."""
    m = re.match(r"^(.*?)(\d+)$", inum)
    options = []
    if m:
        head, digits = m.groups()
        options.append(f"{head}{int(digits)}")                  # leading zeros dropped
        options.append(f"{head}2026-27/{digits}" if head else f"26-27/{digits}")
        if head:
            options.append(digits)                                # prefix dropped
    rng.shuffle(options)
    for o in options:
        if _norm_num(o) != _norm_num(inum) and _similar(o, inum) >= 0.6:
            return o
    return None


def random_month(seed: int) -> dict:
    rng = random.Random(seed)
    b = rng.choice(BUYERS)
    company = {"name": b["name"], "gstin": make(b["state"], b["pan"]), "address": b["address"], "state_code": b["state"]}

    pool = []
    for slug, name, st, pan, addr, items in RAW_VENDORS[b["industry"]]:
        pool.append({"slug": slug, "name": name, "state_code": st, "pan": pan, "address": addr, "items": items})
    for slug, tmpl, kind, sac, desc, lo, hi in rng.sample(LOCAL_SERVICES, rng.randint(2, 4)):
        name = tmpl.format(city=b["city"])
        pool.append({"slug": slug, "name": name, "state_code": b["state"], "pan": _pan(rng, name, kind),
                     "address": f"{rng.randint(2, 180)}, Main Road, {b['city']}",
                     "items": [(desc.format(month=MONTH), sac, "month", lo, hi, 18)]})
    for slug, name, st, pan, addr, items in rng.sample(ELSEWHERE, rng.randint(0, 2)):
        pool.append({"slug": slug, "name": name, "state_code": st, "pan": pan, "address": addr, "items": items})

    vendors, active = {}, []
    for v in pool:
        v["gstin"] = make(v["state_code"], v["pan"])
        v["layout"] = rng.choice(LAYOUTS)
        v["style"] = rng.choice(NUMBER_STYLES)
        v["P"] = _initials(v["name"])
        v["n"] = rng.randint(20, 900)
        vendors[v["slug"]] = {k: v[k] for k in ("slug", "name", "state_code", "gstin", "address")}
        active.append(v)
    # At least one vendor sends Tally-style invoices, which the stock extractor can't read.
    if not any(v["layout"] == "tally" for v in active):
        rng.choice(active)["layout"] = "tally"
    # One vendor on the master is idle this month; it may still show up in GSTR-2B.
    idle = active.pop(rng.randrange(len(active))) if len(active) > 6 else None

    invoices = []
    for v in active:
        count = 1 if v["items"][0][2] == "month" else rng.randint(1, 3)
        days = sorted(rng.sample(range(1, 31), count))
        for day in days:
            v["n"] += rng.randint(1, 9)
            inum = v["style"].format(P=v["P"], FY="26-27", n=v["n"])
            lines = []
            for desc, hsn, unit, lo, hi, rate in rng.sample(v["items"], rng.randint(1, len(v["items"]))):
                price = rng.randint(lo, hi) if hi < 1000 else rng.randrange(lo, hi, 100)
                if unit in ("month", "visit", "lot", "licence"):
                    qty = 1
                elif price >= 50000:
                    qty = rng.randint(1, 2)
                else:
                    qty = max(1, round(rng.uniform(25000, 250000) / price))
                lines.append((desc, hsn, qty, unit, price, rate))
            invoices.append({"vendor": v["slug"], "inum": inum, "date": f"2026-08-{day:02d}", "layout": v["layout"],
                             "lines": lines, "defect": None, "tweak": {}})
    rng.shuffle(invoices)

    # Plant problems, at most one per invoice.
    free = list(invoices)

    def pick(pred=lambda i: True):
        cands = [i for i in free if pred(i)]
        if not cands:
            return None
        i = rng.choice(cands)
        free.remove(i)
        return i

    single_rate = lambda i: len(rate_groups(i["lines"])) == 1  # noqa: E731
    plan = ["missing", "value", "fuzzy", "gstin_typo", "wrong_head", "wrong_buyer", "itc_na"]
    weights = {"missing": 0.9, "value": 0.8, "fuzzy": 0.8, "gstin_typo": 0.5, "wrong_head": 0.6,
               "wrong_buyer": 0.4, "itc_na": 0.35}
    chosen = [p for p in plan if rng.random() < weights[p]]
    while len(chosen) < 3:
        extra = rng.choice([p for p in plan if p not in chosen])
        chosen.append(extra)
    for p in chosen:
        if p == "missing":
            i = pick()
            if i:
                i["tweak"] = {"missing": True}
        elif p == "value":
            i = pick(single_rate)
            if i:
                t = taxable_of(i["lines"])
                cut = rng.choice([0.9, 0.8, 0.5]) if t > 20000 else 0.5
                i["tweak"] = {"taxable": round(t * cut, 2)}
        elif p == "fuzzy":
            i = pick(lambda i: _variant(random.Random(0), i["inum"]) is not None)
            if i:
                i["tweak"] = {"inum": _variant(rng, i["inum"])}
        elif p == "gstin_typo":
            i = pick()
            if i:
                i["defect"] = "gstin_typo"
        elif p == "wrong_head":
            i = pick(lambda i: vendors[i["vendor"]]["state_code"] != company["state_code"])
            if i:
                i["defect"] = "cgst_sgst_on_interstate"
        elif p == "wrong_buyer":
            i = pick()
            if i:
                other = rng.choice([s for s in ("27", "29", "33", "36", "24") if s != company["state_code"]])
                i["defect"] = "wrong_buyer_gstin"
                i["buyer_gstin"] = make(other, b["pan"])
        elif p == "itc_na":
            i = pick()
            if i:
                i["tweak"] = {"itcavl": "N", "rsn": "C"}
        if i and (i["tweak"].get("inum") is None and "inum" in i["tweak"]):
            i["tweak"] = {}

    # An invoice the supplier reported but the business never received.
    only_in_2b = []
    if rng.random() < 0.7:
        src = idle or rng.choice(active)
        if idle:
            src["n"] += 1
        desc, hsn, unit, lo, hi, rate = src["items"][0]
        price = rng.randint(lo, hi) if hi < 1000 else rng.randrange(lo, hi, 100)
        qty = 1 if unit in ("month", "visit", "lot", "licence") else max(1, round(rng.uniform(20000, 120000) / price))
        src["n"] += 50
        only_in_2b.append({"vendor": src["slug"], "inum": src["style"].format(P=src["P"], FY="26-27", n=src["n"]),
                           "date": f"2026-08-{rng.randint(1, 30):02d}", "layout": src["layout"],
                           "lines": [(desc, hsn, qty, unit, price, rate)], "defect": None, "tweak": {}})

    # Emails: some vendors send two invoices in one email; one gets forwarded twice.
    emails, by_vendor, used = [], {}, set()
    for i in invoices:
        by_vendor.setdefault(i["vendor"], []).append(i)
    for slug, invs in by_vendor.items():
        v = vendors[slug]
        vv = next(x for x in active if x["slug"] == slug)
        invs.sort(key=lambda i: i["date"])
        groups = [invs] if len(invs) > 1 and rng.random() < 0.3 else [[i] for i in invs]
        for g in groups:
            names = []
            for i in g:
                fname = rng.choice(FILE_STYLES).format(slug=slug, inum=safe(i["inum"]), P=vv["P"], r=rng.randint(1000, 9999))
                if fname in used:  # files live in one folder, so names must be unique
                    fname = f"{slug}_{safe(i['inum'])}.pdf"
                i["filename"] = fname
                used.add(fname)
                names.append(fname)
            nums = ", ".join(i["inum"] for i in g)
            sent = datetime.strptime(g[-1]["date"], "%Y-%m-%d") + timedelta(days=rng.randint(0, 2), hours=rng.randint(9, 19),
                                                                            minutes=rng.randint(0, 59))
            subject = rng.choice([f"Invoice {nums}", f"Tax invoice {nums} - {v['name']}", f"{v['name']}: bill for {MONTH}",
                                  f"Invoice copy {nums}", f"{v['name']} invoice attached"])
            body = rng.choice([
                f"Dear Sir/Madam,\n\nPlease find attached our tax invoice {nums}. Kindly process the payment as per terms.\n\nThanks & regards,\nAccounts, {v['name']}",
                f"Hi,\n\nAttaching the invoice for supplies made in {MONTH}.\n\nRegards,\n{v['name']}",
                f"Dear Accounts Team,\n\nInvoice {nums} attached. Please acknowledge receipt.\n\n{v['name']}",
            ])
            emails.append({"from_name": v["name"], "from_alias": slug, "subject": subject, "body": body,
                           "date": sent.strftime("%Y-%m-%dT%H:%M:%S+05:30"), "attachments": names})
    dup = rng.choice([i for i in invoices if not i["tweak"].get("missing")])
    if rng.random() < 0.75:
        emails.append({"from_name": "Store Manager", "from_alias": "store",
                       "subject": f"Fwd: {dup['inum']}", "body": "Forwarding in case accounts missed this one.",
                       "date": f"2026-09-0{rng.randint(1, 5)}T10:{rng.randint(10, 59)}:00+05:30",
                       "attachments": [dup["filename"]], "duplicate_of": dup["inum"]})

    # Non-invoice PDFs that land in the same inbox.
    documents = []
    kinds = rng.sample(["price_list", "statement"], rng.randint(0, 2))
    for kind in kinds:
        slug = rng.choice(list(by_vendor))
        v = vendors[slug]
        fname = "PriceList_Sep2026.pdf" if kind == "price_list" else f"Statement_of_Account_{slug}.pdf"
        documents.append({"kind": kind, "vendor": slug, "filename": fname, "invoices": by_vendor[slug]})
        emails.append({"from_name": v["name"], "from_alias": slug,
                       "subject": "Revised price list from September" if kind == "price_list" else f"Statement of account - {MONTH}",
                       "body": "Please find attached for your reference.\n\nRegards,\n" + v["name"],
                       "date": f"2026-09-0{rng.randint(1, 5)}T11:{rng.randint(10, 59)}:00+05:30", "attachments": [fname]})

    extra = [vendors[idle["slug"]]] if idle else []
    if idle:
        del vendors[idle["slug"]]
    return {"seed": seed, "company": company, "vendors": vendors, "extra_vendors": extra,
            "invoices": invoices, "only_in_2b": only_in_2b, "emails": emails, "documents": documents}


# ------------------------------------------------------------------ figures

def printed(sc: dict, inv: dict) -> dict:
    """What the invoice PDF shows: GSTINs, place of supply, per-rate taxes and total."""
    company, v = sc["company"], (sc["vendors"].get(inv["vendor"]) or next(
        x for x in sc["extra_vendors"] if x["slug"] == inv["vendor"]))
    buyer_gstin = inv.get("buyer_gstin") or company["gstin"]
    pos = buyer_gstin[:2]
    interstate = v["state_code"] != pos and inv.get("defect") != "cgst_sgst_on_interstate"
    rows = []
    for rate, taxable in sorted(rate_groups(inv["lines"]).items()):
        rows.append({"rate": rate, "taxable": taxable, **split_tax(taxable, rate, interstate)})
    tax = round(sum(r["igst"] + r["cgst"] + r["sgst"] for r in rows), 2)
    taxable = taxable_of(inv["lines"])
    return {"vendor": v, "supplier_gstin": typo(v["gstin"]) if inv.get("defect") == "gstin_typo" else v["gstin"],
            "buyer_gstin": buyer_gstin, "pos": pos, "rows": rows, "taxable": taxable, "tax": tax,
            "total": round(taxable + tax, 2)}


def gstr2b_rows(sc: dict, inv: dict):
    """The invoice as the supplier reported it, or None if it isn't in the buyer's GSTR-2B."""
    tw = inv["tweak"]
    if tw.get("missing") or inv.get("defect") == "wrong_buyer_gstin":
        return None
    company = sc["company"]
    v = sc["vendors"].get(inv["vendor"]) or next(x for x in sc["extra_vendors"] if x["slug"] == inv["vendor"])
    interstate = v["state_code"] != company["state_code"]
    groups = rate_groups(inv["lines"])
    if "taxable" in tw:
        (rate,) = groups
        groups = {rate: tw["taxable"]}
    items = []
    for n, (rate, taxable) in enumerate(sorted(groups.items()), 1):
        items.append({"num": n, "rt": rate, "txval": taxable, **split_tax(taxable, rate, interstate), "cess": 0})
    val = round(sum(i["txval"] + i["igst"] + i["cgst"] + i["sgst"] for i in items), 2)
    return v, {"inum": tw.get("inum", inv["inum"]),
               "dt": datetime.strptime(inv["date"], "%Y-%m-%d").strftime("%d-%m-%Y"),
               "val": val, "typ": "R", "pos": company["state_code"], "rev": "N",
               "itcavl": tw.get("itcavl", "Y"), "rsn": tw.get("rsn", ""), "diffprcnt": 1, "srctyp": "",
               "items": items}


# ---------------------------------------------------------------- rendering

def _footer(c, v, y):
    c.setFont("Helvetica", 8)
    c.drawString(40, y, "Payment terms: 30 days. This is a computer generated invoice.")
    c.drawString(40, y - 11, f"For {v['name']} - Authorised Signatory")


def draw_classic(path, sc, inv, p):
    v, company = p["vendor"], sc["company"]
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    c.setTitle(f"Tax Invoice {inv['inum']}")
    w, h = A4
    y = h - 50
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y, "TAX INVOICE")
    c.setFont("Helvetica", 9)
    c.drawRightString(w - 40, y, "Original for Recipient")
    y -= 28
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, v["name"])
    c.setFont("Helvetica", 9)
    y -= 14
    c.drawString(40, y, v["address"])
    y -= 13
    c.drawString(40, y, f"GSTIN: {p['supplier_gstin']}")
    y -= 13
    c.drawString(40, y, f"State: {STATES[v['state_code']]} ({v['state_code']})")
    c.drawString(360, h - 78, f"Invoice No: {inv['inum']}")
    c.drawString(360, h - 91, f"Invoice Date: {fmt_date(inv['date'], 'dmy')}")
    c.drawString(360, h - 104, "Reverse Charge: No")
    y -= 30
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "Bill To")
    c.setFont("Helvetica", 9)
    for text in (company["name"], company["address"], f"GSTIN: {p['buyer_gstin']}",
                 f"Place of Supply: {STATES[p['pos']]} ({p['pos']})"):
        y -= 13
        c.drawString(40, y, text)
    y -= 30
    cols = [40, 250, 310, 370, 440]
    c.setFont("Helvetica-Bold", 9)
    for x, t in zip(cols, ["Description", "HSN/SAC", "Qty", "Rate (INR)", "Taxable Value (INR)"]):
        c.drawString(x, y, t)
    c.line(40, y - 4, w - 40, y - 4)
    c.setFont("Helvetica", 9)
    for desc, hsn, qty, unit, price, _ in inv["lines"]:
        y -= 16
        c.drawString(cols[0], y, desc[:40])
        c.drawString(cols[1], y, hsn)
        c.drawString(cols[2], y, f"{qty} {unit}")
        c.drawString(cols[3], y, money(price))
        c.drawString(cols[4], y, money(qty * price))
    c.line(40, y - 6, w - 40, y - 6)
    y -= 24
    rows = [("Taxable Value", p["taxable"])]
    for r in p["rows"]:
        if r["igst"]:
            rows.append((f"IGST @ {r['rate']:g}%", r["igst"]))
        else:
            rows.append((f"CGST @ {r['rate'] / 2:g}%", r["cgst"]))
            rows.append((f"SGST @ {r['rate'] / 2:g}%", r["sgst"]))
    rows.append(("Invoice Total", p["total"]))
    for label, amt in rows:
        c.setFont("Helvetica-Bold" if label == "Invoice Total" else "Helvetica", 9)
        c.drawString(330, y, label)
        c.drawRightString(w - 40, y, f"INR {money(amt)}")
        y -= 14
    _footer(c, v, y - 20)
    c.showPage()
    c.save()


def draw_modern(path, sc, inv, p):
    v, company = p["vendor"], sc["company"]
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    c.setTitle(f"Invoice {inv['inum']}")
    w, h = A4
    c.setFillColorRGB(0.12, 0.25, 0.45)
    c.rect(0, h - 90, w, 90, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(36, h - 45, v["name"])
    c.setFont("Helvetica", 9)
    c.drawString(36, h - 62, v["address"])
    c.drawString(36, h - 75, f"GSTIN/UIN: {p['supplier_gstin']}   |   State Code: {v['state_code']}")
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(w - 36, h - 45, "TAX INVOICE")
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 9)
    y = h - 120
    c.drawString(36, y, f"Bill No.: {inv['inum']}")
    c.drawString(230, y, f"Bill Date: {fmt_date(inv['date'], 'dmon')}")
    c.drawString(420, y, "Due: 30 days")
    y -= 26
    c.setFont("Helvetica-Bold", 9)
    c.drawString(36, y, "Billed To")
    c.setFont("Helvetica", 9)
    for text in (company["name"], company["address"], f"GSTIN/UIN: {p['buyer_gstin']}",
                 f"Place of Supply: {p['pos']}-{STATES[p['pos']]}"):
        y -= 13
        c.drawString(36, y, text)
    y -= 28
    cols = [36, 60, 280, 330, 390, 460, 520]
    c.setFont("Helvetica-Bold", 8)
    for x, t in zip(cols, ["#", "Item", "HSN", "Qty", "Rate", "Amount", "GST"]):
        c.drawString(x, y, t)
    c.line(36, y - 4, w - 36, y - 4)
    c.setFont("Helvetica", 8)
    for n, (desc, hsn, qty, unit, price, rate) in enumerate(inv["lines"], 1):
        y -= 15
        for x, t in zip(cols, [str(n), desc[:38], hsn, f"{qty} {unit}", money(price), money(qty * price), f"{rate:g}%"]):
            c.drawString(x, y, t)
    c.line(36, y - 6, w - 36, y - 6)
    y -= 26
    rows = [("Sub Total", p["taxable"])]
    for r in p["rows"]:
        if r["igst"]:
            rows.append((f"IGST {r['rate']:g}%", r["igst"]))
        else:
            rows.append((f"CGST {r['rate'] / 2:g}%", r["cgst"]))
            rows.append((f"SGST {r['rate'] / 2:g}%", r["sgst"]))
    rows.append(("Grand Total", p["total"]))
    for label, amt in rows:
        c.setFont("Helvetica-Bold" if label == "Grand Total" else "Helvetica", 9)
        c.drawString(360, y, f"{label}:")
        c.drawRightString(w - 36, y, f"Rs. {money(amt)}")
        y -= 14
    _footer(c, v, y - 24)
    c.showPage()
    c.save()


def draw_tally(path, sc, inv, p):
    """Laid out like a Tally print: labels and values sit in separate grid cells."""
    v, company = p["vendor"], sc["company"]
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    c.setTitle("Tax Invoice")
    w, h = A4
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(w / 2, h - 40, "Tax Invoice")
    c.rect(30, h - 330, w - 60, 280)
    c.line(300, h - 50, 300, h - 200)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(36, h - 66, v["name"])
    c.setFont("Helvetica", 8)
    c.drawString(36, h - 78, v["address"])
    c.drawString(36, h - 90, f"GSTIN/UIN: {p['supplier_gstin']}")
    c.drawString(36, h - 102, f"State Name : {STATES[v['state_code']]}, Code : {v['state_code']}")
    c.line(30, h - 112, 300, h - 112)
    c.drawString(36, h - 124, "Buyer (Bill to)")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(36, h - 136, company["name"])
    c.setFont("Helvetica", 8)
    c.drawString(36, h - 148, company["address"])
    c.drawString(36, h - 160, f"GSTIN/UIN     : {p['buyer_gstin']}")
    c.drawString(36, h - 172, f"State Name    : {STATES[p['pos']]}, Code : {p['pos']}")
    c.drawString(36, h - 184, f"Place of Supply : {STATES[p['pos']]}")
    # Right-hand grid: all labels first, then all values, as Tally's PDF export does.
    labels = [("Invoice No.", 306, h - 62), ("Dated", 440, h - 62), ("Delivery Note", 306, h - 92),
              ("Mode/Terms of Payment", 440, h - 92), ("Buyer's Order No.", 306, h - 122), ("Dated", 440, h - 122)]
    for t, x, yy in labels:
        c.drawString(x, yy, t)
    c.setFont("Helvetica-Bold", 8)
    for t, x, yy in [(inv["inum"], 306, h - 74), (fmt_date(inv["date"], "tally"), 440, h - 74),
                     ("30 Days", 440, h - 104)]:
        c.drawString(x, yy, t)
    c.setFont("Helvetica", 8)
    y = h - 214
    cols = [36, 56, 250, 305, 370, 430, 480]
    for x, t in zip(cols, ["Sl", "Description of Goods", "HSN/SAC", "Quantity", "Rate", "per", "Amount"]):
        c.drawString(x, y, t)
    c.line(30, y - 4, w - 30, y - 4)
    for n, (desc, hsn, qty, unit, price, rate) in enumerate(inv["lines"], 1):
        y -= 13
        for x, t in zip(cols[:6], [str(n), desc[:36], hsn, f"{qty} {unit}", money(price), unit]):
            c.drawString(x, y, t)
        c.drawRightString(w - 36, y, money(qty * price))
    for r in p["rows"]:
        heads = [("IGST", r["igst"])] if r["igst"] else [("CGST", r["cgst"]), ("SGST", r["sgst"])]
        for head, amt in heads:
            y -= 13
            c.drawRightString(300, y, f"{head} @ {r['rate'] if head == 'IGST' else r['rate'] / 2:g}")
            c.drawRightString(w - 36, y, money(amt))
    y -= 16
    c.setFont("Helvetica-Bold", 8)
    c.drawString(250, y, "Total")
    c.drawRightString(w - 36, y, money(p["total"]))
    c.setFont("Helvetica", 8)
    y = h - 350
    c.drawString(36, y, "Amount Chargeable (in words)")
    c.drawString(36, y - 12, f"INR {money(p['total'])} only")
    y -= 40
    igst = any(r["igst"] for r in p["rows"])
    head = ["HSN/SAC", "Taxable Value", "Integrated Tax Rate", "Amount"] if igst else \
        ["HSN/SAC", "Taxable Value", "Central Tax Rate", "Amount", "State Tax Rate", "Amount"]
    xs = [36, 130, 230, 320, 390, 470]
    for x, t in zip(xs, head + ["Total Tax Amount"]):
        c.drawString(x if t != "Total Tax Amount" else 470 if igst else 520, y, t if t != "Total Tax Amount" else "Total Tax")
    for r in p["rows"]:
        y -= 12
        hsns = ",".join(sorted({l[1] for l in inv["lines"] if l[5] == r["rate"]}))
        if igst:
            vals = [hsns, money(r["taxable"]), f"{r['rate']:g}%", money(r["igst"])]
            tot = r["igst"]
        else:
            vals = [hsns, money(r["taxable"]), f"{r['rate'] / 2:g}%", money(r["cgst"]), f"{r['rate'] / 2:g}%", money(r["sgst"])]
            tot = r["cgst"] + r["sgst"]
        for x, t in zip(xs, vals):
            c.drawString(x, y, t)
        c.drawString(470 if igst else 520, y, money(tot))
    y -= 30
    c.drawString(36, y, "Company's PAN : " + p["supplier_gstin"][2:12])
    c.drawRightString(w - 36, y, f"for {v['name']}")
    c.drawRightString(w - 36, y - 30, "Authorised Signatory")
    c.drawCentredString(w / 2, 30, "This is a Computer Generated Invoice")
    c.showPage()
    c.save()


def draw_document(path, sc, doc):
    v = sc["vendors"][doc["vendor"]]
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    w, h = A4
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, h - 50, v["name"])
    c.setFont("Helvetica", 9)
    c.drawString(40, h - 64, v["address"])
    c.drawString(40, h - 77, f"GSTIN: {v['gstin']}")
    y = h - 110
    c.setFont("Helvetica-Bold", 12)
    if doc["kind"] == "price_list":
        c.drawString(40, y, "PRICE LIST - effective 1 September 2026")
        c.setFont("Helvetica", 9)
        for inv in doc["invoices"][:1]:
            for desc, hsn, qty, unit, price, rate in inv["lines"]:
                y -= 16
                c.drawString(40, y, f"{desc}   HSN {hsn}   INR {money(round(price * 1.04))} per {unit}   GST extra @ {rate:g}%")
        y -= 24
        c.drawString(40, y, "Prices are ex-works and subject to change without notice.")
    else:
        c.drawString(40, y, f"STATEMENT OF ACCOUNT - {MONTH}")
        c.setFont("Helvetica", 9)
        y -= 14
        c.drawString(40, y, f"Customer: {sc['company']['name']}")
        y -= 20
        bal = 0
        for inv in doc["invoices"]:
            p = printed(sc, inv)
            bal += p["total"]
            y -= 14
            c.drawString(40, y, f"{fmt_date(inv['date'], 'dmy')}   Sales   Ref {inv['inum']}   Debit {money(p['total'])}")
        y -= 20
        c.drawString(40, y, f"Closing balance due: {money(bal)}")
    c.showPage()
    c.save()


DRAW = {"classic": draw_classic, "modern": draw_modern, "tally": draw_tally}


def write(sc: dict, out: Path, key_path: Path) -> dict:
    (out / "invoices").mkdir(parents=True, exist_ok=True)
    (out / "portal").mkdir(parents=True, exist_ok=True)
    for old in (out / "invoices").glob("*.pdf"):
        old.unlink()

    books = []
    for inv in sc["invoices"]:
        p = printed(sc, inv)
        DRAW[inv["layout"]](out / "invoices" / inv["filename"], sc, inv, p)
        books.append((inv, p))
    for doc in sc["documents"]:
        draw_document(out / "invoices" / doc["filename"], sc, doc)

    emails = sorted(sc["emails"], key=lambda e: e["date"])
    for n, e in enumerate(emails, 1):
        e["id"] = f"demo-{n:03d}"
    (out / "emails.json").write_text(json.dumps(
        [{k: v for k, v in e.items() if k != "duplicate_of"} for e in emails], indent=2) + "\n")

    by_ctin = {}
    reported = {}
    for inv in sc["invoices"] + sc["only_in_2b"]:
        got = gstr2b_rows(sc, inv)
        if not got:
            continue
        v, row = got
        reported[inv["inum"]] = row
        entry = by_ctin.setdefault(v["gstin"], {"ctin": v["gstin"], "trdnm": v["name"].upper(),
                                                 "supfildt": "11-09-2026", "supprd": PERIOD, "inv": []})
        entry["inv"].append(row)
    gstr2b = {"data": {"gstin": sc["company"]["gstin"], "rtnprd": PERIOD, "version": "1.0", "gendt": "14-09-2026",
                       "docdata": {"b2b": list(by_ctin.values())}}}
    (out / "portal" / f"GSTR2B_{PERIOD}.json").write_text(json.dumps(gstr2b, indent=2) + "\n")

    with open(out / "vendor_master.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["gstin", "name", "state_code", "contact_alias", "address"])
        for v in list(sc["vendors"].values()) + sc["extra_vendors"]:
            wr.writerow([v["gstin"], v["name"], v["state_code"], v["slug"], v["address"]])
    (out / "company.json").write_text(json.dumps(sc["company"], indent=2) + "\n")

    # The answer key comes from what was planted, not from running the reconciler.
    def tax2b(row):
        return round(sum(i["igst"] + i["cgst"] + i["sgst"] for i in row["items"]), 2)

    findings, at_risk, clean, claims = {}, {}, 0.0, 0.0
    for inv, p in books:
        tw, d = inv["tweak"], inv.get("defect")
        cat = None
        if d == "gstin_typo":
            cat, risk = "invalid_gstin_on_invoice", p["tax"]
        elif d == "wrong_buyer_gstin":
            cat, risk = "billed_to_other_gstin", p["tax"]
        elif tw.get("missing"):
            cat, risk = "missing_in_2b", p["tax"]
        elif d == "cgst_sgst_on_interstate":
            cat, risk = "wrong_tax_head", p["tax"]
        elif tw.get("itcavl") == "N":
            cat, risk = "itc_not_available_in_2b", p["tax"]
        elif "taxable" in tw:
            cat, risk = "value_mismatch", round(p["tax"] - tax2b(reported[inv["inum"]]), 2)
            claims += tax2b(reported[inv["inum"]])
        elif "inum" in tw:
            findings.setdefault("number_format_needs_confirmation", []).append([inv["inum"], tw["inum"]])
            claims += tax2b(reported[inv["inum"]])
            continue
        else:
            clean += p["tax"]
            claims += p["tax"]
            continue
        findings.setdefault(cat, []).append(inv["inum"])
        at_risk[inv["inum"]] = risk
    for inv in sc["only_in_2b"]:
        findings.setdefault("in_2b_not_in_books", []).append(inv["inum"])
    for e in emails:
        if e.get("duplicate_of"):
            findings.setdefault("duplicate_in_books", []).append(e["duplicate_of"])

    key = {
        "seed": sc["seed"],
        "company_gstin": sc["company"]["gstin"],
        "period": PERIOD,
        "invoices_in_books": len(sc["invoices"]),
        "emails": len(emails),
        "pdfs": sum(len(e["attachments"]) for e in emails),
        "non_invoice_documents": [d["filename"] for d in sc["documents"]],
        "layouts": {inv["filename"]: inv["layout"] for inv in sc["invoices"]},
        "findings": findings,
        "itc_at_risk_by_invoice": at_risk,
        "itc_at_risk_total": round(sum(at_risk.values()), 2),
        "itc_claimable_clean": round(clean, 2),
        "itc_to_claim_after_confirmations": round(claims, 2),
        "itc_unclaimed_in_2b_only": round(sum(tax2b(reported[i["inum"]]) for i in sc["only_in_2b"]), 2),
    }
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(json.dumps(key, indent=2) + "\n")
    return key


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, help="generate a random month from this seed")
    ap.add_argument("--out", type=Path, help="output folder (default: data/demo, or state/scenario with --seed)")
    ap.add_argument("--key", type=Path, help="answer key path (default: tests/answer_key.json, or <out>/answer_key.json)")
    args = ap.parse_args(argv)
    if args.seed is None:
        sc = classic()
        out = args.out or ROOT / "data" / "demo"
        key_path = args.key or ROOT / "tests" / "answer_key.json"
    else:
        sc = random_month(args.seed)
        out = args.out or ROOT / "state" / "scenario"
        key_path = args.key or out / "answer_key.json"
    key = write(sc, out, key_path)
    print(f"{sc['company']['name']}: {key['invoices_in_books']} invoices from {len(sc['vendors'])} vendors, "
          f"{key['emails']} emails, {sum(len(v) for v in key['findings'].values())} problems planted, "
          f"ITC at risk INR {money(key['itc_at_risk_total'])}. Written to {out}")
    return key


if __name__ == "__main__":
    main()
