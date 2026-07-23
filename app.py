import os
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, request

from config import APP_VERSION, DB_PATH, ISRAEL_TZ, MAX_DAILY_DEALS, MIN_DEAL_SCORE, SCHEDULER_ENABLED
from daily import prepare_daily_batch
from database import get_daily_batch, init_db, latest_scan_run
from scanner import run_hourly_scan, search_flights
from schedule_rules import delivery_status

app = Flask(__name__)
init_db()

if SCHEDULER_ENABLED and os.getenv("WERKZEUG_RUN_MAIN") != "true":
    from scheduler import start_scheduler
    start_scheduler()


@app.get("/")
def home():
    return jsonify({
        "name": "Ariella Tours", "version": APP_VERSION, "status": "online",
        "purpose": "hourly flight scans and one daily WhatsApp-ready batch",
        "endpoints": ["/health", "/scan", "/scan-status", "/daily-preview", "/daily-batch", "/search"],
    })


@app.get("/health")
def health():
    return jsonify({
        "status": "ok", "version": APP_VERSION, "serpapi_configured": bool(os.getenv("SERPAPI_API_KEY")),
        "scheduler_enabled": SCHEDULER_ENABLED, "database_path": str(DB_PATH),
        "minimum_score": MIN_DEAL_SCORE, "maximum_daily_deals": MAX_DAILY_DEALS,
    })


@app.post("/scan")
def scan_now():
    try:
        max_searches = int(request.args.get("max_searches", "0")) or None
        return jsonify(run_hourly_scan(max_searches))
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.get("/scan-status")
def scan_status():
    return jsonify({"status": "success", "latest_scan": latest_scan_run()})


@app.get("/search")
def manual_search():
    required = ["departure", "arrival", "outbound", "return_date"]
    missing = [k for k in required if not request.args.get(k)]
    if missing:
        return jsonify({"status": "error", "message": f"Missing: {', '.join(missing)}"}), 400
    try:
        result = search_flights(
            request.args["departure"].upper(), request.args["arrival"].upper(),
            request.args["outbound"], request.args["return_date"],
        )
        return jsonify({"status": "success", **result})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.post("/daily-batch")
def create_daily_batch():
    force = request.args.get("force", "false").lower() == "true"
    try:
        return jsonify({"status": "success", **prepare_daily_batch(force=force)})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.get("/daily-preview")
def daily_preview():
    today = datetime.now(ZoneInfo(ISRAEL_TZ)).date().isoformat()
    batch = get_daily_batch(today)
    if not batch:
        result = prepare_daily_batch(force=True)
        batch = result["batch"]
    return jsonify({"status": "success", "batch": batch})


@app.get("/delivery-status")
def delivery_status_route():
    return jsonify(delivery_status())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
