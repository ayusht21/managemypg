"""SQLite data layer for ManageMyPG.

Every read/write that touches a PG, room, tenant or payment is scoped to the
logged-in owner, so one owner can never see or modify another owner's data.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import date

DB_PATH = os.environ.get("MANAGEMYPG_DB", os.path.join(os.path.dirname(__file__), "managemypg.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    phone         TEXT,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pgs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    address     TEXT,
    city        TEXT,
    pg_type     TEXT NOT NULL DEFAULT 'Co-living',   -- Boys / Girls / Co-living
    contact     TEXT,
    rent_due_day INTEGER NOT NULL DEFAULT 5,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rooms (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    pg_id        INTEGER NOT NULL REFERENCES pgs(id) ON DELETE CASCADE,
    room_number  TEXT NOT NULL,
    floor        TEXT,
    capacity     INTEGER NOT NULL DEFAULT 1,       -- number of beds; kept in sync with `beds`
    rent_per_bed REAL NOT NULL DEFAULT 0,          -- default price for newly added beds
    room_type    TEXT NOT NULL DEFAULT 'Non-AC',  -- AC / Non-AC
    notes        TEXT,
    UNIQUE (pg_id, room_number)
);

-- Each bed has its own price; `section` groups beds inside a partitioned room.
CREATE TABLE IF NOT EXISTS beds (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    label   TEXT NOT NULL,
    section TEXT,
    rent    REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tenants (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    pg_id             INTEGER NOT NULL REFERENCES pgs(id) ON DELETE CASCADE,
    room_id           INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
    name              TEXT NOT NULL,
    phone             TEXT,
    email             TEXT,
    id_proof          TEXT,
    occupation        TEXT,
    emergency_contact TEXT,
    join_date         TEXT NOT NULL,
    monthly_rent      REAL NOT NULL DEFAULT 0,
    deposit           REAL NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'Active',  -- Active / Vacated
    vacate_date       TEXT,
    notes             TEXT
);

CREATE TABLE IF NOT EXISTS payments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    pg_id      INTEGER NOT NULL REFERENCES pgs(id) ON DELETE CASCADE,
    month      TEXT NOT NULL,        -- 'YYYY-MM' the rent is for
    amount     REAL NOT NULL,
    paid_on    TEXT NOT NULL,
    mode       TEXT NOT NULL DEFAULT 'UPI',
    notes      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    pg_id        INTEGER NOT NULL REFERENCES pgs(id) ON DELETE CASCADE,
    category     TEXT NOT NULL,
    amount       REAL NOT NULL,
    month        TEXT NOT NULL,        -- 'YYYY-MM' the expense is accounted to
    expense_date TEXT NOT NULL,
    paid_to      TEXT,
    mode         TEXT NOT NULL DEFAULT 'UPI',
    notes        TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_expenses_month ON expenses(pg_id, month);
CREATE INDEX IF NOT EXISTS idx_pgs_owner      ON pgs(owner_id);
CREATE INDEX IF NOT EXISTS idx_beds_room       ON beds(room_id);
CREATE INDEX IF NOT EXISTS idx_rooms_pg       ON rooms(pg_id);
CREATE INDEX IF NOT EXISTS idx_tenants_pg     ON tenants(pg_id);
CREATE INDEX IF NOT EXISTS idx_tenants_room   ON tenants(room_id);
CREATE INDEX IF NOT EXISTS idx_payments_month ON payments(pg_id, month);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Columns added after the first release; init_db() adds them to older databases.
TENANT_DEPOSIT_COLUMNS = {
    "deposit_status": "TEXT NOT NULL DEFAULT 'Held'",   # Held / Settled
    "deposit_rent_adjusted": "REAL NOT NULL DEFAULT 0",  # unpaid rent recovered from the deposit
    "deposit_deduction": "REAL NOT NULL DEFAULT 0",      # damages, cleaning, notice period etc.
    "deposit_deduction_reason": "TEXT",
    "deposit_refund": "REAL NOT NULL DEFAULT 0",
    "deposit_refund_date": "TEXT",
    "deposit_refund_mode": "TEXT",
    "deposit_notes": "TEXT",
}

DEPOSIT_ADJUSTMENT_MODE = "Deposit adjustment"


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(tenants)")}
        for col, ddl in TENANT_DEPOSIT_COLUMNS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE tenants ADD COLUMN {col} {ddl}")
        if "bed_id" not in existing:
            conn.execute("ALTER TABLE tenants ADD COLUMN bed_id INTEGER REFERENCES beds(id) ON DELETE SET NULL")
        _migrate_beds(conn)


def _migrate_beds(conn):
    """Rooms created before per-bed pricing: give them beds and put current tenants on them."""
    for room in conn.execute(
        "SELECT r.* FROM rooms r WHERE (SELECT COUNT(*) FROM beds b WHERE b.room_id = r.id) = 0"
    ).fetchall():
        _add_beds(conn, room["id"], room["capacity"], room["rent_per_bed"])
    for t in conn.execute(
        "SELECT id, room_id FROM tenants WHERE status = 'Active' AND room_id IS NOT NULL AND bed_id IS NULL"
    ).fetchall():
        free = conn.execute(
            "SELECT b.id FROM beds b WHERE b.room_id = ? AND NOT EXISTS "
            "(SELECT 1 FROM tenants x WHERE x.bed_id = b.id AND x.status = 'Active') ORDER BY b.id LIMIT 1",
            (t["room_id"],),
        ).fetchone()
        if free:
            conn.execute("UPDATE tenants SET bed_id = ? WHERE id = ?", (free["id"], t["id"]))

def _rows(cur):
    return [dict(r) for r in cur.fetchall()]


def _one(cur):
    r = cur.fetchone()
    return dict(r) if r else None


# ---------------------------------------------------------------- users

def create_user(name, email, phone, password_hash):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (name, email, phone, password_hash) VALUES (?, ?, ?, ?)",
            (name.strip(), email.strip().lower(), phone.strip(), password_hash),
        )
        return cur.lastrowid


def get_user_by_email(email):
    with get_conn() as conn:
        return _one(conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)))


def update_password(user_id, password_hash):
    with get_conn() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))


# ---------------------------------------------------------------- PGs

def list_pgs(owner_id):
    with get_conn() as conn:
        return _rows(conn.execute("SELECT * FROM pgs WHERE owner_id = ? ORDER BY name", (owner_id,)))


def get_pg(owner_id, pg_id):
    with get_conn() as conn:
        return _one(conn.execute("SELECT * FROM pgs WHERE id = ? AND owner_id = ?", (pg_id, owner_id)))


def create_pg(owner_id, name, address, city, pg_type, contact, rent_due_day):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO pgs (owner_id, name, address, city, pg_type, contact, rent_due_day) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (owner_id, name.strip(), address, city, pg_type, contact, rent_due_day),
        )
        return cur.lastrowid


def update_pg(owner_id, pg_id, name, address, city, pg_type, contact, rent_due_day):
    with get_conn() as conn:
        conn.execute(
            "UPDATE pgs SET name=?, address=?, city=?, pg_type=?, contact=?, rent_due_day=? "
            "WHERE id = ? AND owner_id = ?",
            (name.strip(), address, city, pg_type, contact, rent_due_day, pg_id, owner_id),
        )


def delete_pg(owner_id, pg_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM pgs WHERE id = ? AND owner_id = ?", (pg_id, owner_id))


def _assert_pg(conn, owner_id, pg_id):
    if not conn.execute("SELECT 1 FROM pgs WHERE id = ? AND owner_id = ?", (pg_id, owner_id)).fetchone():
        raise PermissionError("PG not found for this owner")


# ---------------------------------------------------------------- rooms & beds

def _add_beds(conn, room_id, n, rent, section=None):
    have = conn.execute("SELECT COUNT(*) FROM beds WHERE room_id = ?", (room_id,)).fetchone()[0]
    for i in range(have + 1, have + n + 1):
        conn.execute("INSERT INTO beds (room_id, label, section, rent) VALUES (?, ?, ?, ?)",
                     (room_id, f"Bed {i}", section, rent))
    _sync_capacity(conn, room_id)


def _sync_capacity(conn, room_id):
    conn.execute("UPDATE rooms SET capacity = (SELECT COUNT(*) FROM beds WHERE room_id = ?) WHERE id = ?",
                 (room_id, room_id))


def list_rooms(owner_id, pg_id):
    """Rooms with live occupancy counts and their bed price range."""
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        return _rows(conn.execute(
            """
            SELECT r.*,
                   (SELECT COUNT(*) FROM tenants t WHERE t.room_id = r.id AND t.status = 'Active') AS occupied,
                   r.capacity - (SELECT COUNT(*) FROM tenants t
                                  WHERE t.room_id = r.id AND t.status = 'Active') AS vacant,
                   (SELECT GROUP_CONCAT(t.name, ', ') FROM tenants t
                     WHERE t.room_id = r.id AND t.status = 'Active') AS tenant_names,
                   (SELECT MIN(rent) FROM beds b WHERE b.room_id = r.id) AS min_rent,
                   (SELECT MAX(rent) FROM beds b WHERE b.room_id = r.id) AS max_rent
            FROM rooms r
            WHERE r.pg_id = ?
            ORDER BY r.floor, CAST(r.room_number AS INTEGER), r.room_number
            """,
            (pg_id,),
        ))


def list_beds(owner_id, pg_id, room_id=None):
    """Beds with their room and current occupant (if any)."""
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        sql = """
            SELECT b.*, r.room_number, r.floor, r.room_type,
                   t.id AS tenant_id, t.name AS tenant_name
            FROM beds b
            JOIN rooms r ON r.id = b.room_id
            LEFT JOIN tenants t ON t.bed_id = b.id AND t.status = 'Active'
            WHERE r.pg_id = ?
        """
        params = [pg_id]
        if room_id:
            sql += " AND r.id = ?"
            params.append(room_id)
        sql += " ORDER BY r.floor, CAST(r.room_number AS INTEGER), r.room_number, COALESCE(b.section, ''), b.id"
        return _rows(conn.execute(sql, params))


def create_room(owner_id, pg_id, room_number, floor, capacity, rent_per_bed, room_type, notes):
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        cur = conn.execute(
            "INSERT INTO rooms (pg_id, room_number, floor, capacity, rent_per_bed, room_type, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pg_id, room_number.strip(), floor, capacity, rent_per_bed, room_type, notes),
        )
        _add_beds(conn, cur.lastrowid, capacity, rent_per_bed)
        return cur.lastrowid


def update_room(owner_id, pg_id, room_id, room_number, floor, room_type, notes):
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        conn.execute(
            "UPDATE rooms SET room_number=?, floor=?, room_type=?, notes=? WHERE id = ? AND pg_id = ?",
            (room_number.strip(), floor, room_type, notes, room_id, pg_id),
        )


def save_room_beds(owner_id, pg_id, room_id, beds):
    """Replace a room's bed list. beds: [{id (None for new), label, section, rent}].

    Beds left out are deleted — only allowed when nobody is staying on them.
    """
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        if not conn.execute("SELECT 1 FROM rooms WHERE id = ? AND pg_id = ?", (room_id, pg_id)).fetchone():
            raise PermissionError("Room not in this PG")
        if not beds:
            raise ValueError("A room needs at least one bed.")
        current = {r["id"]: dict(r) for r in conn.execute(
            "SELECT b.id, t.name AS tenant FROM beds b "
            "LEFT JOIN tenants t ON t.bed_id = b.id AND t.status = 'Active' WHERE b.room_id = ?", (room_id,))}
        keep = {b["id"] for b in beds if b.get("id")}
        if keep - set(current):
            raise PermissionError("Bed not in this room")
        removed = [current[i] for i in current if i not in keep]
        occupied = [r["tenant"] for r in removed if r["tenant"]]
        if occupied:
            raise ValueError(f"Can't remove a bed someone is staying on ({', '.join(occupied)}). "
                             "Move or vacate them first.")
        for r in removed:
            conn.execute("DELETE FROM beds WHERE id = ?", (r["id"],))
        for b in beds:
            label = (b.get("label") or "").strip() or "Bed"
            section = (b.get("section") or "").strip() or None
            rent = float(b.get("rent") or 0)
            if b.get("id"):
                conn.execute("UPDATE beds SET label=?, section=?, rent=? WHERE id = ? AND room_id = ?",
                             (label, section, rent, b["id"], room_id))
            else:
                conn.execute("INSERT INTO beds (room_id, label, section, rent) VALUES (?, ?, ?, ?)",
                             (room_id, label, section, rent))
        _sync_capacity(conn, room_id)


def delete_room(owner_id, pg_id, room_id):
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        occupied = conn.execute(
            "SELECT COUNT(*) FROM tenants WHERE room_id = ? AND status = 'Active'", (room_id,)
        ).fetchone()[0]
        if occupied:
            raise ValueError("Move or vacate the tenants in this room before deleting it.")
        conn.execute("DELETE FROM rooms WHERE id = ? AND pg_id = ?", (room_id, pg_id))


# ---------------------------------------------------------------- tenants

def list_tenants(owner_id, pg_id, status=None):
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        sql = (
            "SELECT t.*, r.room_number, b.label AS bed_label, b.section AS bed_section FROM tenants t "
            "LEFT JOIN rooms r ON r.id = t.room_id LEFT JOIN beds b ON b.id = t.bed_id WHERE t.pg_id = ?"
        )
        params = [pg_id]
        if status:
            sql += " AND t.status = ?"
            params.append(status)
        sql += " ORDER BY t.status, t.name"
        return _rows(conn.execute(sql, params))


def _resolve_bed(conn, pg_id, bed_id, exclude_tenant_id=None):
    """Room id for a free bed in this PG; raises if the bed is taken or not in the PG."""
    if not bed_id:
        return None
    row = conn.execute(
        "SELECT b.room_id FROM beds b JOIN rooms r ON r.id = b.room_id WHERE b.id = ? AND r.pg_id = ?",
        (bed_id, pg_id),
    ).fetchone()
    if not row:
        raise PermissionError("Bed not in this PG")
    taken = conn.execute(
        "SELECT name FROM tenants WHERE bed_id = ? AND status = 'Active' AND id != ?",
        (bed_id, exclude_tenant_id or -1),
    ).fetchone()
    if taken:
        raise ValueError(f"That bed is already taken by {taken['name']}.")
    return row["room_id"]


def create_tenant(owner_id, pg_id, bed_id, **f):
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        room_id = _resolve_bed(conn, pg_id, bed_id)
        conn.execute(
            """
            INSERT INTO tenants (pg_id, room_id, bed_id, name, phone, email, id_proof, occupation,
                                 emergency_contact, join_date, monthly_rent, deposit, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (pg_id, room_id, bed_id, f["name"].strip(), f["phone"], f["email"], f["id_proof"], f["occupation"],
             f["emergency_contact"], f["join_date"], f["monthly_rent"], f["deposit"], f["notes"]),
        )


