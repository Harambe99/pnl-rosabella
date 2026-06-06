# PnL Rosabella Web

TikTok Shop P&L dashboard. Multi-source imports → daily/monthly P&L → editable COGS + Monthly Inputs.

## Stack

- Python 3.11 + Django 4.2
- PostgreSQL
- Bootstrap CSS
- Hosted on Render

## Imports supported

| # | Source | Filter / Notes |
|---|---|---|
| 1 | TikTok Shop → Manage Orders (CSV) | Order revenue + COGS computation via SKU lookup |
| 2 | TikTok Shop → Statements → View by orders (xlsx) | Fees + adjustments, attributed by Order Created Date (handles late settlement) |
| 3 | TikTok Shop → Shop Analytics → GMV (xlsx) | Daily GMV override (matches portal exactly) |
| 4 | TikTok Shop → Marketing → Campaign overview (xlsx) | Daily ad spend |
| 5 | FBT Portal → Logistics Cost Overview (xlsx) | Hub Placement, Storage, Incidents — flat-spread monthly |

## How dedup works

- **Manage Orders**: dedup by `(Order ID, SKU ID)` — re-uploading the same file is safe
- **Settlement**: dedup by `(Order ID, Settlement ID, Type)` — same order can appear across statements without doubling
- **Analytics + Ad Spend**: upserted by date — latest upload wins per day

## Late-settlement backfill

Settlement rows store `Order Created Date`, not just statement date. When you upload May's Settlement file, late-April orders inside it get attributed to April days automatically — no manual reconciliation needed.

## Local dev

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_cogs
python manage.py runserver
# visit http://127.0.0.1:8000
```

## Deployment

Auto-deploys to Render from `main` branch. Env vars required:
- `DATABASE_URL` (auto-set by Render Postgres)
- `DJANGO_SECRET_KEY`
- `APP_PASSWORD` (shared password for login)
- `DEBUG=False`
