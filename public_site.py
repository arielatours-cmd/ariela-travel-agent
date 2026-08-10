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


site = Blueprint("site", __name__)


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


def _offer_matches_trip(offer, trip):
    answers = trip.get("answers", {})
    destinations = (answers.get("destinations") or "").strip().lower()
    if destinations:
        offer_destination = " ".join([
            str(offer.get("destination_name") or ""),
            str(offer.get("arrival_code") or ""),
            str(offer.get("route") or ""),
        ]).lower()
        destination_terms = [x.strip() for x in destinations.replace("/", ",").split(",") if x.strip()]
        if destination_terms and not any(term in offer_destination for term in destination_terms):
            return False

    date_mode = answers.get("date_mode")
    outbound = str(offer.get("outbound_date") or "")
    inbound = str(offer.get("return_date") or "")
    if date_mode == "exact":
        departure_date = answers.get("departure_date") or ""
        return_date = answers.get("return_date") or ""
        if departure_date and outbound and outbound < departure_date:
            return False
        if return_date and inbound and inbound > return_date:
            return False
    elif date_mode == "month":
        month = answers.get("travel_month") or ""
        if month and outbound and not outbound.startswith(month):
            return False

    budget_mode = answers.get("budget_mode")
    budget_amount = answers.get("budget_amount")
    if budget_mode == "per_person" and budget_amount:
        try:
            if float(offer.get("price_ils") or 0) > float(budget_amount):
                return False
        except (TypeError, ValueError):
            pass
    return True


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
    offers = recent_offers(limit=3, minimum_score=None)
    return render_template("home.html", offers=offers)


@site.get("/deals")
def deals():
    offers = recent_offers(limit=60, minimum_score=None)
    personal_trips = []
    if session.get("member_id") and _current_member() is not None:
        with _db() as conn:
            _expire_finished_trips(conn, session["member_id"])
            rows = conn.execute(
                "SELECT * FROM trip_requests WHERE member_id=? ORDER BY id DESC",
                (session["member_id"],),
            ).fetchall()
            conn.commit()
        for row in rows:
            trip = _trip_dict(row)
            trip["offers"] = [offer for offer in offers if _offer_matches_trip(offer, trip)]
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


@site.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with _db() as conn:
            row = conn.execute("SELECT id,password_hash FROM members WHERE email=? AND status='active'", (email,)).fetchone()
        if not row or not check_password_hash(row["password_hash"], password):
            flash("כתובת הדוא״ל או הסיסמה אינם נכונים.", "error")
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
    return render_template(
        "account.html", member=dict(member_row), trips=[_trip_dict(row) for row in rows],
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
                "UPDATE trip_requests SET status=?, mobile_notifications=CASE WHEN ?='ended' THEN 0 ELSE mobile_notifications END, ended_at=? WHERE id=?",
                (new_status, new_status, utc_now_iso() if new_status == "ended" else None, trip_id),
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


@site.get("/terms")
def terms():
    return render_template("terms.html")
