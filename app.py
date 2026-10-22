"""ManageMyPG — manage multiple PGs: rooms, beds, tenants and rent.

Run with:  streamlit run app.py
"""

from datetime import date
from urllib.parse import quote

import altair as alt
import pandas as pd
import streamlit as st

import auth
import db
import receipts

st.set_page_config(page_title="ManageMyPG", page_icon="🏠", layout="wide")
db.init_db()

st.markdown(
    """<style>
    [data-testid="stMetricValue"] { font-size: 1.6rem; }
    [data-testid="stMetricLabel"] p { font-size: 0.85rem; }
    /* Phones: keep metric rows two-across instead of one long stacked list */
    @media (max-width: 640px) {
        [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [data-testid="stMetric"]) {
            flex-wrap: wrap; gap: 0.75rem 1rem;
        }
        [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [data-testid="stMetric"]) > [data-testid="stColumn"] {
            flex: 1 1 calc(50% - 1rem) !important; min-width: calc(50% - 1rem) !important;
        }
        [data-testid="stMetricValue"] { font-size: 1.3rem; }
    }
    </style>""",
    unsafe_allow_html=True,
)

PG_TYPES = ["Co-living", "Boys", "Girls"]
ROOM_TYPES = ["Non-AC", "AC"]
PAY_MODES = ["UPI", "Cash", "Bank Transfer", "Card", "Cheque"]
EXPENSE_CATEGORIES = {
    "Electricity": "⚡", "Staff salary": "👷", "Maintenance & repairs": "🔧", "Water": "💧",
    "Internet": "📶", "Food & groceries": "🍚", "Housekeeping & supplies": "🧹",
    "Building rent / lease": "🏢", "Other": "📦",
}


# ================================================================ helpers

def inr(x):
    """Format a number as Indian rupees with lakh/crore grouping."""
    x = float(x or 0)
    neg, x = x < 0, abs(round(x))
    s = str(int(x))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-₹" if neg else "₹") + s


def month_label(m):
    return pd.Timestamp(m + "-01").strftime("%B %Y")


def this_month():
    return str(pd.Timestamp(date.today()).to_period("M"))


def last_n_months(n):
    today = pd.Timestamp(date.today()).to_period("M")
    return [str(today - i) for i in range(n - 1, -1, -1)]


def month_options(back=12, ahead=1):
    today = pd.Timestamp(date.today()).to_period("M")
    return [str(today + i) for i in range(ahead, -back - 1, -1)]


def flash(msg, icon="✅"):
    st.session_state["_flash"] = (msg, icon)


def show_flash():
    if "_flash" in st.session_state:
        msg, icon = st.session_state.pop("_flash")
        st.toast(msg, icon=icon)


def whatsapp_link(phone, text):
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if not digits:
        return None
    if len(digits) == 10:
        digits = "91" + digits
    return f"https://wa.me/{digits}?text={quote(text)}"


def goto(page, pg_id=...):
    """Switch page / PG on the next run (widget keys can't change after they render)."""
    st.session_state["_goto"] = (page, pg_id)
    st.rerun()


def bed_name(b, room_key="room_number"):
    """'Room 101 · Part B · Bed 3' for a bed dict (or a tenant dict with bed_label / bed_section)."""
    room = b.get(room_key)
    label = b.get("label") or b.get("bed_label")
    section = b.get("section") if "section" in b else b.get("bed_section")
    if not room:
        return "Not assigned"
    return " · ".join(p for p in [f"Room {room}", section, label] if p)


def rent_range(r):
    lo, hi = r.get("min_rent") or 0, r.get("max_rent") or 0
    return inr(lo) if lo == hi else f"{inr(lo)}–{inr(hi)}"


def receipt_pdf(pg, payment_ids=None, month=None):
    rows = db.receipt_data(uid(), pg["id"], payment_ids=payment_ids, month=month)
    return receipts.build_receipts(pg, st.session_state["user"]["name"], rows), rows


def uid():
    return st.session_state["user"]["id"]


def current_pg():
    pg_id = st.session_state.get("pg_id")
    return db.get_pg(uid(), pg_id) if pg_id else None


# ================================================================ auth screens

def auth_screen():
    st.markdown(
        "<h1 style='text-align:center;margin-bottom:0'>🏠 ManageMyPG</h1>"
        "<p style='text-align:center;color:gray'>Rooms, beds, tenants and rent — for all your PGs in one place.</p>",
        unsafe_allow_html=True,
    )
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        login_tab, signup_tab = st.tabs(["Log in", "Create account"])
        with login_tab:
            with st.form("login"):
                email = st.text_input("Email or username")
                password = st.text_input("Password", type="password")
                if st.form_submit_button("Log in", type="primary", width="stretch"):
                    user, err = auth.login(email, password)
                    if err:
                        st.error(err)
                    else:
                        st.session_state["user"] = user
                        st.rerun()
        with signup_tab:
            with st.form("signup"):
                name = st.text_input("Your name")
                email = st.text_input("Email", key="su_email")
                phone = st.text_input("Phone")
                pw = st.text_input("Password", type="password", help="At least 6 characters")
                pw2 = st.text_input("Confirm password", type="password")
                if st.form_submit_button("Create account", type="primary", width="stretch"):
                    user, err = auth.signup(name, email, phone, pw, pw2)
                    if err:
                        st.error(err)
                    else:
                        st.session_state["user"] = user
                        flash(f"Welcome, {user['name']}! Add your first PG to get started.")
                        st.rerun()


# ================================================================ PG form (shared by create / edit)

def pg_form(key, pg=None):
    pg = pg or {}
    with st.form(key, clear_on_submit=not pg):
        c1, c2 = st.columns(2)
        name = c1.text_input("PG name *", value=pg.get("name", ""), placeholder="e.g. Sai Residency")
        pg_type = c2.selectbox("Type", PG_TYPES, index=PG_TYPES.index(pg.get("pg_type", "Co-living")))
        address = st.text_area("Address", value=pg.get("address") or "", height=70)
        c3, c4, c5 = st.columns(3)
        city = c3.text_input("City", value=pg.get("city") or "Pune")
        contact = c4.text_input("Contact number", value=pg.get("contact") or "")
        due_day = c5.number_input("Rent due day of month", 1, 28, int(pg.get("rent_due_day", 5)))
        submitted = st.form_submit_button("Save PG" if pg else "Create PG", type="primary")
    if submitted:
        if not name.strip():
            st.error("PG name is required.")
            return None
        return dict(name=name, address=address, city=city, pg_type=pg_type, contact=contact,
                    rent_due_day=int(due_day))
    return None


