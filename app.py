import hmac
import html
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, request, redirect, Response
from werkzeug.exceptions import HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from urllib.parse import quote

# Gunicorn/Flask leave the root logger at its default WARNING level, which
# silently drops every logging.info() call app-wide (booking diagnostics,
# scan progress, etc. never reach Render's log stream). INFO must be
# configured before any other module logs anything.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from admin import render_dashboard, render_feedback_dashboard, render_analytics_dashboard, render_hfa_routes_dashboard
from config import (
    ADMIN_TOKEN, APP_VERSION, DB_PATH, ISRAEL_TZ, MAX_DAILY_DEALS,
    MIN_DEAL_SCORE, SCHEDULER_ENABLED, FLASK_SECRET_KEY, DESTINATIONS,
    PUBLIC_BASE_URL_WARNING,
)
from daily import prepare_daily_batch
from database import (
    all_settings, dashboard_stats, business_analytics, get_daily_batch, init_db, latest_scan_run,
    recent_feedback, recent_offers, recent_scan_runs, set_setting, get_setting, connection,
    unread_feedback_count, mark_feedback_seen, request_scan_stop, offers_for_scan_run,
    normalize_scan_run_price_groups, recent_whatsapp_queue, recent_partner_commissions,
    scan_sharing_stats, recent_whatsapp_inbound_log, delete_member_account,
)
from scanner import run_hourly_scan, run_destination_scan, run_wide_scan, search_flights
import scanner as _scanner
from din_agent import enrich_offer_legal_terms
from schedule_rules import delivery_status
from public_site import site, _confirm_paid_search, rematch_trip_without_new_scan
from whatsapp_coexistence import whatsapp_coexistence
from ariella_chat_v2 import ariella_chat_v2
from ariella_chat_clean import ariella_chat_clean
from ai_usage import usage_summary, usage_rows, usage_for_conversation, diagnostic_rows, DIAGNOSTIC_EVENT_SOURCES
from whatsapp_deals_messages import on_whatsapp_deals_paid
from partner_commissions import sync_cj_commissions, cj_connection_check
from mailer import mail_check
from whatsapp import (
    WhatsAppConfigurationError, WhatsAppSendError,
    send_text_message, whatsapp_status, whatsapp_subscription_check,
    whatsapp_register_number, whatsapp_request_code, whatsapp_verify_code,
)

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

# Per the business owner's decision (relayed via Shlomo, 17.10.2026): members
# were being logged out of the public site every time the browser closed,
# because session["member_id"] (public_site.py's join/login routes) was set
# without session.permanent, so Flask defaulted to a non-permanent, browser-
# session-only cookie with no PERMANENT_SESSION_LIFETIME to extend it even
# if it had been. Approved lifetime: 30 days. This does not affect
# /admin/login, which signs its own separate cookie (ADMIN_COOKIE) rather
# than using Flask's session at all.
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Task 008a: APP_VERSION is a manually-edited constant that's easy to forget
# to bump, so /health can silently keep reporting a stale version after a
# real deploy. RENDER_GIT_COMMIT is set automatically by Render on every
# deploy (empty/unset in local dev) - computed once at process startup so a
# restart (not just a new deploy) also shows up here.
_DEPLOYED_COMMIT = (os.getenv("RENDER_GIT_COMMIT") or "").strip()[:7] or None
_STARTED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")

app.register_blueprint(site)
app.register_blueprint(whatsapp_coexistence)
app.register_blueprint(ariella_chat_v2)
app.register_blueprint(ariella_chat_clean)


@app.errorhandler(Exception)
def _log_unhandled_exception(exc):
    # Seen live (Shaked, 2026-10-12): under concurrent chat load, some
    # requests failed fast (~40s, well under any client timeout) with no
    # trace anywhere queryable - every known error path inside chat_clean()
    # (the two Claude calls, every DB write) already has its own try/except
    # with a graceful fallback, so a genuinely UNHANDLED exception (her
    # leading suspect: sqlite3.OperationalError "database is locked" from
    # lock contention under concurrent writes) would only ever have shown up
    # in Render's own log stream - not accessible from here, and not
    # queryable without dashboard access. Recording it into ai_usage (already
    # exposed via /admin/ai-usage.csv) makes the real exception type/message
    # visible through infrastructure already in use, without needing log
    # access at all.
    # Registering for the bare Exception class also intercepts every
    # intentional HTTPException (404s, _require_admin's 401s via abort,
    # etc.) - those are normal routing/auth outcomes, not bugs, and must
    # keep their own status code/body instead of being flattened into a
    # generic 500 here.
    if isinstance(exc, HTTPException):
        return exc
    logging.exception("Unhandled exception in %s %s", request.method, request.path)
    try:
        from ai_usage import record_ai_usage
        record_ai_usage(
            source="unhandled_exception",
            model=f"{request.method} {request.path}",
            error=f"{type(exc).__name__}: {exc}".strip()[:500],
        )
    except Exception:
        logging.exception("Failed to record unhandled-exception diagnostic row")
    return jsonify({
        "status": "error",
        "message": "שגיאה פנימית זמנית. נסו שוב בעוד רגע.",
    }), 500