def update_tenant(owner_id, pg_id, tenant_id, bed_id, **f):
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        room_id = _resolve_bed(conn, pg_id, bed_id, exclude_tenant_id=tenant_id)
        conn.execute(
            """
            UPDATE tenants SET room_id=?, bed_id=?, name=?, phone=?, email=?, id_proof=?, occupation=?,
                   emergency_contact=?, join_date=?, monthly_rent=?, deposit=?, notes=?
            WHERE id = ? AND pg_id = ?
            """,
            (room_id, bed_id, f["name"].strip(), f["phone"], f["email"], f["id_proof"], f["occupation"],
             f["emergency_contact"], f["join_date"], f["monthly_rent"], f["deposit"], f["notes"],
             tenant_id, pg_id),
        )


def vacate_tenant(owner_id, pg_id, tenant_id, vacate_date):
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        conn.execute(
            "UPDATE tenants SET status='Vacated', vacate_date=?, room_id=NULL, bed_id=NULL WHERE id = ? AND pg_id = ?",
            (vacate_date, tenant_id, pg_id),
        )


def delete_tenant(owner_id, pg_id, tenant_id):
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        conn.execute("DELETE FROM tenants WHERE id = ? AND pg_id = ?", (tenant_id, pg_id))


# ---------------------------------------------------------------- payments