# ================================================================ pages

def page_all_pgs():
    st.title("🏢 My PGs")
    month = str(pd.Timestamp(date.today()).to_period("M"))
    summary = db.portfolio_summary(uid(), month)

    if summary:
        beds = sum(s["beds"] for s in summary)
        occ = sum(s["occupied"] for s in summary)
        exp = sum(s["expected"] for s in summary)
        col = sum(s["collected"] for s in summary)
        spent = sum(s["expenses"] for s in summary)
        mon = f"{pd.Timestamp(month + '-01'):%b}"
        c = st.columns(4)
        c[0].metric("PGs", len(summary))
        c[1].metric("Total beds", beds)
        c[2].metric("Occupied beds", f"{occ}/{beds}", help=f"{(occ / beds * 100 if beds else 0):.0f}% occupancy")
        c[3].metric("Deposits held", inr(sum(s["deposits_held"] for s in summary)))
        c = st.columns(4)
        c[0].metric(f"Collected · {mon}", inr(col))
        c[1].metric(f"Pending · {mon}", inr(max(exp - col, 0)))
        c[2].metric(f"Expenses · {mon}", inr(spent))
        c[3].metric(f"Net profit · {mon}", inr(col - spent))
        st.divider()

        cols = st.columns(3)
        for i, s in enumerate(summary):
            with cols[i % 3].container(border=True):
                st.subheader(s["name"])
                st.caption(f"📍 {s['city'] or '—'} · {s['pg_type']} · {s['rooms']} rooms")
                vacant = s["beds"] - s["occupied"]
                st.progress(s["occupied"] / s["beds"] if s["beds"] else 0.0,
                            text=f"{s['occupied']}/{s['beds']} beds occupied · {vacant} vacant")
                st.markdown(f"💰 Collected **{inr(s['collected'])}** &nbsp;·&nbsp; "
                            f"⏳ Pending **{inr(max(s['expected'] - s['collected'], 0))}**  \n"
                            f"🧾 Expenses **{inr(s['expenses'])}** &nbsp;·&nbsp; "
                            f"📈 Net **{inr(s['collected'] - s['expenses'])}**")
                if st.button("Open →", key=f"open_{s['id']}", width="stretch"):
                    goto("📊 Dashboard", s["id"])
    else:
        st.info("You haven't added any PG yet. Create your first one below 👇")

    with st.expander("➕ Add a new PG", expanded=not summary):
        data = pg_form("new_pg")
        if data:
            new_id = db.create_pg(uid(), **data)
            flash(f"PG '{data['name']}' created. Now add rooms to it.")
            goto("🛏️ Rooms", new_id)


def page_dashboard(pg):
    st.title(f"📊 {pg['name']}")
    st.caption(f"📍 {pg['address'] or ''} {pg['city'] or ''} · {pg['pg_type']} · Rent due on day {pg['rent_due_day']}")

    rooms = db.list_rooms(uid(), pg["id"])
    month = str(pd.Timestamp(date.today()).to_period("M"))
    status = db.rent_status(uid(), pg["id"], month)

    beds = sum(r["capacity"] for r in rooms)
    occ = sum(r["occupied"] for r in rooms)
    due = sum(s["due"] for s in status)
    paid = sum(s["paid"] for s in status)
    spent = sum(e["amount"] for e in db.list_expenses(uid(), pg["id"], month))
    deps = db.deposits(uid(), pg["id"])
    to_refund = [d for d in deps if d["status"] == "Vacated" and d["deposit_status"] == "Held"]
    mon = f"{pd.Timestamp(month + '-01'):%b}"

    c = st.columns(5)
    c[0].metric("Rooms", len(rooms))
    c[1].metric("Beds", beds)
    c[2].metric("Occupied", occ)
    c[3].metric("Vacant beds", beds - occ)
    c[4].metric("Deposits held", inr(sum(d["deposit"] for d in deps if d["deposit_status"] == "Held")))
    c = st.columns(5)
    c[0].metric(f"Collected · {mon}", inr(paid))
    c[1].metric(f"Pending · {mon}", inr(max(due - paid, 0)))
    c[2].metric(f"Expenses · {mon}", inr(spent))
    c[3].metric(f"Net profit · {mon}", inr(paid - spent))
    c[4].metric("Deposits to refund", inr(sum(d["deposit"] for d in to_refund)),
                help=f"{len(to_refund)} vacated tenant(s) — settle in 👥 Tenants → Deposits")

    if not rooms:
        st.info("No rooms yet. Go to **🛏️ Rooms** to add them.")
        return

    left, right = st.columns(2)
    with left.container(border=True):
        st.subheader("🟢 Available beds")
        avail = [b for b in db.list_beds(uid(), pg["id"]) if not b["tenant_id"]]
        if avail:
            st.dataframe(
                pd.DataFrame([{
                    "Room": b["room_number"], "Section": b["section"] or "", "Bed": b["label"],
                    "Floor": b["floor"], "Type": b["room_type"], "Rent": b["rent"],
                } for b in avail]),
                hide_index=True, width="stretch",
                column_config={"Rent": st.column_config.NumberColumn(format="₹%d")},
            )
        else:
            st.success("House full! Every bed is occupied. 🎉")

    with right.container(border=True):
        st.subheader(f"🔴 Rent pending — {month_label(month)}")
        pending = [s for s in status if s["paid"] < s["due"]]
        if pending:
            st.dataframe(
                pd.DataFrame([{
                    "Tenant": s["name"], "Room": s["room_number"] or "—",
                    "Due": inr(s["due"]), "Paid": inr(s["paid"]), "Balance": inr(s["due"] - s["paid"]),
                } for s in pending]),
                hide_index=True, width="stretch",
            )
        else:
            st.success("Everyone has paid this month. 🎉")

    pnl = db.income_vs_expenses(uid(), pg["id"], last_n_months(6))
    if any(r["collected"] or r["expenses"] for r in pnl):
        with st.container(border=True):
            st.subheader("📈 Rent collected vs expenses — last 6 months")
            pnl_chart(pnl_frame(pnl))