# Din is Ariella's legal/terms verification layer. Scanner functions resolve
# `insert_offer` from their module globals at runtime, so wrapping it here makes
# every deal pass through Din before it is persisted or refreshed in the DB.
_original_scanner_insert_offer = _scanner.insert_offer

def _insert_offer_with_din(scan_run_id, offer):
    try:
        offer = enrich_offer_legal_terms(offer)
    except Exception as exc:
        app.logger.warning("Din verification failed for deal: %s", exc)
        offer.setdefault("consumer_protection", {
            "status": "check", "label": "יש לבדוק באתר הספק", "checked_by": "Din"
        })
        offer.setdefault("change_cancel", {
            "status": "check", "label": "יש לבדוק באתר הספק", "checked_by": "Din"
        })
    return _original_scanner_insert_offer(scan_run_id, offer)

_scanner.insert_offer = _insert_offer_with_din

init_db()
_latest_for_normalization = latest_scan_run()
if _latest_for_normalization and _latest_for_normalization.get("status") != "running":
    normalize_scan_run_price_groups(int(_latest_for_normalization["id"]))

_manual_scan_lock = threading.Lock()
_manual_scan_jobs = {}


def _background_scan_worker(job_id, label, runner, flask_app=None):
    try:
        _manual_scan_jobs[job_id]["status"] = "running"
        if flask_app is not None:
            with flask_app.test_request_context("/_ariella_manual_background_scan"):
                result = runner()
        else:
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
    if not _manual_scan_lock.acquire(blocking=False):
        return None, (jsonify({
            "status": "busy",
            "message": "כבר מתבצעת סריקה ידנית. יש להמתין לסיומה."
        }), 409)
    job_id = uuid.uuid4().hex
    _manual_scan_jobs[job_id] = {
        "job_id": job_id, "label": label, "status": "starting", "result": None, "error": None,
    }
    # Capture the real Flask app while still inside the initiating request.
    # Background scan threads must never dereference Flask request/session proxies
    # after the HTTP request has returned.
    try:
        flask_app = app
    except Exception:
        flask_app = None
    thread = threading.Thread(
        target=_background_scan_worker,
        args=(job_id, label, runner, flask_app), daemon=True, name=f"ariella-{label}-{job_id[:8]}",
    )
    thread.start()
    return job_id, None

if SCHEDULER_ENABLED and os.getenv("WERKZEUG_RUN_MAIN") != "true":
    from scheduler import start_scheduler
    start_scheduler()


# Admin login (so the token no longer has to sit in ?token= URLs, which end
# up in Render's request logs). The login is its own signed cookie rather
# than a flag in the site-wide Flask session: it is SameSite=Strict, so a
# link or form on another site can never carry it - several admin actions
# are plain GETs (e.g. /admin/delete-member). Path "/" because the admin
# dashboard also calls protected routes outside /admin (/scan, /scan-stop...).
ADMIN_COOKIE = "ariella_admin"
ADMIN_SESSION_SECONDS = 12 * 60 * 60


def _admin_serializer():
    return URLSafeTimedSerializer(app.secret_key, salt="ariella-admin-session")


# Shaked's hardening (16.10): with the public default secret key anyone who
# reads the source could sign an admin cookie, so cookie login is off then.
_DEFAULT_SECRET_KEY = "change-this-before-production"


def _secret_key_is_default() -> bool:
    return not app.secret_key or app.secret_key == _DEFAULT_SECRET_KEY


