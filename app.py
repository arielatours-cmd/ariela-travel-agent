import os
import sqlite3
import threading
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, request, redirect

from admin import render_dashboard, render_feedback_dashboard, render_analytics_dashboard
from config import (
    ADMIN_TOKEN, APP_VERSION, DB_PATH, ISRAEL_TZ, MAX_DAILY_DEALS,
    MIN_DEAL_SCORE, SCHEDULER_ENABLED, FLASK_SECRET_KEY, DESTINATIONS,
)
from daily import prepare_daily_batch
from database import (
    all_settings, dashboard_stats, business_analytics, get_daily_batch, init_db, latest_scan_run,
    recent_feedback, recent_offers, recent_scan_runs, set_setting, get_setting, connection,
    unread_feedback_count, mark_feedback_seen, request_scan_stop, offers_for_scan_run,
)
from scanner import run_hourly_scan, run_destination_scan, run_wide_scan, search_flights
from schedule_rules import delivery_status
from public_site import site
from whatsapp_coexistence import whatsapp_coexistence
from whatsapp import (
    WhatsAppConfigurationError, WhatsAppSendError,
    send_text_message, whatsapp_status,
)

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY
app.register_blueprint(site)
app.register_blueprint(whatsapp_coexistence)

init_db()

# Manual scans must never run inside the browser request itself: a wide flight
# search can exceed Gunicorn's request timeout. The request only starts a
# background worker and returns immediately; the admin page polls job status.
_manual_scan_lock = threading.Lock()
_manual_scan_jobs = {}


def _background_scan_worker(job_id, label, runner):
    try:
        _manual_scan_jobs[job_id]["status"] = "running"
        result = runner()
        _manual_scan_jobs[job_id]["result"] = result
        _manual_scan_jobs[job_id]["status"] = "finished"
    except BaseException as exc:
        _manual_scan_jobs[job_id]["status"] = "failed"
        _manual_scan_jobs[job_id]["error"] = str(exc)
        app.logger.exception("Background manual scan failed: %s", label)
    finally:
        _manual_scan_lock.release()


def _start_background_scan(label, runner):
    # Only one manual scan at a time. This prevents accidental double-clicks
    # from burning the SerpApi quota.
    if not _manual_scan_lock.acquire(blocking=False):
        return None, (jsonify({
            "status": "busy",
            "message": "כבר מתבצעת סריקה ידנית. יש להמתין לסיומה."
        }), 409)

    job_id = uuid.uuid4().hex
    _manual_scan_jobs[job_id] = {
        "job_id": job_id,
        "label": label,
        "status": "starting",
        "result": None,
        "error": None,
    }
    thread = threading.Thread(
        target=_background_scan_worker,
        args=(job_id, label, runner),
        daemon=True,
        name=f"ariella-{label}-{job_id[:8]}",
    )
    thread.start()
    return job_id, None

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
        "database_persistent_path": str(DB_PATH).startswith("/var/data/"),
        "minimum_score": MIN_DEAL_SCORE, "maximum_daily_deals": MAX_DAILY_DEALS,
        "admin_protected": bool(ADMIN_TOKEN),
        "whatsapp": whatsapp_status(),
    })


@app.post("/admin/clear-test-vacations")
def clear_test_vacations():
    denied = _require_admin()
    if denied:
        return denied
    supplied = request.args.get("token") or request.form.get("token") or request.headers.get("X-Admin-Token") or ""
    with connection() as conn:
        trip_ids = [int(r["id"]) for r in conn.execute("SELECT id FROM trip_requests").fetchall()]
        if trip_ids:
            placeholders = ",".join("?" for _ in trip_ids)
            conn.execute(f"UPDATE offers SET trip_id=NULL WHERE trip_id IN ({placeholders})", trip_ids)
        conn.execute("DELETE FROM trip_requests")
        conn.commit()
    return redirect("/admin" + (("?token=" + supplied) if supplied else ""))


@app.post("/admin/toggle-test-mode")
def toggle_test_mode():
    denied = _require_admin()
    if denied:
        return denied
    current = str(get_setting("qa_test_mode", "0") or "0") == "1"
    set_setting("qa_test_mode", "0" if current else "1")
    supplied = request.args.get("token") or ""
    return redirect("/admin" + (("?token=" + supplied) if supplied else ""))


@app.get("/admin")
def admin_dashboard():
    denied = _require_admin()
    if denied:
        return denied
    return render_dashboard(
        version=APP_VERSION, minimum_score=MIN_DEAL_SCORE,
        stats=dashboard_stats(MIN_DEAL_SCORE), offers=recent_offers(50),
        scans=recent_scan_runs(20), feedback_count=unread_feedback_count(),
        test_mode=str(get_setting("qa_test_mode", "0") or "0") == "1",
        token=request.args.get("token", ""),
    )


@app.get("/admin/analytics")
def admin_analytics():
    denied = _require_admin()
    if denied:
        return denied
    return render_analytics_dashboard(version=APP_VERSION, analytics=business_analytics(12), token=request.args.get("token", ""))


@app.get("/admin/feedback")
def admin_feedback():
    denied = _require_admin()
    if denied:
        return denied
    feedback = recent_feedback(500)
    mark_feedback_seen()
    return render_feedback_dashboard(feedback=feedback, token=request.args.get("token", ""))