def month_bounds(month):
    y, m = map(int, month.split("-"))
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return start.isoformat(), end.isoformat()


def rent_status(owner_id, pg_id, month):
    """Per-tenant rent status for a month: everyone who stayed during that month."""
    start, end = month_bounds(month)
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        return _rows(conn.execute(
            """
            SELECT t.id AS tenant_id, t.name, t.phone, r.room_number, t.monthly_rent AS due,
                   t.status,
                   COALESCE(SUM(p.amount), 0) AS paid,
                   MAX(p.paid_on) AS last_paid_on
            FROM tenants t
            LEFT JOIN rooms r ON r.id = t.room_id
            LEFT JOIN payments p ON p.tenant_id = t.id AND p.month = ?
            WHERE t.pg_id = ?
              AND t.join_date < ?
              AND (t.vacate_date IS NULL OR t.vacate_date >= ?)
            GROUP BY t.id
            ORDER BY r.room_number, t.name
            """,
            (month, pg_id, end, start),
        ))


def add_payment(owner_id, pg_id, tenant_id, month, amount, paid_on, mode, notes):
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        if not conn.execute("SELECT 1 FROM tenants WHERE id = ? AND pg_id = ?", (tenant_id, pg_id)).fetchone():
            raise PermissionError("Tenant not in this PG")
        cur = conn.execute(
            "INSERT INTO payments (tenant_id, pg_id, month, amount, paid_on, mode, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, pg_id, month, amount, paid_on, mode, notes),
        )
        return cur.lastrowid