# Failed /admin/login attempts per client IP (and in total), in memory:
# Render runs one gunicorn worker (threads share this dict). Only wrong codes
# count; while an IP is blocked even the right code is refused at the form
# (the X-Admin-Token header / ?token= still work), and a successful login
# clears that IP's failures.
ADMIN_LOGIN_MAX_FAILS_PER_IP = 5
ADMIN_LOGIN_MAX_FAILS_TOTAL = 50
ADMIN_LOGIN_WINDOW_SECONDS = 15 * 60
_admin_login_fails: dict[str, list[float]] = {}
_admin_login_lock = threading.Lock()


def _client_ip() -> str:
    # Behind Render's proxy remote_addr is the proxy; the LAST X-Forwarded-For
    # entry is the one the proxy itself appended (earlier ones can be forged).
    forwarded = [p.strip() for p in (request.headers.get("X-Forwarded-For") or "").split(",") if p.strip()]
    return forwarded[-1] if forwarded else (request.remote_addr or "unknown")


def _admin_login_blocked(ip: str) -> bool:
    cutoff = time.time() - ADMIN_LOGIN_WINDOW_SECONDS
    with _admin_login_lock:
        for key in list(_admin_login_fails):
            _admin_login_fails[key] = [t for t in _admin_login_fails[key] if t > cutoff]
            if not _admin_login_fails[key]:
                del _admin_login_fails[key]
        total = sum(len(v) for v in _admin_login_fails.values())
        return len(_admin_login_fails.get(ip, [])) >= ADMIN_LOGIN_MAX_FAILS_PER_IP or total >= ADMIN_LOGIN_MAX_FAILS_TOTAL


def _admin_login_record_failure(ip: str) -> None:
    with _admin_login_lock:
        _admin_login_fails.setdefault(ip, []).append(time.time())


def _admin_cookie_valid() -> bool:
    raw = request.cookies.get(ADMIN_COOKIE)
    if not raw or not ADMIN_TOKEN or _secret_key_is_default():
        return False
    try:
        data = _admin_serializer().loads(raw, max_age=ADMIN_SESSION_SECONDS)
    except (BadSignature, SignatureExpired):
        return False
    # Rotating ADMIN_TOKEN logs every existing admin session out.
    expected = hmac.new(ADMIN_TOKEN.encode(), b"admin-session", "sha256").hexdigest()
    return isinstance(data, dict) and data.get("is_admin") is True \
        and hmac.compare_digest(str(data.get("token_tag") or ""), expected)


def _authorized() -> bool:
    if not ADMIN_TOKEN:
        return True
    if _admin_cookie_valid():
        return True
    supplied = request.headers.get("X-Admin-Token") or request.args.get("token", "")
    return supplied == ADMIN_TOKEN


def _require_admin():
    if not _authorized():
        # A browser opening an admin page gets the login form instead of a
        # bare 401; API/script callers keep the 401 JSON exactly as before.
        if request.method == "GET" and request.accept_mimetypes.best == "text/html":
            return redirect("/admin/login?next=" + quote(request.path, safe="/"))
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    return None


_ADMIN_LOGIN_HTML = """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>אריאלה — כניסת מנהל</title><style>
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:16px;background:#f5f7fb;font-family:Arial,sans-serif;color:#182033}
form{width:min(380px,100%);background:#fff;padding:26px 22px;border-radius:14px;box-shadow:0 4px 24px #0000001a;display:flex;flex-direction:column;gap:12px}
h1{margin:0 0 4px;font-size:22px}input{padding:12px;font-size:16px;border:1px solid #d8dde6;border-radius:8px;direction:ltr}
button{padding:12px;font-size:16px;font-weight:800;border:0;border-radius:8px;background:#b8892e;color:#fff;cursor:pointer}
.err{color:#a12b2b;margin:0}</style></head><body>
<form method="post" action="/admin/login" autocomplete="off"><h1>כניסת מנהל</h1>
{error}<label for="token">קוד מנהל</label>
<input id="token" name="token" type="password" required autofocus>
<input type="hidden" name="next" value="{next}"><button type="submit">כניסה</button></form></body></html>"""


def _safe_admin_next(value) -> str:
    value = str(value or "")
    return value if value.startswith("/admin") and not value.startswith("/admin/login") and "//" not in value else "/admin"


