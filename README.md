# 🏠 ManageMyPG

A Streamlit app for PG (paying guest) owners to manage **multiple PGs** from one login:
rooms & beds, who lives where, and who has paid rent.

## Features
- **Owner accounts**: sign up / log in (passwords hashed with PBKDF2). Each owner only sees their own data.
- **Multiple PGs**: create any number of PGs (Boys / Girls / Co-living) and switch between them from the sidebar.
  The *My PGs* page shows occupancy and this month's collection across all of them.
- **Rooms & beds**: add single rooms or a range (e.g. 101–110) with a number of beds and a starting price.
  Every bed can then have its **own price**, and beds can be grouped into **sections** for partitioned rooms
  (e.g. one room split into "Part A" with 2 beds and "Part B" with a pricier single bed).
  The room board shows every bed with its price and occupant (🟥 occupied / 🟩 vacant).
- **Tenants**: assign each tenant to a specific bed (a bed can't be double-booked); rent defaults to the bed's
  price. Store phone, ID proof, deposit, emergency contact.
  Edit, move rooms, mark as vacated (frees the bed, keeps history). Search and CSV export.
- **Rent**: per-month view of who paid, partial payments, pending balance, payment mode/transaction ID,
  one-click WhatsApp reminder, payment history with undo, CSV export.
- **Rent receipts (PDF)**: download a receipt right after recording a payment, or any past one from
  *Rent → Payments & receipts*, or all of a month's receipts in one printable PDF. Each receipt has a receipt
  number, tenant, room/bed, month, payment mode, amount in words, the month's balance and a
  paid-in-full / part-payment stamp.
- **Expenses**: log electricity, staff salaries, maintenance, water, internet, food and more per PG.
  Count a bill in the month it belongs to, see a per-category breakdown, copy repeating costs (salaries,
  internet) from last month in one click, and a 6-month profit & loss (rent collected − expenses).
- **Deposit refunds**: when a tenant vacates, settle their deposit — recover unpaid rent (recorded as rent paid),
  add deductions with a reason (damage, cleaning, notice period), and the refund is worked out for you.
  Settled deposits are kept as history with an undo option.
- **Dashboard**: vacant beds, pending rent, expenses, net profit, deposits held / to refund, and a 6-month
  rent-vs-expenses chart.

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```
Data is stored in `managemypg.db` (SQLite) next to the app. Set `MANAGEMYPG_DB=/path/to/file.db` to use another location.

## Notes
- A tenant who stays any part of a month is billed their full monthly rent for that month.
- Login lasts for the browser session; refreshing the page asks you to log in again.
