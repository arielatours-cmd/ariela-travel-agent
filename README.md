# Ariella Tours v6

Version 6 focuses only on the agreed MVP:

1. Scan flight searches automatically every hour.
2. Store scan runs and offers in a database.
3. Score each offer internally.
4. Select up to five top deals from the last 24 hours.
5. Prepare one WhatsApp-ready message each day.

## Important

WhatsApp sending itself is **not connected yet**. Version 6 prepares and stores the daily message. The next version will connect the approved WhatsApp Business API provider.

## What changed from v5

- Removed the old service-fee/payment-link logic.
- Added SQLite persistence.
- Added rotating searches so API usage stays controlled.
- Added hourly APScheduler job.
- Added daily batch creation at 17:00 Israel time.
- Added duplicate filtering and destination diversity.
- Fixed the message formatter.
- Added scan status and daily preview endpoints.

## Environment variables

Required:

- `SERPAPI_API_KEY`

Optional:

- `SCHEDULER_ENABLED=true`
- `MAX_SEARCHES_PER_SCAN=8`
- `MIN_DEAL_SCORE=70`
- `MAX_DAILY_DEALS=5`
- `DAILY_SEND_HOUR=17`
- `DAILY_SEND_MINUTE=0`
- `DB_PATH=/tmp/ariella.db`

## Endpoints

- `GET /health`
- `POST /scan`
- `GET /scan-status`
- `GET /search?departure=TLV&arrival=ATH&outbound=2026-09-01&return_date=2026-09-06`
- `POST /daily-batch?force=true`
- `GET /daily-preview`
- `GET /delivery-status`

## Render note

`/tmp/ariella.db` can be erased when Render restarts. For real historical price retention, attach a persistent disk and change `DB_PATH` to that mounted path, or migrate to PostgreSQL before production.