def _admin_login_page(error="", next_path="/admin", status=200):
    body = _ADMIN_LOGIN_HTML.replace("{error}", f'<p class="err">{html.escape(error)}</p>' if error else "") \
        .replace("{next}", html.escape(_safe_admin_next(next_path)))
    resp = Response(body, status=status, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/admin/login")
def admin_login_form():
    if ADMIN_TOKEN and _admin_cookie_valid():
        return redirect(_safe_admin_next(request.args.get("next")))
    return _admin_login_page(next_path=request.args.get("next"))


@app.post("/admin/login")
def admin_login():
    next_path = _safe_admin_next(request.form.get("next"))
    if _secret_key_is_default():
        logging.warning("admin login refused: FLASK_SECRET_KEY is the public default")
        return _admin_login_page(
            "הכניסה כבויה: FLASK_SECRET_KEY לא הוגדר (ערך ברירת המחדל). יש להגדיר ערך סודי ב-Render.",
            next_path, status=503)
    ip = _client_ip()
    if _admin_login_blocked(ip):
        logging.warning("admin login rate-limited ip=%s", ip)
        resp = _admin_login_page("יותר מדי ניסיונות שגויים. נסו שוב בעוד 15 דקות.", next_path, status=429)
        resp.headers["Retry-After"] = str(ADMIN_LOGIN_WINDOW_SECONDS)
        return resp
    supplied = str(request.form.get("token") or "")
    if not ADMIN_TOKEN or not hmac.compare_digest(supplied.encode(), ADMIN_TOKEN.encode()):
        _admin_login_record_failure(ip)
        return _admin_login_page("קוד שגוי", next_path, status=401)
    with _admin_login_lock:
        _admin_login_fails.pop(ip, None)
    tag = hmac.new(ADMIN_TOKEN.encode(), b"admin-session", "sha256").hexdigest()
    resp = redirect(next_path)
    resp.set_cookie(
        ADMIN_COOKIE, _admin_serializer().dumps({"is_admin": True, "token_tag": tag}),
        max_age=ADMIN_SESSION_SECONDS, path="/", httponly=True, samesite="Strict",
        secure=request.is_secure or bool(os.getenv("RENDER")),
    )
    return resp


@app.route("/admin/logout", methods=["GET", "POST"])
def admin_logout():
    resp = redirect("/admin/login")
    resp.delete_cookie(ADMIN_COOKIE, path="/", httponly=True, samesite="Strict",
                       secure=request.is_secure or bool(os.getenv("RENDER")))
    return resp


def _detect_gunicorn_config():
    """Read the gunicorn worker's ACTUAL resolved --timeout/--threads,
    as gunicorn/conf.py's post_worker_init hook recorded them into this
    exact worker process's own environment right after gunicorn finished
    computing them (worker.cfg.timeout/worker.cfg.threads) - never
    re-derived from a command line.

    Per Shaked's PR #69 review (stage-2 run-4 502 investigation): an
    earlier version of this function scanned /proc/*/cmdline instead, and
    had two separate problems she caught by actually running the exact
    command render.yaml specifies and testing against it. (1) gunicorn is
    itself a Python script, so a PROCESS's cmdline[0] is the interpreter
    path ("/usr/bin/python3"), not "gunicorn" - the old check ("gunicorn"
    not in cmdline[0]) always skipped the real master process, and the
    test's own mocked /proc data started directly with "gunicorn"
    (unrealistic), hiding exactly this bug. (2) even fixed, a value set
    via GUNICORN_CMD_ARGS, a short "-t"/"-w" flag, or a gunicorn.conf.py
    setting never appears as a literal "--timeout"/"--threads" substring
    in the command line at all - the function would have silently
    reported the code's own hardcoded fallback (30/1) as if it were the
    real value, exactly backwards on the one question this field exists
    to answer.

    gunicorn's own post_worker_init hook runs in this same worker process
    after gunicorn has already resolved the real values from WHATEVER
    source actually set them (CLI flag, env var, or config file) - there
    is no more authoritative place to read them from. Requires gunicorn
    to actually be invoked with --config gunicorn.conf.py (or -c) for the
    hook to ever run; under the Flask dev server, or gunicorn invoked
    without that flag, the two env vars are simply never set, and this
    correctly reports (None, None) rather than guessing. Deliberately
    returns only the two parsed integers, never a raw command line, a
    file path, or any other environment variable. Any failure (bad/
    missing env var, anything unexpected) is reported as (None, None) -
    this must never be the reason /health itself fails."""
    def _parse_int(raw):
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None
    return (
        _parse_int(os.getenv("ARIELLA_GUNICORN_TIMEOUT")),
        _parse_int(os.getenv("ARIELLA_GUNICORN_THREADS")),
    )


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
    try:
        gunicorn_timeout, gunicorn_threads = _detect_gunicorn_config()
    except Exception:
        gunicorn_timeout, gunicorn_threads = None, None
    return jsonify({
        "status": "ok" if db_ok else "degraded", "version": APP_VERSION,
        "commit": _DEPLOYED_COMMIT, "deployed_at": _STARTED_AT,
        "serpapi_configured": bool(os.getenv("SERPAPI_API_KEY")),
        "scheduler_enabled": SCHEDULER_ENABLED, "database_ok": db_ok,
        "database_error": db_error, "database_path": str(DB_PATH),
        "database_persistent_path": str(DB_PATH).startswith("/var/data/"),
        "minimum_score": MIN_DEAL_SCORE, "maximum_daily_deals": MAX_DAILY_DEALS,
        "admin_protected": bool(ADMIN_TOKEN), "whatsapp": whatsapp_status(),
        "gunicorn_timeout": gunicorn_timeout, "gunicorn_threads": gunicorn_threads,
        "public_base_url_warning": PUBLIC_BASE_URL_WARNING,
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


@app.post("/admin/toggle-duplicate-guard")
def toggle_duplicate_guard():
    """Temporarily disable the anti-abuse duplicate-active-trip guard
    (public_site._find_duplicate_active_trip) so the same route/dates can be
    re-approved repeatedly while manually testing. Re-enable before real
    customers use the site."""
    denied = _require_admin()
    if denied:
        return denied
    current = str(get_setting("duplicate_trip_guard_disabled", "0") or "0") == "1"
    set_setting("duplicate_trip_guard_disabled", "0" if current else "1")
    supplied = request.args.get("token") or ""
    return redirect("/admin" + (("?token=" + supplied) if supplied else ""))


@app.post("/admin/confirm-payment")
def admin_confirm_payment():
    """Manual stand-in for a payment processor's success webhook. Until a real
    gateway (Isracard or otherwise) is connected, this is the only way a
    personal-search payment (19/39 ILS) turns from 'pending' into an active
    34-day tracking period - for testing the flow end to end. A real
    gateway's callback will call the exact same public_site._confirm_paid_search
    function; nothing else about the flow needs to change when that happens."""
    denied = _require_admin()
    if denied:
        return denied
    trip_id = request.form.get("trip_id", type=int) or request.args.get("trip_id", type=int)
    if not trip_id:
        return jsonify({"status": "error", "message": "missing trip_id"}), 400
    ok = _confirm_paid_search(trip_id, provider="manual_admin")
    if not ok:
        return jsonify({"status": "error", "message": "no pending payment for this trip"}), 404
    supplied = request.args.get("token") or request.form.get("token") or ""
    if request.form.get("redirect") == "admin":
        return redirect("/admin" + (("?token=" + supplied) if supplied else ""))
    return jsonify({"status": "success", "trip_id": trip_id})


@app.post("/admin/rematch-trip")
def admin_rematch_trip():
    """Recovery action for a vacation stuck frozen on an empty matched-offers
    list (per the business owner's directive, 20.10, vacation 259/trip
    #158) - re-runs the matching chain against CURRENT inventory, with no
    new paid scan. Only acts on a trip whose search already finished with
    nothing pinned; see public_site.rematch_trip_without_new_scan for the
    full guard and the four-tier fallback chain it reuses from the scan
    worker itself."""
    denied = _require_admin()
    if denied:
        return denied
    trip_id = request.form.get("trip_id", type=int) or request.args.get("trip_id", type=int)
    if not trip_id:
        return jsonify({"status": "error", "message": "missing trip_id"}), 400
    result = rematch_trip_without_new_scan(trip_id)
    supplied = request.args.get("token") or request.form.get("token") or ""
    if request.form.get("redirect") == "admin":
        return redirect("/admin" + (("?token=" + supplied) if supplied else ""))
    return jsonify(result), (200 if result.get("status") == "success" else 400)


@app.post("/admin/confirm-whatsapp-payment")
def admin_confirm_whatsapp_payment():
    """Manual stand-in for a payment processor's success webhook for the
    one-time ₪9 WhatsApp deals product - same role as /admin/confirm-payment
    above, for whatsapp_deals_9 instead of the personal-search plans. A real
    gateway's callback will call the exact same
    whatsapp_deals_messages.on_whatsapp_deals_paid function."""
    denied = _require_admin()
    if denied:
        return denied
    member_id = request.form.get("member_id", type=int) or request.args.get("member_id", type=int)
    if not member_id:
        return jsonify({"status": "error", "message": "missing member_id"}), 400
    changed = on_whatsapp_deals_paid(member_id)
    return jsonify({"status": "success", "member_id": member_id, "opt_in_changed": changed})


@app.get("/admin")
def admin_dashboard():
    denied = _require_admin()
    if denied:
        return denied
    return render_dashboard(
        version=APP_VERSION, minimum_score=MIN_DEAL_SCORE,
        stats=dashboard_stats(MIN_DEAL_SCORE), offers=recent_offers(500),
        scans=recent_scan_runs(20), feedback_count=unread_feedback_count(),
        test_mode=str(get_setting("qa_test_mode", "0") or "0") == "1",
        duplicate_guard_disabled=str(get_setting("duplicate_trip_guard_disabled", "0") or "0") == "1",
        token=request.args.get("token", ""),
    )


@app.get("/admin/scans")
def admin_scans():
    denied = _require_admin()
    if denied:
        return denied
    return render_dashboard(
        version=APP_VERSION, minimum_score=MIN_DEAL_SCORE,
        stats=dashboard_stats(MIN_DEAL_SCORE), offers=[],
        scans=recent_scan_runs(100), feedback_count=unread_feedback_count(),
        test_mode=str(get_setting("qa_test_mode", "0") or "0") == "1",
        duplicate_guard_disabled=str(get_setting("duplicate_trip_guard_disabled", "0") or "0") == "1",
        token=request.args.get("token", ""), page="scans",
    )


@app.get("/admin/analytics")
def admin_analytics():
    denied = _require_admin()
    if denied: return denied
    return render_analytics_dashboard(version=APP_VERSION, analytics=business_analytics(12), token=request.args.get("token", ""))


@app.get("/admin/feedback")
def admin_feedback():
    denied = _require_admin()
    if denied: return denied
    feedback = recent_feedback(500)
    mark_feedback_seen()
    return render_feedback_dashboard(feedback=feedback, token=request.args.get("token", ""))


@app.get("/admin/hfa-routes")
def admin_hfa_routes():
    """Task 011a: the Haifa (Air Haifa) destination list with verified_at."""
    denied = _require_admin()
    if denied: return denied
    from hfa_routes import load_routes
    return render_hfa_routes_dashboard(routes=load_routes(), token=request.args.get("token", ""))


@app.get("/admin/ai-usage")
def admin_ai_usage():
    denied = _require_admin()
    if denied: return denied
    days = request.args.get("days", 30, type=int)
    include_test = request.args.get("include_test", "0") == "1"
    return jsonify({"status": "success", **usage_summary(days=days, include_test=include_test)})


@app.get("/admin/ai-usage.csv")
def admin_ai_usage_csv():
    denied = _require_admin()
    if denied: return denied
    import csv
    import io
    days = request.args.get("days", 30, type=int)
    include_test = request.args.get("include_test", "0") == "1"
    rows = usage_rows(days=days, include_test=include_test)
    buffer = io.StringIO()
    columns = [
        "id", "created_at", "source", "member_id", "trip_id", "conversation_id", "model",
        "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
        "is_test", "error", "estimated_cost_usd", "thread_id", "call_started_at", "call_duration_ms",
    ]
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return Response(buffer.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": f"attachment; filename=ai-usage-{days}d.csv"
    })


@app.get("/admin/ai-usage/conversation/<int:conversation_id>")
def admin_ai_usage_conversation(conversation_id):
    denied = _require_admin()
    if denied: return denied
    rows = usage_for_conversation(conversation_id)
    return jsonify({"status": "success", "conversation_id": conversation_id, "count": len(rows), "calls": rows})


@app.get("/admin/ai-usage/diagnostics.csv")
def admin_ai_usage_diagnostics_csv():
    """Per Shlomo's follow-up (18.10, qa/reports/2026-10-18-stage3-run4.md):
    a plain logging.info call for a live-site diagnostic (the reset-
    confirmation gate, the guided-redirect mismatch) has no value on this
    infrastructure - no agent has access to Render's own log stream. These
    events are recorded instead via record_diagnostic_event (see
    ai_usage.py), as ai_usage rows excluded from every cost total, and
    exported here so the business owner can download them and Shaked can
    analyze them - never the customer's own message text, by construction
    of every caller. ?event= selects one of DIAGNOSTIC_EVENT_SOURCES."""
    denied = _require_admin()
    if denied: return denied
    import csv
    import io
    event = request.args.get("event", "").strip()
    if event not in DIAGNOSTIC_EVENT_SOURCES:
        return jsonify({
            "status": "error",
            "message": f"?event= must be one of {list(DIAGNOSTIC_EVENT_SOURCES)}",
        }), 400
    days = request.args.get("days", 30, type=int)
    include_test = request.args.get("include_test", "0") == "1"
    rows = diagnostic_rows(event, days=days, include_test=include_test)
    buffer = io.StringIO()
    columns = ["id", "created_at", "member_id", "conversation_id", "details"]
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return Response(buffer.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": f"attachment; filename=ai-usage-diagnostics-{event}-{days}d.csv"
    })


@app.get("/admin/whatsapp-queue")
def admin_whatsapp_queue():
    denied = _require_admin()
    if denied: return denied
    import json as _json
    rows = recent_whatsapp_queue(request.args.get("limit", 50, type=int))
    for row in rows:
        try:
            row["buttons"] = _json.loads(row.get("buttons_json") or "[]")
        except Exception:
            row["buttons"] = []
    return jsonify({"status": "success", "count": len(rows), "queue": rows})


@app.get("/admin/whatsapp-inbox")
def admin_whatsapp_inbox():
    """Task 006a: the last 50 (default) whatsapp_inbound_log rows,
    in/out, for debugging the inbound Ariella bridge."""
    denied = _require_admin()
    if denied: return denied
    rows = recent_whatsapp_inbound_log(request.args.get("limit", 50, type=int))
    return jsonify({"status": "success", "count": len(rows), "messages": rows})


@app.get("/admin/whatsapp-subscription")
def admin_whatsapp_subscription():
    """Task 006b: checks whether this app is subscribed to the WABA's
    messages webhook - read-only by default; ?apply=1 also subscribes it if
    not already subscribed. Never returns WHATSAPP_ACCESS_TOKEN."""
    denied = _require_admin()
    if denied: return denied
    apply = request.args.get("apply", "0") == "1"
    result = whatsapp_subscription_check(apply=apply)
    return jsonify({"status": "success", **result})


@app.get("/admin/whatsapp-number/request-code")
def admin_whatsapp_number_request_code():
    """Task 006c step 1: sends a verification SMS/voice code to the number -
    only with ?confirm=1 (otherwise just explains what would happen, since
    the business owner operates this from her phone)."""
    denied = _require_admin()
    if denied: return denied
    method = request.args.get("method", "SMS")
    confirm = request.args.get("confirm", "0") == "1"
    result = whatsapp_request_code(method=method, confirm=confirm)
    return jsonify({"status": "success", **result})


@app.get("/admin/whatsapp-number/verify-code")
def admin_whatsapp_number_verify_code():
    """Task 006c step 2: verifies the code Meta sent in step 1."""
    denied = _require_admin()
    if denied: return denied
    code = request.args.get("code", "")
    confirm = request.args.get("confirm", "0") == "1"
    result = whatsapp_verify_code(code, confirm=confirm)
    return jsonify({"status": "success", **result})


@app.get("/admin/whatsapp-number/register")
def admin_whatsapp_number_register():
    """Task 006c step 3: registers the verified number directly on the Cloud
    API using WHATSAPP_REGISTRATION_PIN. Never returns the PIN or the
    access token."""
    denied = _require_admin()
    if denied: return denied
    confirm = request.args.get("confirm", "0") == "1"
    result = whatsapp_register_number(confirm=confirm)
    return jsonify({"status": "success", **result})


@app.post("/admin/cj-sync")
def admin_cj_sync():
    denied = _require_admin()
    if denied: return denied
    result = sync_cj_commissions(days_back=request.args.get("days_back", 7, type=int))
    return jsonify({"status": "success", **result})


@app.get("/admin/cj-check")
def admin_cj_check():
    """Task 001b: read-only CJ connection/field-name check, openable as a
    plain GET link from a phone browser - unlike /admin/cj-sync above (POST,
    and a no-op while CJ_COMMISSIONS_SYNC_ENABLED is false). Never writes to
    partner_commissions and never queues a message; see
    partner_commissions.cj_connection_check for the full behavior."""
    denied = _require_admin()
    if denied: return denied
    result = cj_connection_check(days_back=request.args.get("days_back", 31, type=int))
    return jsonify(result)


@app.get("/admin/mail-check")
def admin_mail_check():
    """Read-only config check, openable as a plain GET link; pass ?to=<email>
    to also attempt one real send and see the exact SMTP error if it fails,
    since mailer.send_email() itself only logs and never raises."""
    denied = _require_admin()
    if denied: return denied
    result = mail_check(test_to=request.args.get("to"))
    return jsonify(result)


@app.get("/admin/delete-member")
def admin_delete_member():
    """Admin equivalent of the customer-facing /account/delete (task 008 QA,
    bug 8) - for a support/ops case the customer can't self-serve (e.g. they
    lost access to their own account), and for cleaning up test accounts.
    GET with ?member_id=<id> or ?email=<email> only explains what would be
    deleted; ?confirm=1 actually deletes. Matches the read-by-default,
    explicit-confirm pattern already used by /admin/whatsapp-number/*."""
    denied = _require_admin()
    if denied: return denied
    member_id = request.args.get("member_id", type=int)
    email = (request.args.get("email") or "").strip().lower()
    if not member_id and not email:
        return jsonify({"status": "error", "message": "נדרש member_id או email."}), 400
    with connection() as conn:
        if member_id:
            row = conn.execute("SELECT id, email, full_name FROM members WHERE id=?", (member_id,)).fetchone()
        else:
            row = conn.execute("SELECT id, email, full_name FROM members WHERE lower(email)=?", (email,)).fetchone()
    if not row:
        return jsonify({"status": "error", "message": "לא נמצא חשבון תואם."}), 404
    confirm = request.args.get("confirm", "0") == "1"
    if not confirm:
        return jsonify({
            "status": "success", "would_delete": True, "applied": False,
            "member_id": row["id"], "email": row["email"], "full_name": row["full_name"],
        })
    delete_member_account(row["id"])
    return jsonify({"status": "success", "applied": True, "member_id": row["id"]})


@app.get("/admin/partner-commissions")
def admin_partner_commissions():
    denied = _require_admin()
    if denied: return denied
    rows = recent_partner_commissions(request.args.get("limit", 50, type=int))
    return jsonify({"status": "success", "count": len(rows), "commissions": rows})


@app.get("/admin/scan-sharing")
def admin_scan_sharing():
    """Task 007a: measurement only, read-only - see database.scan_sharing_stats."""
    denied = _require_admin()
    if denied: return denied
    days = request.args.get("days", 30, type=int)
    return jsonify({"status": "success", **scan_sharing_stats(days=days)})


@app.get("/admin/scan-sharing/history")
def admin_scan_sharing_history():
    """Task 007a: one-off retrospective report over existing scan_runs/
    monthly_scan_coverage history - see tools/report_scan_sharing_history.py
    for exactly what it computes and its documented approximations."""
    denied = _require_admin()
    if denied: return denied
    from tools.report_scan_sharing_history import generate_report
    return jsonify({"status": "success", **generate_report()})


@app.get("/offers-preview")
def offers_preview():
    denied = _require_admin()
    if denied: return denied
    limit = request.args.get("limit", 50, type=int)
    minimum_score = request.args.get("minimum_score", type=int)
    offers = recent_offers(limit=limit, minimum_score=minimum_score)
    return jsonify({"status": "success", "count": len(offers), "minimum_deal_score": MIN_DEAL_SCORE, "offers": offers})


@app.get("/feedback-preview")
def feedback_preview():
    denied = _require_admin()
    if denied: return denied
    messages = recent_feedback(request.args.get("limit", 100, type=int))
    return jsonify({"status": "success", "count": len(messages), "messages": messages})


@app.get("/scan-history")
def scan_history():
    denied = _require_admin()
    if denied: return denied
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
        return jsonify({"status": "accepted", "job_id": job_id,"destinations": max_destinations}), 202
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


# NOTE: /whatsapp-webhook used to be registered here too (duplicate of the
# implementation in whatsapp.py, attached to the `site` blueprint). Having
# two handlers for the same path/methods is ambiguous routing and only one
# was ever actually reachable. Removed so there is exactly one WhatsApp
# webhook implementation (whatsapp.py: whatsapp_webhook, on the `site`
# blueprint). To adapt/extend behavior, edit whatsapp.py directly.


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