@app.get("/offers-preview")
def offers_preview():
    denied = _require_admin()
    if denied:
        return denied
    limit = request.args.get("limit", 50, type=int)
    minimum_score = request.args.get("minimum_score", type=int)
    offers = recent_offers(limit=limit, minimum_score=minimum_score)
    return jsonify({"status": "success", "count": len(offers), "minimum_deal_score": MIN_DEAL_SCORE, "offers": offers})


@app.get("/feedback-preview")
def feedback_preview():
    denied = _require_admin()
    if denied:
        return denied
    messages = recent_feedback(request.args.get("limit", 100, type=int))
    return jsonify({"status": "success", "count": len(messages), "messages": messages})


@app.get("/scan-history")
def scan_history():
    denied = _require_admin()
    if denied:
        return denied
    return jsonify({"status": "success", "scans": recent_scan_runs(request.args.get("limit", 20, type=int))})


@app.post("/scan")
def scan_now():
    denied = _require_admin()
    if denied: return denied
    try:
        job_id, error = _start_background_scan("trial", lambda: run_hourly_scan(1))
        if error: return error
        return jsonify({"status": "accepted", "job_id": job_id, "message": "סריקת הניסיון התחילה ברקע."}), 202
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.post("/scan-destination")
def scan_destination():
    denied = _require_admin()
    if denied: return denied
    try:
        arrival = request.args.get("arrival", "FCO").upper()
        max_searches = max(1, min(int(request.args.get("max_searches", "3")), 8))
        job_id, error = _start_background_scan(f"destination-{arrival}", lambda: run_destination_scan(arrival, max_searches))
        if error: return error
        return jsonify({"status": "accepted", "job_id": job_id, "message": f"סריקת {arrival} התחילה ברקע."}), 202
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.post("/scan-wide")
def scan_wide():
    denied = _require_admin()
    if denied: return denied
    try:
        max_destinations = max(1, min(int(request.args.get("max_destinations", "30")), len(DESTINATIONS)))
        job_id, error = _start_background_scan("wide", lambda: run_wide_scan(max_destinations))
        if error: return error
        return jsonify({"status": "accepted", "job_id": job_id, "destinations": max_destinations}), 202
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.get("/manual-scan-status/<job_id>")
def manual_scan_status(job_id):
    denied = _require_admin()
    if denied: return denied
    job = _manual_scan_jobs.get(job_id)
    if not job: return jsonify({"status": "unknown"}), 404
    return jsonify(job)


@app.post("/scan-stop")
def scan_stop():
    denied = _require_admin()
    if denied: return denied
    request_scan_stop()
    return jsonify({"status":"success","message":"נשלחה בקשת עצירה."})


@app.get("/scan-run/<int:run_id>/offers")
def scan_run_offers(run_id):
    denied = _require_admin()
    if denied: return denied
    offers = offers_for_scan_run(run_id)
    return jsonify({"status":"success","scan_run_id":run_id,"count":len(offers),"offers":offers})


@app.get("/scan-status")
def scan_status():
    return jsonify({"status": "success", "latest_scan": latest_scan_run()})


@app.get("/search")
def manual_search():
    denied = _require_admin()
    if denied: return denied
    required = ["departure", "arrival", "outbound", "return_date"]
    missing = [key for key in required if not request.args.get(key)]
    if missing: return jsonify({"status": "error", "message": f"Missing: {', '.join(missing)}"}), 400
    try:
        result = search_flights(request.args["departure"].upper(), request.args["arrival"].upper(), request.args["outbound"], request.args["return_date"])
        return jsonify({"status": "success", **result})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.post("/daily-batch")
def create_daily_batch():
    denied = _require_admin()
    if denied: return denied
    try:
        return jsonify({"status": "success", **prepare_daily_batch(force=request.args.get("force", "false").lower() == "true")})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.get("/daily-preview")
def daily_preview():
    today = datetime.now(ZoneInfo(ISRAEL_TZ)).date().isoformat()
    batch = get_daily_batch(today)
    if not batch:
        batch = prepare_daily_batch(force=True)["batch"]
    return jsonify({"status": "success", "batch": batch})


@app.get("/delivery-status")
def delivery_status_route():
    return jsonify(delivery_status())


@app.get("/whatsapp-status")
def whatsapp_status_route():
    denied = _require_admin()
    if denied: return denied
    return jsonify({"status": "success", **whatsapp_status()})


@app.post("/whatsapp-send-test")
def whatsapp_send_test():
    denied = _require_admin()
    if denied: return denied
    try:
        result = prepare_daily_batch(force=True)
        message = (result.get("message") or "").strip()
        deals = result.get("deals") or []
        if not deals or not message:
            return jsonify({"status": "error", "message": "אין כרגע דילים מתאימים לשליחה."}), 400
        send_result = send_text_message(message)
        return jsonify({"status": "success", "deal_count": len(deals), "recipient_ending": send_result.get("recipient_ending"), "message_id": send_result.get("message_id")})
    except (WhatsAppConfigurationError, WhatsAppSendError) as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.get("/settings")
def settings():
    denied = _require_admin()
    if denied: return denied
    return jsonify({"status": "success", "settings": all_settings()})


@app.get("/whatsapp-webhook")
def whatsapp_webhook_verify():
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == verify_token and verify_token:
        return request.args.get("hub.challenge", ""), 200
    return "Verification failed", 403


@app.post("/whatsapp-webhook")
def whatsapp_webhook_receive():
    payload = request.get_json(silent=True) or {}
    app.logger.info("WhatsApp webhook event received: object=%s entries=%s", payload.get("object"), len(payload.get("entry") or []))
    return jsonify({"status": "received"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
