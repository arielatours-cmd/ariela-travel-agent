import json
import sqlite3
import smtplib
from email.message import EmailMessage
from functools import wraps

from flask import (
    Blueprint, flash, redirect, render_template, request, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash

from config import (
    DB_PATH, FEEDBACK_TO_EMAIL, MAIL_APP_PASSWORD, MAIL_SMTP_HOST,
    MAIL_SMTP_PORT, MAIL_USERNAME,
)
from database import (
    mark_feedback_email_result, recent_offers, save_feedback, utc_now_iso,
)


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
        if not session.get("member_id"):
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


def _send_feedback_email(
    full_name: str, email: str, phone: str, message: str
) -> None:
    if not MAIL_USERNAME or not MAIL_APP_PASSWORD:
        raise RuntimeError(
            "MAIL_USERNAME או MAIL_APP_PASSWORD אינם מוגדרים ב-Render."
        )

    mail = EmailMessage()
    mail["Subject"] = f"משוב חדש באתר אריאלה — {full_name}"
    mail["From"] = MAIL_USERNAME
    mail["To"] = FEEDBACK_TO_EMAIL
    mail["Reply-To"] = email
    mail.set_content(
        "התקבל משוב חדש באתר אריאלה\n\n"
        f"שם מלא: {full_name}\n"
        f"אימייל: {email}\n"
        f"טלפון: {phone}\n\n"
        "הודעה:\n"
        f"{message}\n"
    )

    with smtplib.SMTP_SSL(
        MAIL_SMTP_HOST, MAIL_SMTP_PORT, timeout=20
    ) as smtp:
        smtp.login(MAIL_USERNAME, MAIL_APP_PASSWORD)
        smtp.send_message(mail)


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

    feedback_id = save_feedback(full_name, email, phone, message)

    try:
        _send_feedback_email(full_name, email, phone, message)
        mark_feedback_email_result(feedback_id, "sent")
    except Exception as exc:
        # The message is still safely stored in the database.
        mark_feedback_email_result(feedback_id, "failed", str(exc)[:1000])

    flash(
        "תודה! קיבלנו את ההצעה שלכם. "
        "כל רעיון נקרא ועוזר לנו להמשיך לשפר את אריאלה.",
        "success",
    )
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
        flash("ברוכים הבאים לאריאלה. החשבון נוצר בהצלחה.", "success")
        return redirect(url_for("site.account"))

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
    member = _current_member()
    with _db() as conn:
        rows = conn.execute(
            """SELECT id, request_name, travel_window, status, created_at
               FROM trip_requests
               WHERE member_id=?
               ORDER BY id DESC""",
            (member["id"],),
        ).fetchall()
    return render_template(
        "account.html", member=member, trips=[dict(row) for row in rows]
    )


@site.route("/trip/new", methods=["GET", "POST"])
@login_required
def new_trip():
    if request.method == "POST":
        form = request.form
        request_name = form.get("request_name", "").strip() or "הטיול הבא שלי"
        date_mode = form.get("date_mode", "month")
        travel_window = (
            form.get("travel_month", "").strip()
            if date_mode == "month"
            else f'{form.get("departure_date", "")} – {form.get("return_date", "")}'
        )

        payload = {
            "travel_party": form.getlist("travel_party"),
            "adults": form.get("adults"),
            "children": form.get("children"),
            "age_groups": form.getlist("age_groups"),
            "date_mode": date_mode,
            "travel_month": form.get("travel_month"),
            "departure_date": form.get("departure_date"),
            "return_date": form.get("return_date"),
            "date_flexibility": form.get("date_flexibility"),
            "minimum_nights": form.get("minimum_nights"),
            "maximum_nights": form.get("maximum_nights"),
            "holiday_styles": form.getlist("holiday_styles"),
            "top_priorities": form.getlist("top_priorities"),
            "destination_mode": form.get("destination_mode"),
            "destinations": form.get("destinations"),
            "flight_budget_pp": form.get("flight_budget_pp"),
            "total_budget": form.get("total_budget"),
            "budget_flexibility": form.get("budget_flexibility"),
            "flight_preferences": form.getlist("flight_preferences"),
            "baggage": form.getlist("baggage"),
            "hotel_needed": form.get("hotel_needed"),
            "hotel_preferences": form.getlist("hotel_preferences"),
            "attractions_needed": form.get("attractions_needed"),
            "attraction_types": form.getlist("attraction_types"),
            "special_needs": form.getlist("special_needs"),
            "notes": form.get("notes"),
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

        flash(
            "בקשת הטיול נשמרה. מנגנון ההתאמה האישית יחובר למנוע הדילים בשלב הבא.",
            "success",
        )
        return redirect(url_for("site.account"))

    return render_template("trip_form.html")


@site.get("/privacy")
def privacy():
    return render_template("privacy.html")


@site.get("/terms")
def terms():
    return render_template("terms.html")