def list_payments(owner_id, pg_id, month=None, tenant_id=None):
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        sql = (
            "SELECT p.*, t.name AS tenant_name FROM payments p "
            "JOIN tenants t ON t.id = p.tenant_id WHERE p.pg_id = ?"
        )
        params = [pg_id]
        if month:
            sql += " AND p.month = ?"
            params.append(month)
        if tenant_id:
            sql += " AND p.tenant_id = ?"
            params.append(tenant_id)
        sql += " ORDER BY p.paid_on DESC, p.id DESC"
        return _rows(conn.execute(sql, params))


def receipt_data(owner_id, pg_id, payment_ids=None, month=None):
    """Payments with everything a rent receipt needs. Filter by ids or by rent month."""
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        sql = """
            SELECT p.*, t.name AS tenant_name, t.phone AS tenant_phone, t.monthly_rent,
                   r.room_number, b.label AS bed_label, b.section AS bed_section,
                   (SELECT COALESCE(SUM(x.amount), 0) FROM payments x
                     WHERE x.tenant_id = p.tenant_id AND x.month = p.month
                       AND (x.paid_on < p.paid_on OR (x.paid_on = p.paid_on AND x.id <= p.id))) AS paid_to_date
            FROM payments p
            JOIN tenants t ON t.id = p.tenant_id
            LEFT JOIN rooms r ON r.id = t.room_id
            LEFT JOIN beds b ON b.id = t.bed_id
            WHERE p.pg_id = ?
        """
        params = [pg_id]
        if payment_ids is not None:
            if not payment_ids:
                return []
            sql += f" AND p.id IN ({','.join('?' * len(payment_ids))})"
            params += list(payment_ids)
        if month:
            sql += " AND p.month = ?"
            params.append(month)
        sql += " ORDER BY p.paid_on, p.id"
        return _rows(conn.execute(sql, params))


