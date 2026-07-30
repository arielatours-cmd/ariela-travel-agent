import json
import sqlite3
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
            "SELECT id, full_name, email, phone, created_at FROM members WHERE id=?",
            (member_id,),
        ).fetchone()
    return dict(row) if row else None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        # A session can outlive the database row after a redeploy/reset.
        # Validate the member itself, not only the session key, so /account
        # never crashes when an old/stale session is present.
        if not session.get("member_id") or _current_member() is None:
            session.pop("member_id", None)
            flash("כדי להמשיך יש להתחבר לחשבון.", "info")
            return redirect(url_for("site.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@site.app_context_processor
def inject_site_context():
    return {"current_member": _current_member()}


@site.get("/")
def home():
    offers = recent_offers(limit=3, minimum_score=None)
    return render_template("home.html", offers=offers)


@site.get("/deals")
def deals():
    offers = recent_offers(limit=60, minimum_score=None)
    return render_template("deals.html", offers=offers)


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

    # Invisible anti-spam field. A normal visitor never fills it.
    if website:
        return redirect(url_for("site.feedback_form", sent="1"))

    if not full_name or not email or not phone or not message:
        flash("יש למלא את כל הפרטים לפני השליחה.", "error")
        return redirect(url_for("site.feedback_form"))

    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        flash("כתובת האימייל אינה תקינה.", "error")
        return redirect(url_for("site.feedback_form"))

    if len(full_name) > 120 or len(email) > 254 or len(phone) > 40:
        flash("אחד הפרטים שהוזנו ארוך מדי.", "error")
        return redirect(url_for("site.feedback_form"))

    if len(message) < 5 or len(message) > 5000:
        flash("ההודעה צריכה להכיל בין 5 ל-5,000 תווים.", "error")
        return redirect(url_for("site.feedback_form"))

    save_feedback(full_name, email, phone, message)
    return redirect(url_for("site.feedback_form", sent="1"))


@site.route("/join", methods=["GET", "POST"])
def join():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        consent = request.form.get("consent") == "yes"

        if not full_name or not email or not password:
            flash("יש למלא שם, כתובת דוא״ל וסיסמה.", "error")
            return render_template("join.html")
        if len(password) < 8:
            flash("הסיסמה צריכה להכיל לפחות 8 תווים.", "error")
            return render_template("join.html")
        if not consent:
            flash("יש לאשר את תנאי השימוש ומדיניות הפרטיות.", "error")
            return render_template("join.html")

        try:
            with _db() as conn:
                cur = conn.execute(
                    """INSERT INTO members
                       (full_name,email,phone,password_hash,created_at,status)
                       VALUES(?,?,?,?,?,?)""",
                    (
                        full_name, email, phone,
                        generate_password_hash(password),
                        utc_now_iso(), "active",
                    ),
                )
                member_id = int(cur.lastrowid)
                conn.commit()
        except sqlite3.IntegrityError:
            flash("כבר קיים חשבון עם כתובת הדוא״ל הזאת.", "error")
            return render_template("join.html")

        session["member_id"] = member_id
        return redirect(url_for("site.account", welcome="1"))

    return render_template("join.html")


@site.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with _db() as conn:
            row = conn.execute(
                "SELECT id,password_hash FROM members WHERE email=? AND status='active'",
                (email,),
            ).fetchone()

        if not row or not check_password_hash(row["password_hash"], password):
            flash("כתובת הדוא״ל או הסיסמה אינם נכונים.", "error")
            return render_template("login.html")

        session["member_id"] = int(row["id"])
        flash("התחברת בהצלחה.", "success")
        next_url = request.args.get("next")
        return redirect(next_url or url_for("site.account"))

    return render_template("login.html")


@site.post("/logout")
def logout():
    session.clear()
    flash("התנתקת מהחשבון.", "info")
    return redirect(url_for("site.home"))


@site.get("/account")
@login_required
def account():
    member_id = session.get("member_id")
    if not member_id:
        return redirect(url_for("site.login", next=request.path))

    with _db() as conn:
        member_row = conn.execute(
            "SELECT id, full_name, email, phone, created_at FROM members WHERE id=? AND status='active'",
            (member_id,),
        ).fetchone()

        if member_row is None:
            session.pop("member_id", None)
            return redirect(url_for("site.login", next=request.path))

        rows = conn.execute(
            """SELECT id, request_name, travel_window, status, created_at
               FROM trip_requests
               WHERE member_id=?
               ORDER BY id DESC""",
            (int(member_row["id"]),),
        ).fetchall()

    member = dict(member_row)
    return render_template(
        "account.html",
        member=member,
        trips=[dict(row) for row in rows],
        welcome=request.args.get("welcome") == "1",
    )


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

        if destination_mode in {"specific", "several"} and not destinations:
            flash("יש לכתוב את היעד או היעדים שמעניינים אתכם.", "error")
            return render_template("trip_form.html")
        if date_mode == "month" and not travel_month:
            flash("יש לבחור חודש מועדף.", "error")
            return render_template("trip_form.html")
        if date_mode == "exact" and (not departure_date or not return_date):
            flash("יש לבחור תאריך יציאה ותאריך חזרה.", "error")
            return render_template("trip_form.html")

        destination_title = destinations if destinations else "הצעות של אריאלה"
        if date_mode == "month":
            date_title = travel_month
            travel_window = travel_month
        elif date_mode == "exact":
            date_title = f"{departure_date}–{return_date}"
            travel_window = f"{departure_date} – {return_date}"
        else:
            date_title = "תאריכים גמישים"
            travel_window = "כל השנה"
        request_name = f"{destination_title} • {date_title}"

        travel_party = form.get("travel_party")
        adults = form.get("family_adults") if travel_party in {"family", "extended"} else form.get("adults")
        if travel_party == "solo":
            adults = "1"
        elif travel_party == "couple":
            adults = "2"

        payload = {
            "destination_mode": destination_mode,
            "destinations": destinations,
            "date_mode": date_mode,
            "travel_month": travel_month,
            "departure_date": departure_date,
            "return_date": return_date,
            "travel_party": travel_party,
            "adults": adults,
            "children": form.get("children"),
            "age_groups": form.getlist("age_groups"),
            "holiday_priorities": form.getlist("holiday_priorities"),
            "budget_mode": form.get("budget_mode"),
            "budget_amount": form.get("budget_amount"),
            "special_needs": form.getlist("special_needs"),
            "notes": form.get("notes", "").strip(),
        }

        with _db() as conn:
            conn.execute(
                """INSERT INTO trip_requests
                   (member_id,request_name,travel_window,status,answers_json,created_at)
                   VALUES(?,?,?,?,?,?)""",
                (
                    session["member_id"], request_name, travel_window,
                    "active", json.dumps(payload, ensure_ascii=False), utc_now_iso(),
                ),
            )
            conn.commit()

        flash("החופשה נשמרה בהצלחה.", "success")
        return redirect(url_for("site.account"))

    return render_template("trip_form.html")


@site.get("/privacy")
def privacy():
    return render_template("privacy.html")


@site.get("/terms")
def terms():
    return render_template("terms.html")
