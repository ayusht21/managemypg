"""Create a demo owner with two PGs, rooms, tenants and payments.

    python seed_demo.py
    login: demo123 / demo123
"""

import random
from datetime import date

import auth
import db

EMAIL, PASSWORD = "demo123", "demo123"
NAMES = ["Rahul Sharma", "Priya Patil", "Amit Joshi", "Sneha Kulkarni", "Rohan Deshmukh", "Neha Gupta",
         "Vikas Yadav", "Pooja Shinde", "Karan Mehta", "Anjali Pawar", "Siddharth Rao", "Kavya Nair",
         "Aditya Jadhav", "Riya Bhosale", "Manish Verma", "Shruti Kale", "Yash More", "Tanvi Gokhale"]


def main():
    random.seed(7)
    db.init_db()
    existing = db.get_user_by_email(EMAIL)
    if existing:
        add_expenses(existing["id"])
        add_partitioned_room(existing["id"])
        print("Demo user already exists; demo expenses and partitioned room are in place.")
        return
    uid = db.create_user("Demo Owner", EMAIL, "9800000000", auth.hash_password(PASSWORD))
    this_month = date.today().strftime("%Y-%m")
    last_month = f"{date.today().year - (date.today().month == 1)}-{(date.today().month - 2) % 12 + 1:02d}"
    names = iter(NAMES)

    for pg_name, city, pg_type, rooms in [
        ("Sai Residency", "Pune", "Boys", [("101", "1", 2, 8000, "AC"), ("102", "1", 3, 6500, "Non-AC"),
                                           ("201", "2", 2, 8500, "AC"), ("202", "2", 1, 12000, "AC")]),
        ("Shree Ganesh PG", "Pune", "Girls", [("G1", "Ground", 3, 7000, "Non-AC"), ("F1", "1", 2, 9000, "AC"),
                                              ("F2", "1", 2, 9000, "AC")]),
    ]:
        pg = db.create_pg(uid, pg_name, "Near Hinjewadi Phase 1", city, pg_type, "9800000000", 5)
        for r in rooms:
            db.create_room(uid, pg, r[0], r[1], r[2], r[3], r[4], "")
        for room in db.list_rooms(uid, pg):
            beds = db.list_beds(uid, pg, room["id"])
            for bed in beds[:random.randint(max(len(beds) - 1, 0), len(beds))]:
                db.create_tenant(uid, pg, bed["id"], name=next(names), phone=f"98{random.randint(10**7, 10**8 - 1)}",
                                 email="", id_proof="", occupation=random.choice(["Infosys", "TCS", "MIT student", "Wipro"]),
                                 emergency_contact="", join_date="2026-06-01", monthly_rent=bed["rent"],
                                 deposit=bed["rent"], notes="")
        for t in db.list_tenants(uid, pg, "Active"):
            db.add_payment(uid, pg, t["id"], last_month, t["monthly_rent"], f"{last_month}-05", "UPI", "")
            roll = random.random()
            if roll < 0.6:
                db.add_payment(uid, pg, t["id"], this_month, t["monthly_rent"], date.today().isoformat(), "UPI", "")
            elif roll < 0.8:
                db.add_payment(uid, pg, t["id"], this_month, t["monthly_rent"] / 2, date.today().isoformat(), "Cash", "")
    add_expenses(uid)
    add_partitioned_room(uid)
    print(f"Demo data created. Log in with {EMAIL} / {PASSWORD}")


def add_partitioned_room(uid):
    """Room 301 in the first PG: one room split by a partition — 2 beds on one side, a pricier single on the other."""
    pg = db.list_pgs(uid)[0]["id"]
    if any(r["room_number"] == "301" for r in db.list_rooms(uid, pg)):
        return
    room = db.create_room(uid, pg, "301", "3", 3, 7000, "Non-AC", "Partitioned room")
    ids = [b["id"] for b in db.list_beds(uid, pg, room)]
    db.save_room_beds(uid, pg, room, [
        {"id": ids[0], "section": "Part A (2 beds)", "label": "Bed 1", "rent": 7000},
        {"id": ids[1], "section": "Part A (2 beds)", "label": "Bed 2", "rent": 7000},
        {"id": ids[2], "section": "Part B (single)", "label": "Bed 3", "rent": 10500},
    ])
    for bed_id, name, rent in [(ids[0], "Omkar Kulkarni", 7000), (ids[2], "Harsh Agarwal", 10500)]:
        db.create_tenant(uid, pg, bed_id, name=name, phone=f"97{random.randint(10**7, 10**8 - 1)}", email="",
                         id_proof="", occupation="Persistent Systems", emergency_contact="",
                         join_date=date.today().replace(day=1).isoformat(), monthly_rent=rent, deposit=rent, notes="")


def add_expenses(uid):
    """Three months of typical running costs per PG (skipped if a PG already has expenses)."""
    today = date.today()
    months = []
    y, m = today.year, today.month
    for _ in range(3):
        months.append(f"{y}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    for pg in db.list_pgs(uid):
        if any(db.list_expenses(uid, pg["id"], mo) for mo in months):
            continue
        for mo in months:
            day = f"{mo}-10" if mo < today.strftime("%Y-%m") else today.isoformat()
            add = lambda cat, amt, to, mode="UPI", notes="": db.add_expense(uid, pg["id"], cat, amt, mo, day, to, mode, notes)
            add("Electricity", random.randint(4, 7) * 1000, "MSEDCL", notes=f"{random.randint(450, 800)} units")
            add("Staff salary", 9000, "Cook - Lakshmi", "Cash")
            add("Staff salary", 5000, "Housekeeping - Ramesh", "Cash")
            add("Internet", 1499, "Airtel Xstream Fiber")
            add("Water", 1500, "Water tanker")
            if random.random() < 0.6:
                add("Maintenance & repairs", random.choice([1200, 2500, 4800]), "Plumber / electrician",
                    notes=random.choice(["Geyser repair", "Tap leakage", "Fan replacement"]))


if __name__ == "__main__":
    main()