def delete_payment(owner_id, pg_id, payment_id):
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        conn.execute("DELETE FROM payments WHERE id = ? AND pg_id = ?", (payment_id, pg_id))


# ---------------------------------------------------------------- expenses

def add_expense(owner_id, pg_id, category, amount, month, expense_date, paid_to, mode, notes):
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        conn.execute(
            "INSERT INTO expenses (pg_id, category, amount, month, expense_date, paid_to, mode, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (pg_id, category, amount, month, expense_date, paid_to, mode, notes),
        )


def list_expenses(owner_id, pg_id, month):
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        return _rows(conn.execute(
            "SELECT * FROM expenses WHERE pg_id = ? AND month = ? ORDER BY expense_date DESC, id DESC",
            (pg_id, month),
        ))


def delete_expense(owner_id, pg_id, expense_id):
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        conn.execute("DELETE FROM expenses WHERE id = ? AND pg_id = ?", (expense_id, pg_id))


def income_vs_expenses(owner_id, pg_id, months):
    """[{month, collected, expenses}] for the given 'YYYY-MM' months."""
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        marks = ",".join("?" * len(months))
        inc = dict(conn.execute(
            f"SELECT month, SUM(amount) FROM payments WHERE pg_id = ? AND month IN ({marks}) GROUP BY month",
            (pg_id, *months)).fetchall())
        exp = dict(conn.execute(
            f"SELECT month, SUM(amount) FROM expenses WHERE pg_id = ? AND month IN ({marks}) GROUP BY month",
            (pg_id, *months)).fetchall())
    return [{"month": m, "collected": inc.get(m, 0) or 0, "expenses": exp.get(m, 0) or 0} for m in months]