def page_rooms(pg):
    st.title(f"🛏️ Rooms — {pg['name']}")
    rooms = db.list_rooms(uid(), pg["id"])

    view, add, manage = st.tabs(["Room board", "➕ Add rooms", "✏️ Edit / delete"])

    with view:
        if not rooms:
            st.info("No rooms yet. Use the **➕ Add rooms** tab.")
        else:
            f1, f2 = st.columns([1, 3])
            only_vacant = f1.toggle("Show only rooms with vacancy")
            floors = sorted({r["floor"] or "—" for r in rooms})
            floor_sel = f2.multiselect("Floor", floors, default=floors)
            shown = [r for r in rooms if (r["floor"] or "—") in floor_sel and (r["vacant"] > 0 or not only_vacant)]
            st.caption("🟥 occupied bed · 🟩 vacant bed")
            beds_by_room = {}
            for b in db.list_beds(uid(), pg["id"]):
                beds_by_room.setdefault(b["room_id"], []).append(b)
            cols = st.columns(3)
            for i, r in enumerate(shown):
                with cols[i % 3].container(border=True):
                    tag = "🟢 Available" if r["vacant"] else "🔴 Full"
                    st.markdown(f"**Room {r['room_number']}** &nbsp; {tag}")
                    st.caption(f"Floor {r['floor'] or '—'} · {r['room_type']} · {r['capacity']} bed(s) · {rent_range(r)}")
                    lines, last_section = [], None
                    for b in beds_by_room.get(r["id"], []):
                        if b["section"] and b["section"] != last_section:
                            lines.append(f"*{b['section']}*")
                        last_section = b["section"]
                        who = b["tenant_name"] or "vacant"
                        lines.append(f"{'🟥' if b['tenant_id'] else '🟩'} {b['label']} · {inr(b['rent'])} · {who}")
                    st.markdown("  \n".join(lines))

    with add:
        st.caption("Add one room, or a range of rooms with the same setup (e.g. 101–110). "
                   "Beds with different prices or a partitioned room? Add it here, then set each bed in ✏️ Edit.")
        with st.form("add_room", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            mode = c1.radio("Add", ["Single room", "Range of rooms"], horizontal=True)
            floor = c2.text_input("Floor", placeholder="e.g. 1 / Ground")
            room_type = c3.selectbox("Room type", ROOM_TYPES)
            c4, c5, c6 = st.columns(3)
            room_no = c4.text_input("Room number (single)", placeholder="e.g. 101")
            rng = c5.text_input("Range (numeric)", placeholder="e.g. 101-110")
            capacity = c6.number_input("Beds (sharing)", 1, 20, 2)
            rent = st.number_input("Rent per bed (₹/month)", 0, 1_000_000, 8000, step=500,
                                   help="Every bed starts at this price — change individual beds in ✏️ Edit")
            notes = st.text_input("Notes", placeholder="Attached washroom, balcony…")
            if st.form_submit_button("Add", type="primary"):
                numbers = []
                if mode == "Single room":
                    if room_no.strip():
                        numbers = [room_no.strip()]
                else:
                    try:
                        a, b = (int(x) for x in rng.replace(" ", "").split("-"))
                        numbers = [str(n) for n in range(a, b + 1)] if a <= b and b - a < 200 else []
                    except ValueError:
                        numbers = []
                if not numbers:
                    st.error("Enter a room number, or a valid range like 101-110.")
                else:
                    existing = {r["room_number"] for r in rooms}
                    added, skipped = 0, []
                    for n in numbers:
                        if n in existing:
                            skipped.append(n)
                            continue
                        db.create_room(uid(), pg["id"], n, floor, int(capacity), float(rent), room_type, notes)
                        added += 1
                    msg = f"Added {added} room(s)."
                    if skipped:
                        msg += f" Skipped existing: {', '.join(skipped)}"
                    flash(msg)
                    st.rerun()

    with manage:
        if not rooms:
            st.info("No rooms to edit.")
        else:
            room = st.selectbox(
                "Select room", rooms,
                format_func=lambda r: f"Room {r['room_number']} (Floor {r['floor'] or '—'}) — {r['occupied']}/{r['capacity']} occupied",
            )
            with st.form(f"edit_room_{room['id']}"):
                c1, c2, c3 = st.columns(3)
                rn = c1.text_input("Room number", room["room_number"])
                fl = c2.text_input("Floor", room["floor"] or "")
                rt = c3.selectbox("Type", ROOM_TYPES, index=ROOM_TYPES.index(room["room_type"]))
                nt = st.text_input("Notes", room["notes"] or "")
                if st.form_submit_button("Save room details", type="primary"):
                    try:
                        db.update_room(uid(), pg["id"], room["id"], rn, fl, rt, nt)
                        flash("Room updated.")
                        st.rerun()
                    except Exception:
                        st.error("Couldn't save — that room number may already exist.")

            with st.container(border=True):
                st.markdown("**🛏️ Beds & prices**")
                st.caption("Each bed can have its own rent. Partitioned room? Use *Section* to group beds — e.g. "
                           "two beds in 'Part A' and the single bed in 'Part B' at a higher price. "
                           "Add a bed with the ➕ row at the bottom; delete by selecting a row (only vacant beds).")
                beds = db.list_beds(uid(), pg["id"], room["id"])
                df = pd.DataFrame([{
                    "id": b["id"], "Section": b["section"] or "", "Bed": b["label"], "Rent": b["rent"],
                    "Occupied by": b["tenant_name"] or "",
                } for b in beds], columns=["id", "Section", "Bed", "Rent", "Occupied by"])
                edited = st.data_editor(
                    df, key=f"beds_{room['id']}", num_rows="dynamic", hide_index=True, width="stretch",
                    column_order=["Section", "Bed", "Rent", "Occupied by"],
                    column_config={
                        "Section": st.column_config.TextColumn(help="Optional, e.g. Part A / Part B"),
                        "Bed": st.column_config.TextColumn(required=True, default="Bed"),
                        "Rent": st.column_config.NumberColumn("Rent (₹/month)", min_value=0, step=500,
                                                              format="₹%d", required=True,
                                                              default=float(room["rent_per_bed"] or 0)),
                        "Occupied by": st.column_config.TextColumn(disabled=True),
                    },
                )
                if st.button("Save beds", type="primary", key=f"save_beds_{room['id']}"):
                    rows = [{
                        "id": int(r["id"]) if pd.notna(r["id"]) else None,
                        "label": r["Bed"], "section": r["Section"] if pd.notna(r["Section"]) else "",
                        "rent": float(r["Rent"]) if pd.notna(r["Rent"]) else 0,
                    } for _, r in edited.iterrows()]
                    try:
                        db.save_room_beds(uid(), pg["id"], room["id"], rows)
                        st.session_state.pop(f"beds_{room['id']}", None)
                        flash("Beds saved.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
                st.caption("Changing a bed's price affects new tenants only. To change what a current tenant pays, "
                           "edit their monthly rent in 👥 Tenants.")
            if st.button("🗑️ Delete this room", key=f"del_room_{room['id']}"):
                try:
                    db.delete_room(uid(), pg["id"], room["id"])
                    flash("Room deleted.", "🗑️")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


def tenant_fields(prefix, beds, t=None, current_bed_id=None):
    """Tenant form body. Returns (bed_id, fields)."""
    t = t or {}
    bed_choices = [None] + [b for b in beds if not b["tenant_id"] or b["id"] == current_bed_id]
    idx = next((i for i, b in enumerate(bed_choices) if b and b["id"] == current_bed_id), 0)
    c1, c2 = st.columns(2)
    name = c1.text_input("Full name *", t.get("name", ""), key=f"{prefix}_name")
    phone = c2.text_input("Phone *", t.get("phone") or "", key=f"{prefix}_phone")
    bed = st.selectbox(
        "Bed", bed_choices, index=idx, key=f"{prefix}_bed",
        format_func=lambda b: "— Not assigned —" if b is None else
        f"{bed_name(b)} · {b['room_type']} · {inr(b['rent'])}/month",
    )
    c3, c4, c5 = st.columns(3)
    default_rent = t.get("monthly_rent") if t else (bed["rent"] if bed else 0)
    rent = c3.number_input("Monthly rent (₹) *", 0, 1_000_000, int(default_rent or 0), step=500,
                           key=f"{prefix}_rent_{bed['id'] if bed else 0}", help="Defaults to the bed's price")
    deposit = c4.number_input("Security deposit (₹)", 0, 10_000_000, int(t.get("deposit") or 0), step=1000, key=f"{prefix}_dep")
    join = c5.date_input("Joining date", pd.to_datetime(t.get("join_date") or date.today()).date(), key=f"{prefix}_join",
                         format="DD/MM/YYYY")
    c6, c7, c8 = st.columns(3)
    email = c6.text_input("Email", t.get("email") or "", key=f"{prefix}_email")
    occupation = c7.text_input("Occupation / college", t.get("occupation") or "", key=f"{prefix}_occ")
    id_proof = c8.text_input("ID proof (Aadhaar last 4 / PAN etc.)", t.get("id_proof") or "", key=f"{prefix}_id")
    emergency = st.text_input("Emergency contact (name & phone)", t.get("emergency_contact") or "", key=f"{prefix}_em")
    notes = st.text_area("Notes", t.get("notes") or "", height=68, key=f"{prefix}_notes")
    return (bed["id"] if bed else None), dict(
        name=name, phone=phone, email=email, id_proof=id_proof, occupation=occupation,
        emergency_contact=emergency, join_date=join.isoformat(), monthly_rent=float(rent),
        deposit=float(deposit), notes=notes,
    )


def page_tenants(pg):
    st.title(f"👥 Tenants — {pg['name']}")
    beds = db.list_beds(uid(), pg["id"])
    active = db.list_tenants(uid(), pg["id"], "Active")
    past = db.list_tenants(uid(), pg["id"], "Vacated")

    pending_deposits = sum(1 for t in past if t["deposit"] > 0 and t["deposit_status"] == "Held")
    t_active, t_add, t_edit, t_past, t_dep = st.tabs(
        [f"Current ({len(active)})", "➕ Add tenant", "✏️ Edit / vacate", f"Past tenants ({len(past)})",
         "💼 Deposits" + (f" ({pending_deposits} to refund)" if pending_deposits else "")]
    )

    with t_active:
        if not active:
            st.info("No tenants yet. Use **➕ Add tenant**.")
        else:
            q = st.text_input("🔍 Search by name, phone or room", key="tenant_search").strip().lower()
            rows = [t for t in active if not q or q in t["name"].lower() or q in (t["phone"] or "")
                    or q in bed_name(t).lower()]
            df = pd.DataFrame([{
                "Name": t["name"], "Room / bed": bed_name(t), "Phone": t["phone"],
                "Rent": t["monthly_rent"], "Deposit": t["deposit"],
                "Joined": pd.to_datetime(t["join_date"]).strftime("%d %b %Y"),
                "Occupation": t["occupation"], "Emergency": t["emergency_contact"],
            } for t in rows])
            st.dataframe(df, hide_index=True, width="stretch", column_config={
                "Rent": st.column_config.NumberColumn(format="₹%d"),
                "Deposit": st.column_config.NumberColumn(format="₹%d"),
            })
            st.download_button("⬇️ Download CSV", df.to_csv(index=False), f"{pg['name']}_tenants.csv", "text/csv")

    with t_add:
        if not beds:
            st.warning("Add rooms first so you can assign tenants to them.")
        elif all(b["tenant_id"] for b in beds):
            st.warning("All beds are occupied. You can still add a tenant without a bed.")
        # Not wrapped in st.form so the rent default follows the chosen bed.
        bed_id, f = tenant_fields("add", beds)
        if st.button("Add tenant", type="primary"):
            if not f["name"].strip() or not f["phone"].strip():
                st.error("Name and phone are required.")
            else:
                try:
                    db.create_tenant(uid(), pg["id"], bed_id, **f)
                    for k in [k for k in st.session_state if k.startswith("add_")]:
                        del st.session_state[k]
                    flash(f"{f['name']} added.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    with t_edit:
        if not active:
            st.info("No current tenants.")
        else:
            t = st.selectbox("Select tenant", active,
                             format_func=lambda t: f"{t['name']} — {bed_name(t)} — {t['phone']}")
            with st.form(f"edit_tenant_{t['id']}"):
                bed_id, f = tenant_fields(f"edit{t['id']}", beds, t, current_bed_id=t["bed_id"])
                st.caption("Moving to another bed keeps their current rent — change it above if the new bed costs more or less.")
                if st.form_submit_button("Save changes", type="primary"):
                    try:
                        db.update_tenant(uid(), pg["id"], t["id"], bed_id, **f)
                        flash("Tenant updated.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

            with st.container(border=True):
                st.markdown("**🚪 Vacate tenant** — frees the bed and moves them to past tenants.")
                c1, c2 = st.columns([2, 1])
                vd = c1.date_input("Vacating date", date.today(), key=f"vd_{t['id']}", format="DD/MM/YYYY")
                c2.write("")
                if c2.button("Mark vacated", key=f"vac_{t['id']}"):
                    db.vacate_tenant(uid(), pg["id"], t["id"], vd.isoformat())
                    extra = " Settle their deposit in the 💼 Deposits tab." if t["deposit"] > 0 else ""
                    flash(f"{t['name']} marked as vacated.{extra}", "🚪")
                    st.rerun()

    with t_past:
        if not past:
            st.info("No past tenants.")
        else:
            st.dataframe(pd.DataFrame([{
                "Name": t["name"], "Phone": t["phone"],
                "Joined": pd.to_datetime(t["join_date"]).strftime("%d %b %Y"),
                "Vacated": pd.to_datetime(t["vacate_date"]).strftime("%d %b %Y") if t["vacate_date"] else "—",
                "Rent": inr(t["monthly_rent"]), "Deposit": inr(t["deposit"]),
                "Deposit status": "—" if not t["deposit"] else
                ("✅ Settled" if t["deposit_status"] == "Settled" else "⏳ To refund"),
            } for t in past]), hide_index=True, width="stretch")
            with st.expander("🗑️ Permanently delete a past tenant (also deletes their payment history)"):
                d = st.selectbox("Tenant", past, format_func=lambda t: f"{t['name']} — {t['phone']}", key="del_t")
                if st.button("Delete permanently", key="del_t_btn"):
                    db.delete_tenant(uid(), pg["id"], d["id"])
                    flash("Tenant deleted.", "🗑️")
                    st.rerun()

    with t_dep:
        deposits_tab(pg)


def deposits_tab(pg):
    deps = db.deposits(uid(), pg["id"])
    held = [d for d in deps if d["status"] == "Active" and d["deposit_status"] == "Held"]
    to_settle = [d for d in deps if d["status"] == "Vacated" and d["deposit_status"] == "Held"]
    settled = [d for d in deps if d["deposit_status"] == "Settled"]

    c = st.columns(4)
    c[0].metric("Held (current tenants)", inr(sum(d["deposit"] for d in held)), help=f"{len(held)} tenants")
    c[1].metric("To refund (vacated)", inr(sum(d["deposit"] for d in to_settle)), help=f"{len(to_settle)} tenants")
    c[2].metric("Refunded", inr(sum(d["deposit_refund"] for d in settled)))
    c[3].metric("Kept (rent + deductions)",
                inr(sum(d["deposit_rent_adjusted"] + d["deposit_deduction"] for d in settled)))

    with st.container(border=True):
        st.subheader("🔄 Settle a deposit")
        if not to_settle:
            st.info("No vacated tenants waiting for a deposit refund. Vacate a tenant from **✏️ Edit / vacate** first.")
        else:
            t = st.selectbox("Vacated tenant", to_settle, key="settle_t", format_func=lambda d:
                             f"{d['name']} — vacated {pd.to_datetime(d['vacate_date']).strftime('%d %b %Y')} — deposit {inr(d['deposit'])}")
            k = f"st{t['id']}"
            remaining = t["deposit"]
            adjustments = []
            unpaid = db.unpaid_rent_months(uid(), pg["id"], t["id"])
            if unpaid:
                st.markdown("**Unpaid rent** — recover it from the deposit (it will be recorded as rent paid):")
                st.caption("Pre-filled from payments recorded in this app. Set a month to 0 if they paid it outside the app.")
                # Pre-fill the most recent months first; older gaps are more often paid outside the app.
                defaults, left = {}, remaining
                for u in reversed(unpaid):
                    defaults[u["month"]] = int(min(u["balance"], max(left, 0)))
                    left -= defaults[u["month"]]
                cols = st.columns(len(unpaid))
                for col, u in zip(cols, unpaid):
                    amt = col.number_input(
                        f"{month_label(u['month'])} (owes {inr(u['balance'])})", 0, int(u["balance"]),
                        defaults[u["month"]], step=100, key=f"{k}_rent_{u['month']}")
                    adjustments.append((u["month"], float(amt)))
            else:
                st.caption("✅ No unpaid rent in their last 3 months.")
            c1, c2 = st.columns([1, 2])
            deduction = c1.number_input("Other deductions (₹)", 0, int(t["deposit"]), 0, step=100, key=f"{k}_ded")
            reason = c2.text_input("Reason", placeholder="Damage, cleaning, notice period, electricity share…", key=f"{k}_reason")
            refund = t["deposit"] - sum(a for _, a in adjustments) - deduction

            c3, c4, c5 = st.columns(3)
            c3.metric("Refund to tenant", inr(max(refund, 0)))
            refund_date = c4.date_input("Refund date", date.today(), key=f"{k}_date", format="DD/MM/YYYY")
            mode = c5.selectbox("Mode", PAY_MODES, key=f"{k}_mode")
            notes = st.text_input("Notes / transaction ID", key=f"{k}_notes")
            if refund < 0:
                st.error(f"Rent adjusted + deductions exceed the deposit by {inr(-refund)}.")
            elif st.button("Settle deposit", type="primary", key=f"{k}_go"):
                try:
                    db.settle_deposit(uid(), pg["id"], t["id"], adjustments, float(deduction), reason,
                                      float(refund), refund_date.isoformat(), mode, notes)
                    flash(f"Deposit settled for {t['name']}: {inr(refund)} refunded.", "💼")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    if settled:
        st.subheader("✅ Settled deposits")
        df = pd.DataFrame([{
            "Tenant": d["name"], "Phone": d["phone"],
            "Vacated": pd.to_datetime(d["vacate_date"]).strftime("%d %b %Y") if d["vacate_date"] else "—",
            "Deposit": d["deposit"], "Rent adjusted": d["deposit_rent_adjusted"],
            "Deductions": d["deposit_deduction"], "Reason": d["deposit_deduction_reason"],
            "Refunded": d["deposit_refund"],
            "Refund date": pd.to_datetime(d["deposit_refund_date"]).strftime("%d %b %Y") if d["deposit_refund_date"] else "—",
            "Mode": d["deposit_refund_mode"],
        } for d in settled])
        money = st.column_config.NumberColumn(format="₹%d")
        st.dataframe(df, hide_index=True, width="stretch", column_config={
            "Deposit": money, "Rent adjusted": money, "Deductions": money, "Refunded": money})
        st.download_button("⬇️ Download CSV", df.to_csv(index=False), f"{pg['name']}_deposits.csv", "text/csv")
        with st.expander("↩️ Undo a settlement"):
            st.caption("Moves it back to *To refund* and removes the rent payments that were adjusted from the deposit.")
            u = st.selectbox("Tenant", settled, key="undo_dep", format_func=lambda d: f"{d['name']} — refunded {inr(d['deposit_refund'])}")
            if st.button("Undo settlement", key="undo_dep_btn"):
                db.undo_deposit_settlement(uid(), pg["id"], u["id"])
                flash("Settlement undone.", "↩️")
                st.rerun()

    if held:
        with st.expander(f"Deposits held for current tenants ({len(held)})"):
            st.dataframe(pd.DataFrame([{
                "Tenant": d["name"], "Room": d["room_number"] or "—", "Deposit": inr(d["deposit"]),
                "Joined": pd.to_datetime(d["join_date"]).strftime("%d %b %Y"),
            } for d in held]), hide_index=True, width="stretch")


def pnl_frame(rows):
    df = pd.DataFrame(rows)
    df["Month"] = df["month"].map(lambda m: pd.Timestamp(m + "-01").strftime("%b %Y"))
    df = df.rename(columns={"collected": "Rent collected", "expenses": "Expenses"})
    df["Net profit"] = df["Rent collected"] - df["Expenses"]
    return df.set_index("Month")[["Rent collected", "Expenses", "Net profit"]]


def pnl_chart(df):
    """Grouped bars of rent collected vs expenses, months in calendar order."""
    long = df[["Rent collected", "Expenses"]].reset_index().melt("Month", var_name="Type", value_name="Amount")
    chart = alt.Chart(long).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("Month:N", sort=list(df.index), title=None, axis=alt.Axis(labelAngle=0)),
        xOffset="Type:N",
        y=alt.Y("Amount:Q", title="₹"),
        color=alt.Color("Type:N", scale=alt.Scale(domain=["Rent collected", "Expenses"], range=["#4F46E5", "#F97316"]),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["Month", "Type", alt.Tooltip("Amount:Q", format=",.0f")],
    ).properties(height=300)
    st.altair_chart(chart, width="stretch")


def page_expenses(pg):
    st.title(f"🧾 Expenses — {pg['name']}")
    months = month_options()
    month = st.selectbox("Month", months, index=months.index(this_month()), format_func=month_label, key="exp_month")

    expenses = db.list_expenses(uid(), pg["id"], month)
    collected = db.income_vs_expenses(uid(), pg["id"], [month])[0]["collected"]
    total = sum(e["amount"] for e in expenses)
    by_cat = {}
    for e in expenses:
        by_cat[e["category"]] = by_cat.get(e["category"], 0) + e["amount"]

    c = st.columns(4)
    c[0].metric("Rent collected", inr(collected))
    c[1].metric("Expenses", inr(total))
    c[2].metric("Net profit", inr(collected - total))
    top = max(by_cat, key=by_cat.get) if by_cat else None
    c[3].metric("Biggest expense", f"{EXPENSE_CATEGORIES.get(top, '')} {top}" if top else "—",
                help=inr(by_cat[top]) if top else None)

    t_list, t_add, t_pnl = st.tabs(["Expenses", "➕ Add expense", "📈 Profit & loss"])

    with t_list:
        if not expenses:
            st.info(f"No expenses recorded for {month_label(month)}. Use **➕ Add expense**.")
        else:
            left, right = st.columns([1, 2])
            with left.container(border=True):
                st.markdown("**By category**")
                for cat, amt in sorted(by_cat.items(), key=lambda x: -x[1]):
                    st.markdown(f"{EXPENSE_CATEGORIES.get(cat, '📦')} {cat}")
                    st.progress(amt / total, text=f"{inr(amt)} · {amt / total * 100:.0f}%")
            with right:
                df = pd.DataFrame([{
                    "Date": pd.to_datetime(e["expense_date"]).strftime("%d %b %Y"),
                    "Category": f"{EXPENSE_CATEGORIES.get(e['category'], '📦')} {e['category']}",
                    "Amount": e["amount"], "Paid to": e["paid_to"], "Mode": e["mode"], "Notes": e["notes"],
                } for e in expenses])
                st.dataframe(df, hide_index=True, width="stretch",
                             column_config={"Amount": st.column_config.NumberColumn(format="₹%d")})
                st.download_button("⬇️ Download CSV", df.to_csv(index=False),
                                   f"{pg['name']}_expenses_{month}.csv", "text/csv")
                with st.expander("Undo a wrong entry"):
                    e = st.selectbox("Expense", expenses, key="del_exp", format_func=lambda e:
                                     f"{e['expense_date']} · {e['category']} · {inr(e['amount'])} · {e['paid_to'] or ''}")
                    if st.button("🗑️ Delete expense", key="del_exp_btn"):
                        db.delete_expense(uid(), pg["id"], e["id"])
                        flash("Expense deleted.", "🗑️")
                        st.rerun()

    with t_add:
        with st.form(f"add_expense_{month}", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            cat = c1.selectbox("Category", list(EXPENSE_CATEGORIES),
                               format_func=lambda c: f"{EXPENSE_CATEGORIES[c]} {c}")
            amount = c2.number_input("Amount (₹)", 1, 10_000_000, 1000, step=100)
            exp_date = c3.date_input("Paid on", date.today(), format="DD/MM/YYYY")
            c4, c5, c6 = st.columns(3)
            for_month = c4.selectbox("Count it in month", months, index=months.index(month), format_func=month_label,
                                     help="e.g. September's electricity bill paid in October → September")
            paid_to = c5.text_input("Paid to", placeholder="MSEDCL, cook's name, plumber…")
            mode = c6.selectbox("Mode", PAY_MODES)
            notes = st.text_input("Notes", placeholder="Meter units, bill number, what was repaired…")
            if st.form_submit_button("Add expense", type="primary"):
                db.add_expense(uid(), pg["id"], cat, float(amount), for_month, exp_date.isoformat(), paid_to, mode, notes)
                flash(f"Added {inr(amount)} for {cat}.", "🧾")
                st.rerun()

        prev = str(pd.Period(month) - 1)
        prev_exp = db.list_expenses(uid(), pg["id"], prev)
        if prev_exp:
            with st.expander(f"🔁 Copy repeating expenses from {month_label(prev)} (salaries, internet…)"):
                pick = st.multiselect(
                    "Expenses to copy", prev_exp, key=f"copy_{month}",
                    default=[e for e in prev_exp if e["category"] in ("Staff salary", "Internet", "Building rent / lease")],
                    format_func=lambda e: f"{e['category']} · {inr(e['amount'])} · {e['paid_to'] or ''}")
                if st.button(f"Copy {len(pick)} into {month_label(month)}", disabled=not pick, key=f"copy_btn_{month}"):
                    d = date.today().isoformat() if month >= this_month() else f"{month}-01"
                    for e in pick:
                        db.add_expense(uid(), pg["id"], e["category"], e["amount"], month, d,
                                       e["paid_to"], e["mode"], e["notes"])
                    flash(f"Copied {len(pick)} expense(s).", "🔁")
                    st.rerun()

    with t_pnl:
        rows = db.income_vs_expenses(uid(), pg["id"], last_n_months(6))
        df = pnl_frame(rows)
        pnl_chart(df)
        money = st.column_config.NumberColumn(format="₹%d")
        st.dataframe(df.reset_index(), hide_index=True, width="stretch",
                     column_config={"Rent collected": money, "Expenses": money, "Net profit": money})
        st.caption("Rent collected includes unpaid rent recovered from deposits. Deposit refunds are not expenses — "
                   "the deposit was never your income.")


def page_rent(pg):
    st.title(f"💰 Rent — {pg['name']}")
    months = month_options()
    default = str(pd.Timestamp(date.today()).to_period("M"))
    month = st.selectbox("Month", months, index=months.index(default), format_func=month_label)

    status = db.rent_status(uid(), pg["id"], month)
    due = sum(s["due"] for s in status)
    paid = sum(s["paid"] for s in status)
    n_paid = sum(1 for s in status if s["paid"] >= s["due"])

    c = st.columns(4)
    c[0].metric("Expected", inr(due))
    c[1].metric("Collected", inr(paid))
    c[2].metric("Pending", inr(max(due - paid, 0)))
    c[3].metric("Tenants paid", f"{n_paid}/{len(status)}")
    if due:
        st.progress(min(paid / due, 1.0), text=f"{paid / due * 100:.0f}% collected")

    t_status, t_record, t_history = st.tabs(["Who paid?", "➕ Record payment", "🧾 Payments & receipts"])

    with t_status:
        if not status:
            st.info("No tenants were staying in this month.")
        else:
            flt = st.radio("Show", ["All", "Pending", "Paid"], horizontal=True)
            rows = []
            for s in status:
                bal = s["due"] - s["paid"]
                state = "✅ Paid" if bal <= 0 else ("🟡 Partial" if s["paid"] > 0 else "🔴 Due")
                if (flt == "Pending" and bal <= 0) or (flt == "Paid" and bal > 0):
                    continue
                msg = (f"Hi {s['name']}, this is a reminder from {pg['name']} that your rent of "
                       f"{inr(bal)} for {month_label(month)} is pending. Please pay at the earliest. Thank you!")
                rows.append({
                    "Tenant": s["name"], "Room": s["room_number"] or "—", "Status": state,
                    "Due": s["due"], "Paid": s["paid"], "Balance": max(bal, 0),
                    "Last paid": pd.to_datetime(s["last_paid_on"]).strftime("%d %b") if s["last_paid_on"] else "—",
                    "Remind": whatsapp_link(s["phone"], msg) if bal > 0 else None,
                })
            df = pd.DataFrame(rows)
            if df.empty:
                st.info("Nothing to show for this filter.")
            else:
                st.dataframe(df, hide_index=True, width="stretch", column_config={
                    "Due": st.column_config.NumberColumn(format="₹%d"),
                    "Paid": st.column_config.NumberColumn(format="₹%d"),
                    "Balance": st.column_config.NumberColumn(format="₹%d"),
                    "Remind": st.column_config.LinkColumn("Remind", display_text="💬 WhatsApp"),
                })
                st.download_button("⬇️ Download CSV", df.drop(columns="Remind").to_csv(index=False),
                                   f"{pg['name']}_rent_{month}.csv", "text/csv")

    with t_record:
        if not status:
            st.info("No tenants to record payments for in this month.")
        else:
            pending_first = sorted(status, key=lambda s: s["paid"] >= s["due"])
            s = st.selectbox(
                "Tenant", pending_first,
                format_func=lambda s: f"{s['name']} — Room {s['room_number'] or '—'} — balance {inr(max(s['due'] - s['paid'], 0))}",
            )
            with st.form(f"pay_{s['tenant_id']}_{month}", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                amount = c1.number_input("Amount (₹)", 1, 10_000_000, int(max(s["due"] - s["paid"], 0)) or 1, step=100)
                paid_on = c2.date_input("Paid on", date.today(), format="DD/MM/YYYY")
                mode = c3.selectbox("Mode", PAY_MODES)
                notes = st.text_input("Notes / transaction ID")
                if st.form_submit_button(f"Record payment for {month_label(month)}", type="primary"):
                    pid = db.add_payment(uid(), pg["id"], s["tenant_id"], month, float(amount), paid_on.isoformat(), mode, notes)
                    st.session_state["last_payment"] = (pg["id"], pid)
                    flash(f"Recorded {inr(amount)} from {s['name']}.", "💰")
                    st.rerun()

        last = st.session_state.get("last_payment")
        if last and last[0] == pg["id"]:
            pdf, rows = receipt_pdf(pg, payment_ids=[last[1]])
            if rows:
                p = rows[0]
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    c1.success(f"Payment of {inr(p['amount'])} from **{p['tenant_name']}** recorded "
                               f"({receipts.receipt_no(p)}).")
                    c2.download_button("📄 Download receipt", pdf, f"{receipts.receipt_no(p)}.pdf",
                                       "application/pdf", type="primary", width="stretch")

    with t_history:
        pays = db.list_payments(uid(), pg["id"], month=month)
        if not pays:
            st.info("No payments recorded for this month.")
        else:
            st.dataframe(pd.DataFrame([{
                "Receipt no": receipts.receipt_no(p),
                "Date": pd.to_datetime(p["paid_on"]).strftime("%d %b %Y"), "Tenant": p["tenant_name"],
                "Amount": p["amount"], "Mode": p["mode"], "Notes": p["notes"],
            } for p in pays]), hide_index=True, width="stretch",
                column_config={"Amount": st.column_config.NumberColumn(format="₹%d")})

            with st.container(border=True):
                st.markdown("**📄 Rent receipts (PDF)**")
                c1, c2 = st.columns([3, 1])
                p = c1.selectbox("Payment", pays, key=f"rcpt_{month}", label_visibility="collapsed",
                                 format_func=lambda p: f"{receipts.receipt_no(p)} · {p['tenant_name']} · "
                                                       f"{inr(p['amount'])} · {pd.to_datetime(p['paid_on']):%d %b}")
                pdf, _ = receipt_pdf(pg, payment_ids=[p["id"]])
                c2.download_button("Download receipt", pdf, f"{receipts.receipt_no(p)}.pdf", "application/pdf",
                                   type="primary", width="stretch", key=f"rcpt_btn_{p['id']}")
                all_pdf, _ = receipt_pdf(pg, month=month)
                st.download_button(f"⬇️ All {len(pays)} receipts for {month_label(month)} (one PDF, ready to print)",
                                   all_pdf, f"{pg['name']}_receipts_{month}.pdf", "application/pdf",
                                   key=f"rcpt_all_{month}")
            with st.expander("Undo a wrong entry"):
                p = st.selectbox("Payment", pays, format_func=lambda p:
                                 f"{p['paid_on']} · {p['tenant_name']} · {inr(p['amount'])} · {p['mode']}")
                if st.button("🗑️ Delete payment"):
                    db.delete_payment(uid(), pg["id"], p["id"])
                    flash("Payment deleted.", "🗑️")
                    st.rerun()


def page_settings(pg):
    st.title("⚙️ Settings")
    if pg:
        st.subheader(f"Edit PG — {pg['name']}")
        data = pg_form(f"edit_pg_{pg['id']}", pg)
        if data:
            db.update_pg(uid(), pg["id"], **data)
            flash("PG updated.")
            st.rerun()
        with st.expander("⚠️ Delete this PG"):
            st.warning("This permanently deletes the PG with all its rooms, tenants and payment records.")
            confirm = st.text_input(f"Type **{pg['name']}** to confirm")
            if st.button("Delete PG", type="primary", disabled=confirm != pg["name"]):
                db.delete_pg(uid(), pg["id"])
                flash("PG deleted.", "🗑️")
                goto("🏢 My PGs", None)
        st.divider()

    st.subheader("Account")
    u = st.session_state["user"]
    st.write(f"**{u['name']}** · {u['email']} · {u['phone'] or ''}")
    with st.form("change_pw", clear_on_submit=True):
        old = st.text_input("Current password", type="password")
        new = st.text_input("New password", type="password")
        new2 = st.text_input("Confirm new password", type="password")
        if st.form_submit_button("Change password"):
            fresh = db.get_user_by_email(u["email"])
            if not auth.verify_password(old, fresh["password_hash"]):
                st.error("Current password is wrong.")
            elif len(new) < 6 or new != new2:
                st.error("New password must be 6+ characters and match.")
            else:
                db.update_password(u["id"], auth.hash_password(new))
                st.success("Password changed.")


# ================================================================ main

def main():
    if "user" not in st.session_state:
        auth_screen()
        return

    show_flash()
    if "_goto" in st.session_state:
        page, pg_id = st.session_state.pop("_goto")
        st.session_state["nav"] = page
        if pg_id is not ...:
            st.session_state["pg_id"] = pg_id
    user = st.session_state["user"]
    pgs = db.list_pgs(user["id"])
    ids = [p["id"] for p in pgs]
    if st.session_state.get("pg_id") not in ids:
        st.session_state["pg_id"] = ids[0] if ids else None

    pg_pages = ["📊 Dashboard", "🛏️ Rooms", "👥 Tenants", "💰 Rent", "🧾 Expenses"]
    with st.sidebar:
        st.markdown("## 🏠 ManageMyPG")
        st.caption(f"Logged in as **{user['name']}**")
        if pgs:
            st.selectbox("Current PG", ids, key="pg_id",
                         format_func=lambda i: next(p["name"] for p in pgs if p["id"] == i))
        nav_options = ["🏢 My PGs"] + (pg_pages if pgs else []) + ["⚙️ Settings"]
        if st.session_state.get("nav") not in nav_options:
            st.session_state["nav"] = nav_options[0]
        st.radio("Menu", nav_options, key="nav", label_visibility="collapsed")
        st.divider()
        if st.button("Log out", width="stretch"):
            st.session_state.clear()
            st.rerun()

    pg = current_pg()
    page = st.session_state["nav"]
    if page == "🏢 My PGs":
        page_all_pgs()
    elif page == "📊 Dashboard":
        page_dashboard(pg)
    elif page == "🛏️ Rooms":
        page_rooms(pg)
    elif page == "👥 Tenants":
        page_tenants(pg)
    elif page == "💰 Rent":
        page_rent(pg)
    elif page == "🧾 Expenses":
        page_expenses(pg)
    else:
        page_settings(pg)


main()
