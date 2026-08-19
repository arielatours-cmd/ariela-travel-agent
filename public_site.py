from pathlib import Path
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from datetime import date, datetime
from functools import wraps

from flask import (
    Blueprint, flash, redirect, render_template, request, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash

from config import DB_PATH
from database import recent_offers, save_feedback, utc_now_iso
from scanner import run_customer_trip_search


site = Blueprint("site", __name__)

_AIRPORTS_FILE = Path(__file__).resolve().parent / "static" / "airports.json"
try:
    _AIRPORT_LOCALIZATION = {
        row["code"]: row for row in json.loads(_AIRPORTS_FILE.read_text(encoding="utf-8"))
    }
except Exception:
    _AIRPORT_LOCALIZATION = {}

def _localize_offer_airports(offer: dict) -> dict:
    dep = _AIRPORT_LOCALIZATION.get(offer.get("departure_code"), {})
    arr = _AIRPORT_LOCALIZATION.get(offer.get("arrival_code"), {})
    offer["departure_city_he"] = dep.get("city_he") or offer.get("departure_airport_name") or offer.get("departure_code")
    offer["departure_city_en"] = dep.get("city_en") or offer.get("departure_code")
    offer["departure_name_he"] = dep.get("name_he") or offer["departure_city_he"]
    offer["departure_name_en"] = dep.get("name_en") or offer["departure_city_en"]
    offer["arrival_city_he"] = arr.get("city_he") or offer.get("destination_name") or offer.get("arrival_airport_name") or offer.get("arrival_code")
    offer["arrival_city_en"] = arr.get("city_en") or offer.get("arrival_code")
    offer["arrival_name_he"] = arr.get("name_he") or offer["arrival_city_he"]
    offer["arrival_name_en"] = arr.get("name_en") or offer["arrival_city_en"]
    return offer



def _db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _current_member():
    member_id = session.get("member_id")
    if not member_id:
        return None
    with _db() as conn:
        row = conn.execute(
            "SELECT id, full_name, email, phone, country, preferred_airports, created_at FROM members WHERE id=?",
            (member_id,),
        ).fetchone()
    
    if not row:
        return None
    member = dict(row)
    try:
        member["preferred_airports_list"] = json.loads(member.get("preferred_airports") or "[]")
    except (TypeError, json.JSONDecodeError):
        member["preferred_airports_list"] = []

    # Country-based defaults for a new vacation. Explicit member preferences win.
    country_key = str(member.get("country") or "").strip().lower()
    country_defaults = {
        "israel": ["TLV", "HFA"],
        "ישראל": ["TLV", "HFA"],
        "il": ["TLV", "HFA"],
    }
    member["vacation_default_airports"] = (
        member["preferred_airports_list"]
        if member["preferred_airports_list"]
        else country_defaults.get(country_key, [])
    )
    return member


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("member_id") or _current_member() is None:
            session.pop("member_id", None)
            return redirect(url_for("site.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def _trip_dict(row):
    trip = dict(row)
    try:
        trip["answers"] = json.loads(trip.get("answers_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        trip["answers"] = {}
    return trip


def _expire_finished_trips(conn, member_id):
    today = date.today().isoformat()
    rows = conn.execute(
        "SELECT id, answers_json FROM trip_requests WHERE member_id=? AND status='active'",
        (member_id,),
    ).fetchall()
    for row in rows:
        try:
            answers = json.loads(row["answers_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        return_date = (answers.get("return_date") or "").strip()
        if return_date and return_date < today:
            conn.execute(
                "UPDATE trip_requests SET status='ended', mobile_notifications=0, ended_at=? WHERE id=?",
                (utc_now_iso(), row["id"]),
            )


def _trip_destination_terms(trip):
    destinations = str((trip.get("answers") or {}).get("destinations") or "").strip().lower()
    if not destinations:
        return []
    aliases = {
        "רומא": ["רומא", "rome", "fco", "cia"],
        "rome": ["רומא", "rome", "fco", "cia"],
        "אתונה": ["אתונה", "athens", "ath"],
        "athens": ["אתונה", "athens", "ath"],
        "בודפשט": ["בודפשט", "budapest", "bud"],
        "budapest": ["בודפשט", "budapest", "bud"],
        "פראג": ["פראג", "prague", "prg"],
        "prague": ["פראג", "prague", "prg"],
        "וינה": ["וינה", "vienna", "vie"],
        "vienna": ["וינה", "vienna", "vie"],
        "מילאנו": ["מילאנו", "milan", "mxp", "bgy", "lin"],
        "milan": ["מילאנו", "milan", "mxp", "bgy", "lin"],
    }
    raw = [x.strip() for x in destinations.replace("/", ",").split(",") if x.strip()]
    terms = []
    for term in raw:
        terms.extend(aliases.get(term, [term]))
    return list(dict.fromkeys(terms))


def _offer_destination_matches(offer, trip):
    terms = _trip_destination_terms(trip)
    if not terms:
        return True
    haystack = " ".join([
        str(offer.get("destination_name") or ""),
        str(offer.get("arrival_code") or ""),
        str(offer.get("route") or ""),
        str(offer.get("arrival_city_he") or ""),
        str(offer.get("arrival_city_en") or ""),
    ]).lower()
    return any(term in haystack for term in terms)


def _trip_requested_month(trip):
    answers = trip.get("answers") or {}
    if answers.get("date_mode") == "month":
        return str(answers.get("travel_month") or "")[:7]
    if answers.get("date_mode") == "exact":
        return str(answers.get("departure_date") or "")[:7]
    return ""


def _offer_matches_trip(offer, trip, *, exact_dates=False, same_month=False):
    answers = trip.get("answers", {})
    if not _offer_destination_matches(offer, trip):
        return False

    origin_airports = [str(x).upper() for x in (answers.get("origin_airports") or []) if x]
    if origin_airports and str(offer.get("departure_code") or "").upper() not in origin_airports:
        return False

    outbound = str(offer.get("outbound_date") or "")
    inbound = str(offer.get("return_date") or "")
    if exact_dates and answers.get("date_mode") == "exact":
        if outbound != str(answers.get("departure_date") or ""):
            return False
        if inbound != str(answers.get("return_date") or ""):
            return False
    elif same_month:
        month = _trip_requested_month(trip)
        if month and not outbound.startswith(month):
            return False
    elif answers.get("date_mode") == "month":
        month = str(answers.get("travel_month") or "")
        if month and outbound and not outbound.startswith(month):
            return False

    budget_mode = answers.get("budget_mode")
    budget_amount = answers.get("budget_amount")
    if budget_mode == "per_person" and budget_amount:
        try:
            # Alternatives may be slightly above the user's target; do not hide a
            # materially better schedule for a tiny overage. Exact matches stay strict.
            multiplier = 1.0 if exact_dates else 1.10
            if float(offer.get("price_ils") or 0) > float(budget_amount) * multiplier:
                return False
        except (TypeError, ValueError):
            pass
    return True


def _offer_signature(offer):
    return (
        offer.get("departure_code"), offer.get("arrival_code"),
        offer.get("outbound_date"), offer.get("return_date"),
        offer.get("airline"), offer.get("departure_time"),
        offer.get("return_airline"), offer.get("return_departure_time"),
    )


def _customer_deal_choices(all_offers, trip, limit=5):
    """Database-first selection: exact request first, then valuable same-month alternatives."""
    # Never surface weak inventory merely because it exists.
    qualified = [o for o in all_offers if int(o.get("score") or 0) >= 65]

    exact = [o for o in qualified if _offer_matches_trip(o, trip, exact_dates=True)]
    same_month = [o for o in qualified if _offer_matches_trip(o, trip, same_month=True)]

    exact.sort(key=lambda o: (-int(o.get("score") or 0), float(o.get("price_ils") or 10**9)))
    same_month.sort(key=lambda o: (-int(o.get("score") or 0), float(o.get("price_ils") or 10**9)))

    selected = []
    seen = set()

    def add(offer, label_he, label_en):
        sig = _offer_signature(offer)
        if sig in seen or len(selected) >= limit:
            return
        copy = dict(offer)
        copy["customer_choice_label_he"] = label_he
        copy["customer_choice_label_en"] = label_en
        selected.append(copy)
        seen.add(sig)

    # 1. Ariella's best match to the exact request.
    if exact:
        add(exact[0], "הבחירה של אריאלה", "Ariella's choice")

    # Candidate pool excludes the exact winner but can include other exact options.
    pool = [o for o in same_month if _offer_signature(o) not in seen]

    # 2. Cheapest worthwhile option.
    if pool:
        cheapest = min(pool, key=lambda o: (float(o.get("price_ils") or 10**9), -int(o.get("score") or 0)))
        add(cheapest, "הכי משתלם", "Best value")

    # 3. Best usable-time/schedule option using the combined score already calculated.
    pool2 = [o for o in pool if _offer_signature(o) not in seen]
    if pool2:
        best_time = max(pool2, key=lambda o: (int(o.get("time_value_score") or 0), int(o.get("score") or 0)))
        add(best_time, "הכי הרבה זמן ביעד", "Most time at destination")

    # 4. Strongest different-date option in the same month.
    pool3 = [o for o in pool2 if _offer_signature(o) not in seen]
    answers = trip.get("answers") or {}
    requested_out = str(answers.get("departure_date") or "")
    different = [o for o in pool3 if not requested_out or str(o.get("outbound_date") or "") != requested_out]
    if different:
        add(different[0], "שווה לשקול תאריכים אחרים", "Worth considering different dates")

    # 5. Fill only with other qualified, non-duplicate options.
    for offer in pool3:
        add(offer, "אפשרות נוספת ששווה לשקול", "Another option worth considering")

    # If the user chose a month rather than exact dates, the top ranked option is the choice.
    if not exact and selected:
        selected[0]["customer_choice_label_he"] = "הבחירה של אריאלה"
        selected[0]["customer_choice_label_en"] = "Ariella's choice"

    return selected[:limit]


@site.app_context_processor
def inject_site_context():
    requested_lang = request.args.get("lang")
    if requested_lang in {"he", "en"}:
        session["lang"] = requested_lang

    # Hebrew is the default for every new visitor/session.
    lang = session.get("lang", "he")
    if lang not in {"he", "en"}:
        lang = "he"
        session["lang"] = "he"

    return {"current_member": _current_member(), "site_lang": lang}


def _lang():
    requested_lang = request.args.get("lang")
    if requested_lang in {"he", "en"}:
        session["lang"] = requested_lang
    lang = session.get("lang", "he")
    return lang if lang in {"he", "en"} else "he"


def _msg(he, en):
    return en if _lang() == "en" else he


@site.get("/")
def home():
    requested_lang = request.args.get("lang")
    if requested_lang == "en":
        session["lang"] = "en"
    else:
        # Bare site URL and ?lang=he always open the Hebrew homepage.
        session["lang"] = "he"

    offers = recent_offers(limit=3, minimum_score=None)
    return render_template("home.html", offers=offers)


@site.get("/deals")
def deals():
    offers = [_localize_offer_airports(o) for o in recent_offers(limit=60, minimum_score=None)]
    personal_trips = []
    if session.get("member_id") and _current_member() is not None:
        with _db() as conn:
            _expire_finished_trips(conn, session["member_id"])
            rows = conn.execute(
                "SELECT * FROM trip_requests WHERE member_id=? ORDER BY id DESC",
                (session["member_id"],),
            ).fetchall()
            conn.commit()
        # Database first: include a deeper recent inventory than the public general-deals list.
        database_offers = [_localize_offer_airports(o) for o in recent_offers(limit=500, minimum_score=None)]
        for row in rows:
            trip = _trip_dict(row)
            trip["offers"] = _customer_deal_choices(database_offers, trip, limit=5)
            trip["database_match_found"] = bool(trip["offers"])
            trip["needs_fresh_search"] = not bool(trip["offers"])
            personal_trips.append(trip)
    return render_template("deals.html", offers=offers, personal_trips=personal_trips)


@site.get("/about")
def about():
    return render_template("about.html")


@site.get("/feedback")
def feedback_form():
    return render_template("feedback.html")


@site.post("/feedback")
def feedback():
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    message = request.form.get("message", "").strip()
    website = request.form.get("website", "").strip()
    if website:
        return redirect(url_for("site.feedback_form", sent="1"))
    if not full_name or not email or not phone or not message:
        flash(_msg("יש למלא את כל הפרטים לפני השליחה.", "Please complete all fields before sending."), "error")
        return redirect(url_for("site.feedback_form"))
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        flash(_msg("כתובת האימייל אינה תקינה.", "The email address is invalid."), "error")
        return redirect(url_for("site.feedback_form"))
    if len(full_name) > 120 or len(email) > 254 or len(phone) > 40:
        flash(_msg("אחד הפרטים שהוזנו ארוך מדי.", "One of the entered details is too long."), "error")
        return redirect(url_for("site.feedback_form"))
    if len(message) < 5 or len(message) > 5000:
        flash(_msg("ההודעה צריכה להכיל בין 5 ל-5,000 תווים.", "The message must contain between 5 and 5,000 characters."), "error")
        return redirect(url_for("site.feedback_form"))
    save_feedback(full_name, email, phone, message)
    return redirect(url_for("site.feedback_form", sent="1"))


@site.route("/join", methods=["GET", "POST"])
def join():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        country = request.form.get("country", "").strip().upper()
        preferred_airports = [x.strip().upper() for x in request.form.get("preferred_airports", "").replace(";", ",").split(",") if x.strip()]
        password = request.form.get("password", "")
        consent = request.form.get("consent") == "yes"
        if not full_name or not email or not password or not preferred_airports:
            flash(_msg("יש למלא שם, כתובת דוא״ל, סיסמה ולבחור לפחות שדה תעופה אחד.", "Please enter your name, email address, password and select at least one departure airport."), "error")
            return render_template("join.html")
        if len(password) < 8:
            flash(_msg("הסיסמה צריכה להכיל לפחות 8 תווים.", "The password must contain at least 8 characters."), "error")
            return render_template("join.html")
        if not consent:
            flash(_msg("יש לאשר את תנאי השימוש ומדיניות הפרטיות.", "Please accept the Terms of Use and Privacy Policy."), "error")
            return render_template("join.html")

        with _db() as conn:
            email_match = conn.execute("SELECT 1 FROM members WHERE email=?", (email,)).fetchone()
            phone_match = conn.execute("SELECT 1 FROM members WHERE phone=? AND phone<>''", (phone,)).fetchone() if phone else None
            if email_match or phone_match:
                if email_match and phone_match:
                    flash(_msg("כבר קיים חשבון עם כתובת הדוא״ל ומספר הטלפון האלה.", "An account already exists with this email address and phone number."), "error")
                elif email_match:
                    flash(_msg("כבר קיים חשבון עם כתובת הדוא״ל הזאת.", "An account already exists with this email address."), "error")
                else:
                    flash(_msg("כבר קיים חשבון עם מספר הטלפון הזה.", "An account already exists with this phone number."), "error")
                return render_template("join.html", duplicate_account=True)
            cur = conn.execute(
                "INSERT INTO members (full_name,email,phone,password_hash,created_at,status,country,preferred_airports) VALUES(?,?,?,?,?,?,?,?)",
                (full_name, email, phone, generate_password_hash(password), utc_now_iso(), "active", country, json.dumps(preferred_airports)),
            )
            member_id = int(cur.lastrowid)
            conn.commit()
        session["member_id"] = member_id
        return redirect(url_for("site.account", welcome="1"))
    return render_template("join.html")



@site.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    site_lang = _site_lang()
    message = None
    reset_link = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        # Always show the same response so account existence is not disclosed.
        message = ("If an account exists for this email, password reset instructions have been prepared."
                   if site_lang == "en" else
                   "אם קיים חשבון עם כתובת האימייל הזו, הוכנו הוראות לאיפוס הסיסמה.")
        with _db() as conn:
            member = conn.execute("SELECT id FROM members WHERE lower(email)=?", (email,)).fetchone()
            if member:
                raw = secrets.token_urlsafe(32)
                token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                now = datetime.now(timezone.utc)
                expires = now + timedelta(minutes=30)
                conn.execute("UPDATE password_reset_tokens SET used_at=? WHERE member_id=? AND used_at IS NULL",
                             (now.isoformat(), member["id"]))
                conn.execute("""INSERT INTO password_reset_tokens
                                (member_id,token_hash,created_at,expires_at)
                                VALUES (?,?,?,?)""",
                             (member["id"], token_hash, now.isoformat(), expires.isoformat()))
                conn.commit()
                # No email provider is connected yet. Keep the token server-side and
                # do not expose it in production UI. Email delivery will use this URL later.
                if current_app.config.get("DEBUG"):
                    reset_link = url_for("site.reset_password", token=raw, lang=site_lang, _external=True)
    return render_template("forgot_password.html", site_lang=site_lang, message=message, reset_link=reset_link)

@site.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    site_lang = _site_lang()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    error = None
    with _db() as conn:
        row = conn.execute("""SELECT prt.id,prt.member_id,prt.expires_at,prt.used_at
                              FROM password_reset_tokens prt
                              WHERE prt.token_hash=?""", (token_hash,)).fetchone()
    valid = False
    if row and not row["used_at"]:
        try:
            valid = datetime.fromisoformat(row["expires_at"]) > datetime.now(timezone.utc)
        except Exception:
            valid = False
    if request.method == "POST" and valid:
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(password) < 8:
            error = "Password must contain at least 8 characters." if site_lang == "en" else "הסיסמה חייבת להכיל לפחות 8 תווים."
        elif password != confirm:
            error = "Passwords do not match." if site_lang == "en" else "הסיסמאות אינן תואמות."
        else:
            with _db() as conn:
                conn.execute("UPDATE members SET password_hash=? WHERE id=?",
                             (generate_password_hash(password), row["member_id"]))
                conn.execute("UPDATE password_reset_tokens SET used_at=? WHERE id=?",
                             (datetime.now(timezone.utc).isoformat(), row["id"]))
                conn.commit()
            return redirect(url_for("site.login", lang=site_lang, reset="success"))
    return render_template("reset_password.html", site_lang=site_lang, valid=valid, error=error)


@site.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with _db() as conn:
            row = conn.execute("SELECT id,password_hash FROM members WHERE email=? AND status='active'", (email,)).fetchone()
        if not row or not check_password_hash(row["password_hash"], password):
            flash("The email address or password is incorrect." if _lang() == "en" else "כתובת הדוא״ל או הסיסמה אינם נכונים.", "error")
            return render_template("login.html")
        session["member_id"] = int(row["id"])
        next_url = request.args.get("next")
        return redirect(next_url or url_for("site.account"))
    return render_template("login.html")


@site.post("/logout")
def logout():
    session.clear()
    flash("התנתקת מהחשבון.", "info")
    return redirect(url_for("site.home"))


@site.route("/account/details", methods=["GET", "POST"])
@login_required
def account_details():
    member_id = session["member_id"]
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        country = request.form.get("country", "").strip().upper()
        preferred_airports = [x.strip().upper() for x in request.form.get("preferred_airports", "").replace(";", ",").split(",") if x.strip()]
        if not full_name or not email or not preferred_airports:
            flash(_msg("יש למלא שם, כתובת דוא״ל ולבחור לפחות שדה תעופה אחד.", "Please enter your name, email address and select at least one departure airport."), "error")
        else:
            with _db() as conn:
                email_match = conn.execute("SELECT id FROM members WHERE email=? AND id<>?", (email, member_id)).fetchone()
                phone_match = conn.execute("SELECT id FROM members WHERE phone=? AND phone<>'' AND id<>?", (phone, member_id)).fetchone() if phone else None
                if email_match:
                    flash("כתובת הדוא״ל הזו כבר משויכת לחשבון אחר.", "error")
                elif phone_match:
                    flash("מספר הטלפון הזה כבר משויך לחשבון אחר.", "error")
                else:
                    conn.execute("UPDATE members SET full_name=?, email=?, phone=?, country=?, preferred_airports=? WHERE id=?", (full_name, email, phone, country, json.dumps(preferred_airports), member_id))
                    conn.commit()
                    flash("פרטי החשבון עודכנו בהצלחה.", "success")
                    return redirect(url_for("site.account_details"))
    member = _current_member()
    return render_template("account_details.html", member=member)


@site.get("/account")
@login_required
def account():
    member_id = session["member_id"]
    with _db() as conn:
        member_row = conn.execute(
            "SELECT id, full_name, email, phone, country, preferred_airports, created_at FROM members WHERE id=? AND status='active'",
            (member_id,),
        ).fetchone()
        if member_row is None:
            session.pop("member_id", None)
            return redirect(url_for("site.login", next=request.path))
        _expire_finished_trips(conn, member_id)
        rows = conn.execute("SELECT * FROM trip_requests WHERE member_id=? ORDER BY id DESC", (member_id,)).fetchall()
        conn.commit()
    trips = [_trip_dict(row) for row in rows]
    database_offers = [_localize_offer_airports(o) for o in recent_offers(limit=500, minimum_score=None)]
    for trip in trips:
        trip["offers"] = _customer_deal_choices(database_offers, trip, limit=5)
    return render_template(
        "account.html", member=dict(member_row), trips=trips,
        welcome=request.args.get("welcome") == "1",
    )


@site.post("/trip/<int:trip_id>/toggle-search")
@login_required
def toggle_trip_search(trip_id):
    with _db() as conn:
        row = conn.execute("SELECT status FROM trip_requests WHERE id=? AND member_id=?", (trip_id, session["member_id"])).fetchone()
        if row:
            new_status = "ended" if row["status"] == "active" else "active"
            conn.execute(
                "UPDATE trip_requests SET status=?, mobile_notifications=CASE WHEN ?='ended' THEN 0 ELSE mobile_notifications END, ended_at=?, subscription_cancel_at_period_end=CASE WHEN ?='ended' AND subscription_status='active' THEN 1 ELSE subscription_cancel_at_period_end END WHERE id=?",
                (new_status, new_status, utc_now_iso() if new_status == "ended" else None, new_status, trip_id),
            )
            conn.commit()
    return redirect(url_for("site.account"))


@site.post("/trip/<int:trip_id>/toggle-notifications")
@login_required
def toggle_trip_notifications(trip_id):
    with _db() as conn:
        row = conn.execute("SELECT status,mobile_notifications FROM trip_requests WHERE id=? AND member_id=?", (trip_id, session["member_id"])).fetchone()
        if row and row["status"] == "active":
            conn.execute("UPDATE trip_requests SET mobile_notifications=? WHERE id=?", (0 if row["mobile_notifications"] else 1, trip_id))
            conn.commit()
    return redirect(url_for("site.account"))




@site.post("/trip/<int:trip_id>/search-now")
@login_required
def search_trip_now(trip_id):
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM trip_requests WHERE id=? AND member_id=? AND status='active'",
            (trip_id, session["member_id"]),
        ).fetchone()
    if row is None:
        return redirect(url_for("site.deals") + "#personalDeals")
    trip = _trip_dict(row)

    # Check the database again immediately before spending API quota.
    database_offers = [_localize_offer_airports(o) for o in recent_offers(limit=500, minimum_score=None)]
    if _customer_deal_choices(database_offers, trip, limit=5):
        flash(_msg("מצאתי דילים מתאימים במאגר — לא בוצעה סריקת אינטרנט נוספת.", "Suitable database deals were found — no extra web scan was used."), "success")
        return redirect(url_for("site.deals") + f"#vacation-{trip_id}")

    result = run_customer_trip_search(trip_id, trip.get("answers") or {})
    if result.get("offers_found"):
        flash(_msg("הסריקה הסתיימה ונמצאו אפשרויות חדשות לחופשה.", "The scan finished and new vacation options were found."), "success")
    else:
        flash(_msg("הסריקה הסתיימה, אך עדיין לא נמצא דיל שעובר את סף האיכות.", "The scan finished, but no deal passed Ariella's quality threshold yet."), "info")
    return redirect(url_for("site.deals") + f"#vacation-{trip_id}")


@site.post("/trip/<int:trip_id>/renew-search")
@login_required
def renew_trip_search(trip_id):
    plan = request.form.get("plan", "").strip()
    allowed = {"calm", "daily", "intensive"}
    if plan not in allowed:
        return redirect(url_for("site.account"))
    with _db() as conn:
        row = conn.execute(
            "SELECT id,status FROM trip_requests WHERE id=? AND member_id=?",
            (trip_id, session["member_id"]),
        ).fetchone()
        if row and row["status"] == "active":
            conn.execute(
                "UPDATE trip_requests SET subscription_plan=?, subscription_status='pending', renewal_reminder_sent_at=NULL WHERE id=?",
                (plan, trip_id),
            )
            conn.commit()
    # Isracard checkout will replace this pending step. Each purchase is one-time only.\n    # After confirmed payment, the paid search period will be set to 34 days from payment date\n    # (one month + the 4-day early-renewal window). No automatic renewal or recurring charge.
    return redirect(url_for("site.account", payment="pending", trip_id=trip_id))


@site.route("/trip/new", methods=["GET", "POST"])
@login_required
def new_trip():
    if request.method == "POST":
        form = request.form
        destination_mode = form.get("destination_mode", "open")
        destinations = form.get("destinations", "").strip()
        date_mode = form.get("date_mode", "anytime")
        travel_month = form.get("travel_month", "").strip()
        departure_date = form.get("departure_date", "").strip()
        return_date = form.get("return_date", "").strip()
        today = date.today().isoformat()
        current_month = today[:7]

        if destination_mode in {"specific", "several"} and not destinations:
            flash(_msg("יש לכתוב את היעד או היעדים שמעניינים אתכם.", "Please enter the destination or destinations you are interested in."), "error")
            return render_template("trip_form.html", today=today, current_month=current_month)
        if date_mode == "month" and (not travel_month or travel_month < current_month):
            flash(_msg("יש לבחור חודש נוכחי או עתידי.", "Please choose the current month or a future month."), "error")
            return render_template("trip_form.html", today=today, current_month=current_month)
        if date_mode == "exact":
            if not departure_date or not return_date:
                flash(_msg("יש לבחור תאריך יציאה ותאריך חזרה.", "Please choose a departure date and a return date."), "error")
                return render_template("trip_form.html", today=today, current_month=current_month)
            if departure_date < today:
                flash(_msg("ניתן לבחור תאריכים מהיום והלאה בלבד.", "You can only choose dates from today onward."), "error")
                return render_template("trip_form.html", today=today, current_month=current_month)
            if return_date <= departure_date:
                flash(_msg("תאריך החזרה חייב להיות אחרי תאריך היציאה.", "The return date must be after the departure date."), "error")
                return render_template("trip_form.html", today=today, current_month=current_month)

        destination_title = destinations if destinations else _msg("הצעות של אריאלה", "Ariella suggestions")
        if date_mode == "month":
            travel_window = travel_month
        elif date_mode == "exact":
            travel_window = f"{departure_date} – {return_date}"
        else:
            travel_window = _msg("כל השנה", "Anytime")
        request_name = destination_title

        travel_party = form.get("travel_party")
        adults = form.get("family_adults") if travel_party in {"family", "extended"} else form.get("adults")
        if travel_party == "solo": adults = "1"
        elif travel_party == "couple": adults = "2"

        budget_mode = form.get("budget_mode")
        if budget_mode not in {"per_person", "unlimited"}:
            budget_mode = "unlimited"

        member = _current_member() or {}
        profile_airports = member.get("preferred_airports_list", [])
        override_airports = [x.strip().upper() for x in form.get("origin_airports", "").replace(";", ",").split(",") if x.strip()]
        origin_airports = override_airports or profile_airports

        payload = {
            "origin_airports": origin_airports,
            "destination_mode": destination_mode, "destinations": destinations,
            "date_mode": date_mode, "travel_month": travel_month,
            "departure_date": departure_date, "return_date": return_date,
            "travel_party": travel_party, "adults": adults,
            "children": form.get("children"), "age_groups": form.getlist("age_groups"),
            "holiday_priorities": form.getlist("holiday_priorities"),
            "budget_mode": budget_mode,
            "budget_amount": form.get("budget_amount") if budget_mode == "per_person" else "",
            "special_needs": form.getlist("special_needs"), "notes": form.get("notes", "").strip(),
        }
        with _db() as conn:
            conn.execute(
                "INSERT INTO trip_requests (member_id,request_name,travel_window,status,answers_json,created_at,mobile_notifications) VALUES(?,?,?,?,?,?,?)",
                (session["member_id"], request_name, travel_window, "active", json.dumps(payload, ensure_ascii=False), utc_now_iso(), 0),
            )
            conn.commit()
        return redirect(url_for("site.account"))

    today = date.today().isoformat()
    return render_template("trip_form.html", today=today, current_month=today[:7])


@site.get("/privacy")
def privacy():
    return render_template("privacy.html")


@site.get("/cookies")
def cookies():
    return render_template("cookies.html")

@site.get("/affiliate-disclosure")
def affiliates():
    return render_template("affiliates.html")

@site.get("/accessibility")
def accessibility():
    return render_template("accessibility.html")

@site.get("/contact")
def contact():
    return render_template("contact.html")

@site.get("/terms")
def terms():
    return render_template("terms.html")