# ---------------------------------------------------------------- deposits

def deposits(owner_id, pg_id):
    """All tenants with a deposit, with their settlement state."""
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        return _rows(conn.execute(
            "SELECT t.*, r.room_number FROM tenants t LEFT JOIN rooms r ON r.id = t.room_id "
            "WHERE t.pg_id = ? AND t.deposit > 0 ORDER BY t.vacate_date DESC, t.name",
            (pg_id,),
        ))


def unpaid_rent_months(owner_id, pg_id, tenant_id, lookback=3):
    """Months (up to `lookback`, ending at the vacate month) where the tenant still owes rent."""
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        t = _one(conn.execute("SELECT * FROM tenants WHERE id = ? AND pg_id = ?", (tenant_id, pg_id)))
        if not t:
            return []
        end = (t["vacate_date"] or date.today().isoformat())[:7]
        y, m = map(int, end.split("-"))
        months = []
        for _ in range(lookback):
            if f"{y}-{m:02d}" < t["join_date"][:7]:
                break
            months.append(f"{y}-{m:02d}")
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        out = []
        for mo in reversed(months):
            paid = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE tenant_id = ? AND month = ?",
                (tenant_id, mo)).fetchone()[0]
            if paid < t["monthly_rent"]:
                out.append({"month": mo, "due": t["monthly_rent"], "paid": paid,
                            "balance": t["monthly_rent"] - paid})
        return out


