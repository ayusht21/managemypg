"""Rent receipt PDFs (A5 landscape, one receipt per page)."""

from datetime import date

from fpdf import FPDF

INDIGO = (79, 70, 229)
GREEN = (22, 163, 74)
ORANGE = (234, 88, 12)
GREY = (107, 114, 128)
DARK = (17, 24, 39)
LIGHT = (243, 244, 246)

ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
        "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two_digits(n):
    return ONES[n] if n < 20 else (TENS[n // 10] + (" " + ONES[n % 10] if n % 10 else ""))


def _three_digits(n):
    hundred, rest = divmod(n, 100)
    parts = []
    if hundred:
        parts.append(ONES[hundred] + " Hundred")
    if rest:
        parts.append(_two_digits(rest))
    return " ".join(parts)


def amount_in_words(amount):
    """Indian numbering: 1,25,000 -> 'Rupees One Lakh Twenty Five Thousand Only'."""
    n = int(round(amount))
    if n == 0:
        return "Rupees Zero Only"
    parts = []
    for name, size in [("Crore", 10_000_000), ("Lakh", 100_000), ("Thousand", 1000)]:
        q, n = divmod(n, size)
        if q:
            parts.append(f"{_three_digits(q) if q >= 100 else _two_digits(q)} {name}")
    if n:
        parts.append(_three_digits(n))
    return "Rupees " + " ".join(parts) + " Only"


def rs(x):
    """Rs. with Indian digit grouping."""
    n = int(round(abs(x or 0)))
    s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return ("-" if (x or 0) < 0 else "") + "Rs. " + s


def receipt_no(p):
    return f"RCPT-{p['month'].replace('-', '')}-{p['id']:05d}"


def _txt(s):
    """Built-in PDF fonts are Latin-1 only; replace anything else rather than crash."""
    return str(s or "").replace("₹", "Rs. ").replace("–", "-").replace("—", "-").replace("·", "-") \
        .encode("latin-1", "replace").decode("latin-1")


def _fmt_date(iso):
    return date.fromisoformat(iso[:10]).strftime("%d %b %Y")


def _month_label(m):
    return date.fromisoformat(m + "-01").strftime("%B %Y")


class _Receipt(FPDF):
    def text_at(self, x, y, w, txt, size=9, style="", color=DARK, align="L", h=5):
        self.set_xy(x, y)
        self.set_font("Helvetica", style, size)
        self.set_text_color(*color)
        self.cell(w, h, _txt(txt), align=align)


def _draw(pdf, pg, owner_name, p):
    pdf.add_page()
    W, M = pdf.w, 10
    inner = W - 2 * M

    # Header band
    pdf.set_fill_color(*INDIGO)
    pdf.rect(0, 0, W, 26, style="F")
    pdf.text_at(M, 5, inner * 0.62, pg["name"], 16, "B", (255, 255, 255), h=8)
    addr = ", ".join(x for x in [pg.get("address"), pg.get("city")] if x)
    contact = f"Contact: {pg['contact']}" if pg.get("contact") else ""
    pdf.text_at(M, 13.5, inner * 0.62, addr, 8, "", (224, 231, 255))
    pdf.text_at(M, 18, inner * 0.62, contact, 8, "", (224, 231, 255))
    pdf.text_at(M, 5, inner, "RENT RECEIPT", 13, "B", (255, 255, 255), "R", h=8)
    pdf.text_at(M, 13.5, inner, f"Receipt No: {receipt_no(p)}", 8, "", (224, 231, 255), "R")
    pdf.text_at(M, 18, inner, f"Date: {_fmt_date(p['paid_on'])}", 8, "", (224, 231, 255), "R")

    # Details table
    room = " - ".join(x for x in [f"Room {p['room_number']}" if p.get("room_number") else None,
                                  p.get("bed_section"), p.get("bed_label")] if x) or "-"
    mode = p["mode"] + (f"  ({p['notes']})" if p.get("notes") else "")
    rows = [
        ("Received from", p["tenant_name"] + (f"   |   {p['tenant_phone']}" if p.get("tenant_phone") else "")),
        ("Room / bed", room),
        ("Rent for the month of", _month_label(p["month"])),
        ("Payment mode", mode),
    ]
    y, label_w = 31, 42
    for i, (k, v) in enumerate(rows):
        if i % 2 == 0:
            pdf.set_fill_color(*LIGHT)
            pdf.rect(M, y, inner, 7.5, style="F")
        pdf.text_at(M + 3, y + 1.3, label_w, k, 9, "", GREY)
        pdf.text_at(M + 3 + label_w, y + 1.3, inner - label_w - 6, v, 9.5, "B")
        y += 7.5

    # Amount box
    y += 4
    pdf.set_draw_color(*INDIGO)
    pdf.set_line_width(0.5)
    pdf.rect(M, y, inner, 17)
    pdf.text_at(M + 4, y + 2.5, 60, "AMOUNT RECEIVED", 8, "B", INDIGO)
    pdf.text_at(M + 4, y + 8.5, inner - 70, amount_in_words(p["amount"]), 9, "I", DARK)
    pdf.text_at(M, y + 4.5, inner - 4, rs(p["amount"]), 20, "B", INDIGO, "R", h=9)
    y += 17

    # Month status
    y += 4
    due, paid = p["monthly_rent"] or 0, p["paid_to_date"] or 0
    balance = max(due - paid, 0)
    pdf.text_at(M, y, inner, f"Monthly rent: {rs(due)}     Paid for {_month_label(p['month'])} so far: {rs(paid)}"
                f"     Balance: {rs(balance)}", 8.5, "", GREY)
    stamp, color = ("PAID IN FULL", GREEN) if balance <= 0 else ("PART PAYMENT", ORANGE)
    pdf.set_draw_color(*color)
    pdf.set_line_width(0.6)
    sx, sy = M + 4, y + 10
    pdf.rect(sx, sy, 44, 10)
    pdf.text_at(sx, sy + 2.5, 44, stamp, 11, "B", color, "C")

    # Signature
    sig_x, sig_w = W - M - 62, 62
    pdf.set_draw_color(*GREY)
    pdf.set_line_width(0.2)
    pdf.line(sig_x, sy + 13, sig_x + sig_w, sy + 13)
    pdf.text_at(sig_x, sy + 14, sig_w, f"For {pg['name']}", 8.5, "B", DARK, "C")
    pdf.text_at(sig_x, sy + 18.5, sig_w, owner_name or "Authorised signatory", 8, "", GREY, "C")

    pdf.text_at(M, pdf.h - 9, inner, "This is a computer-generated receipt from ManageMyPG.", 7, "I", GREY, "C")


def build_receipts(pg, owner_name, payments):
    """PDF bytes with one page per payment."""
    pdf = _Receipt(orientation="L", unit="mm", format=(148, 210))  # A5
    pdf.set_auto_page_break(False)
    pdf.set_title(f"Rent receipts - {pg['name']}")
    pdf.set_author(owner_name or "")
    for p in payments:
        _draw(pdf, pg, owner_name, p)
    return bytes(pdf.output())
