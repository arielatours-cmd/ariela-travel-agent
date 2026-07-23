import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, request

from admin import render_dashboard
from config import (
    ADMIN_TOKEN, APP_VERSION, DB_PATH, ISRAEL_TZ, MAX_DAILY_DEALS,
    MIN_DEAL_SCORE, SCHEDULER_ENABLED,
)
from daily import prepare_daily_batch
from database import (
    all_settings, dashboard_stats, get_daily_batch, init_db, latest_scan_run,
    recent_offers, recent_scan_runs, set_setting,
)
from scanner import run_hourly_scan, search_flights
from schedule_rules import delivery_status

app = Flask(__name__)
init_db()

if SCHEDULER_ENABLED and os.getenv("WERKZEUG_RUN_MAIN") != "true":
    from scheduler import start_scheduler
    start_scheduler()


def _authorized() -> bool:
    if not ADMIN_TOKEN:
        return True
    supplied = request.headers.get("X-Admin-Token") or request.args.get("token", "")
    return supplied == ADMIN_TOKEN


def _require_admin():
    if not _authorized():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    return None


@app.get("/")
def home():
    return jsonify({
        "name": "Ariella Tours", "version": APP_VERSION, "status": "online",
        "purpose": "flight scans, transparent scoring and daily WhatsApp-ready batches",
        "dashboard": "/admin",
        "endpoints": [
            "/health", "/admin", "/offers-preview", "/scan-history", "/scan",
            "/scan-status", "/daily-preview", "/daily-batch", "/search", "/settings",
        ],
    })


@app.get("/health")
def health():
    db_ok = True
    db_error = None
    try:
        with sqlite3.connect(DB_PATH, timeout=5) as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception as exc:
        db_ok = False
        db_error = str(exc)
    return jsonify({
        "status": "ok" if db_ok else "degraded", "version": APP_VERSION,
        "serpapi_configured": bool(os.getenv("SERPAPI_API_KEY")),
        "scheduler_enabled": SCHEDULER_ENABLED, "database_ok": db_ok,
        "database_error": db_error, "database_path": str(DB_PATH),
        "minimum_score": MIN_DEAL_SCORE, "maximum_daily_deals": MAX_DAILY_DEALS,
        "admin_protected": bool(ADMIN_TOKEN),
    })


@app.get("/admin")
def admin_dashboard():
    denied = _require_admin()
    if denied:
        return denied
    return render_dashboard(
        version=APP_VERSION, minimum_score=MIN_DEAL_SCORE,
        stats=dashboard_stats(MIN_DEAL_SCORE), offers=recent_offers(50),
        scans=recent_scan_runs(20),
    )


@app.get("/offers-preview")
def offers_preview():
    denied = _require_admin()
    if denied:
        return denied
    limit = request.args.get("limit", 50, type=int)
    minimum_score = request.args.get("minimum_score", type=int)
    offers = recent_offers(limit=limit, minimum_score=minimum_score)
    return jsonify({
        "status": "success", "count": len(offers), "minimum_deal_score": MIN_DEAL_SCORE,
        "offers": offers,
    })


@app.get("/scan-history")
def scan_history():
    denied = _require_admin()
    if denied:
        return denied
    limit = request.args.get("limit", 20, type=int)
    return jsonify({"status": "success", "scans": recent_scan_runs(limit)})


@app.post("/scan")
def scan_now():
    denied = _require_admin()
    if denied:
        return denied
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
    denied = _require_admin()
    if denied:
        return denied
    required = ["departure", "arrival", "outbound", "return_date"]
    missing = [key for key in required if not request.args.get(key)]
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
    denied = _require_admin()
    if denied:
        return denied
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


@app.route("/settings", methods=["GET", "POST"])
def settings_route():
    denied = _require_admin()
    if denied:
        return denied
    if request.method == "GET":
        return jsonify({
            "status": "success", "runtime_settings": all_settings(),
            "environment_settings": {
                "minimum_score": MIN_DEAL_SCORE, "maximum_daily_deals": MAX_DAILY_DEALS,
            },
        })
    data = request.get_json(silent=True) or {}
    allowed = {"scan_cursor"}
    invalid = [key for key in data if key not in allowed]
    if invalid:
        return jsonify({"status": "error", "message": f"Unsupported settings: {', '.join(invalid)}"}), 400
    for key, value in data.items():
        set_setting(key, str(value))
    return jsonify({"status": "success", "runtime_settings": all_settings()})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