def settle_deposit(owner_id, pg_id, tenant_id, rent_adjustments, deduction, reason,
                   refund, refund_date, refund_mode, notes):
    """Close out a vacated tenant's deposit.

    rent_adjustments: [(month, amount)] — recorded as rent payments so those months show as paid.
    """
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        t = _one(conn.execute("SELECT * FROM tenants WHERE id = ? AND pg_id = ?", (tenant_id, pg_id)))
        if not t:
            raise PermissionError("Tenant not in this PG")
        if t["deposit_status"] == "Settled":
            raise ValueError("This deposit is already settled.")
        rent_total = sum(a for _, a in rent_adjustments)
        if rent_total + deduction + refund > t["deposit"] + 0.01:
            raise ValueError("Rent adjusted + deductions + refund can't exceed the deposit.")
        for month, amount in rent_adjustments:
            if amount > 0:
                conn.execute(
                    "INSERT INTO payments (tenant_id, pg_id, month, amount, paid_on, mode, notes) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (tenant_id, pg_id, month, amount, refund_date, DEPOSIT_ADJUSTMENT_MODE, "Adjusted from deposit"),
                )
        conn.execute(
            """
            UPDATE tenants SET deposit_status='Settled', deposit_rent_adjusted=?, deposit_deduction=?,
                   deposit_deduction_reason=?, deposit_refund=?, deposit_refund_date=?,
                   deposit_refund_mode=?, deposit_notes=?
            WHERE id = ? AND pg_id = ?
            """,
            (rent_total, deduction, reason, refund, refund_date, refund_mode, notes, tenant_id, pg_id),
        )


def undo_deposit_settlement(owner_id, pg_id, tenant_id):
    with get_conn() as conn:
        _assert_pg(conn, owner_id, pg_id)
        conn.execute("DELETE FROM payments WHERE tenant_id = ? AND pg_id = ? AND mode = ?",
                     (tenant_id, pg_id, DEPOSIT_ADJUSTMENT_MODE))
        conn.execute(
            """
            UPDATE tenants SET deposit_status='Held', deposit_rent_adjusted=0, deposit_deduction=0,
                   deposit_deduction_reason=NULL, deposit_refund=0, deposit_refund_date=NULL,
                   deposit_refund_mode=NULL, deposit_notes=NULL
            WHERE id = ? AND pg_id = ?
            """,
            (tenant_id, pg_id),
        )


# ---------------------------------------------------------------- portfolio summary

def portfolio_summary(owner_id, month):
    """One row per PG with beds, occupancy and this month's rent numbers."""
    start, end = month_bounds(month)
    with get_conn() as conn:
        return _rows(conn.execute(
            """
            SELECT g.id, g.name, g.city, g.pg_type,
                   (SELECT COUNT(*) FROM rooms r WHERE r.pg_id = g.id) AS rooms,
                   (SELECT COALESCE(SUM(capacity), 0) FROM rooms r WHERE r.pg_id = g.id) AS beds,
                   (SELECT COUNT(*) FROM tenants t
                     WHERE t.pg_id = g.id AND t.status = 'Active' AND t.room_id IS NOT NULL) AS occupied,
                   (SELECT COALESCE(SUM(t.monthly_rent), 0) FROM tenants t
                     WHERE t.pg_id = g.id AND t.join_date < ?
                       AND (t.vacate_date IS NULL OR t.vacate_date >= ?)) AS expected,
                   (SELECT COALESCE(SUM(p.amount), 0) FROM payments p
                     WHERE p.pg_id = g.id AND p.month = ?) AS collected,
                   (SELECT COALESCE(SUM(e.amount), 0) FROM expenses e
                     WHERE e.pg_id = g.id AND e.month = ?) AS expenses,
                   (SELECT COALESCE(SUM(t.deposit), 0) FROM tenants t
                     WHERE t.pg_id = g.id AND t.deposit_status = 'Held') AS deposits_held
            FROM pgs g WHERE g.owner_id = ?
            ORDER BY g.name
            """,
            (end, start, month, month, owner_id),
        ))
