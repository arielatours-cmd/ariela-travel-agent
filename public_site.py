from pathlib import Path
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import requests
from urllib.parse import parse_qsl
from datetime import date, datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (
    Blueprint, flash, redirect, render_template, request, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash

from config import DB_PATH, MIN_DEAL_SCORE, ISRAEL_TZ, SERPAPI_API_KEY
from database import recent_offers, save_feedback, utc_now_iso, record_site_event, record_booking_click, DESTINATION_LANDMARK_IMAGES, get_setting
from scanner import run_customer_trip_search



site = Blueprint("site", __name__)

def _public_deal_threshold():
    """Production stays at MIN_DEAL_SCORE; QA test mode can temporarily expose 65+."""
    enabled = str(get_setting("qa_test_mode", "0") or "0") == "1"
    return 65 if enabled else MIN_DEAL_SCORE

@site.before_request
def _track_public_visit():
    """Count one unique browser visit per day without storing IP addresses."""
    if request.method != "GET":
        return
    visitor_id = session.get("_ariella_visitor_id")
    if not visitor_id:
        visitor_id = uuid.uuid4().hex
        session["_ariella_visitor_id"] = visitor_id
    today_key = date.today().isoformat()
    if session.get("_ariella_visit_day") != today_key:
        record_site_event(
            "site_visit",
            visitor_id=visitor_id,
            member_id=session.get("member_id"),
            path=request.path,
        )
        session["_ariella_visit_day"] = today_key

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
            "SELECT id, full_name, email, phone, country, preferred_airports, created_at, whatsapp_opt_in, whatsapp_opt_in_at FROM members WHERE id=?",
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


def _trip_destination_codes(trip):
    """Return the exact destination airport codes chosen by the customer."""
    raw = str((trip.get("answers") or {}).get("destinations") or "").strip()
    if not raw:
        return set()

    # The airport picker stores IATA codes. Keep city-name aliases only for
    # older saved requests created before the airport picker was introduced.
    aliases = {
        "רומא": {"FCO", "CIA"}, "rome": {"FCO", "CIA"},
        "מילאנו": {"MXP", "BGY", "LIN"}, "milan": {"MXP", "BGY", "LIN"},
        "אתונה": {"ATH"}, "athens": {"ATH"},
        "בודפשט": {"BUD"}, "budapest": {"BUD"},
        "פראג": {"PRG"}, "prague": {"PRG"},
        "וינה": {"VIE"}, "vienna": {"VIE"},
        "סופיה": {"SOF"}, "sofia": {"SOF"},
        "לרנקה": {"LCA"}, "larnaca": {"LCA"},
        "פאפוס": {"PFO"}, "paphos": {"PFO"},
        "בוקרשט": {"OTP"}, "bucharest": {"OTP"},
    }

    codes = set()
    for token in [x.strip() for x in raw.replace("/", ",").replace(";", ",").split(",") if x.strip()]:
        upper = token.upper()
        if len(upper) == 3 and upper.isalpha():
            codes.add(upper)
        else:
            codes.update(aliases.get(token.lower(), set()))
    return codes


def _offer_destination_matches(offer, trip):
    """Personal-vacation results must be for the requested destination only."""
    requested = _trip_destination_codes(trip)
    if not requested:
        return True
    return str(offer.get("arrival_code") or "").upper() in requested


def _offer_has_complete_roundtrip(offer):
    """Do not show partial/legacy records as a personal vacation deal."""
    required = (
        offer.get("outbound_date"),
        offer.get("return_date"),
        offer.get("departure_time"),
        offer.get("arrival_time"),
        offer.get("return_departure_time"),
        offer.get("return_arrival_time"),
    )
    return all(bool(v) for v in required)


def _offer_has_baggage_pricing_when_needed(offer):
    """If trolley/checked bag is not included, require a usable round-trip estimate."""
    baggage = offer.get("baggage") or {}

    def priced_or_included(key):
        item = baggage.get(key) or {}
        if item.get("included"):
            return True
        return isinstance(item.get("roundtrip_price_ils"), (int, float)) or isinstance(item.get("price_each_way"), (int, float))

    return priced_or_included("carry_on_8kg") and priced_or_included("checked_bag_23kg")


def _trip_requested_month(trip):
    answers = trip.get("answers") or {}
    if answers.get("date_mode") == "month":
        return str(answers.get("outbound_month") or answers.get("travel_month") or "")[:7]
    if answers.get("date_mode") == "exact":
        return str(answers.get("departure_date") or "")[:7]
    return ""

def _trip_requested_return_month(trip):
    answers = trip.get("answers") or {}
    if answers.get("date_mode") == "month":
        return str(answers.get("return_month") or answers.get("outbound_month") or answers.get("travel_month") or "")[:7]
    if answers.get("date_mode") == "exact":
        return str(answers.get("return_date") or "")[:7]
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
        return_month = _trip_requested_return_month(trip)
        if month and not outbound.startswith(month):
            return False
        if return_month and not inbound.startswith(return_month):
            return False
    elif answers.get("date_mode") == "month":
        month = str(answers.get("outbound_month") or answers.get("travel_month") or "")
        return_month = str(answers.get("return_month") or month or "")
        if month and outbound and not outbound.startswith(month):
            return False
        if return_month and inbound and not inbound.startswith(return_month):
            return False

    # Budget is a preference, not a hard exclusion. A strong match may be shown
    # above the requested amount; ranking and the UI make the overage transparent.
    return True


def _offer_signature(offer):
    return (
        offer.get("departure_code"), offer.get("arrival_code"),
        offer.get("outbound_date"), offer.get("return_date"),
        offer.get("airline"), offer.get("departure_time"),
        offer.get("return_airline"), offer.get("return_departure_time"),
    )


def _trip_is_destination_led(trip):
    """True when the customer already chose one or more destinations."""
    return str((trip.get("answers") or {}).get("destination_mode") or "open") in {"specific", "several"}


def _offer_seen_at(offer):
    for key in ("last_seen_at", "scan_started_at", "observed_at"):
        raw = offer.get(key)
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def _offer_is_recent(offer, max_age_hours=48):
    seen = _offer_seen_at(offer)
    if seen is None:
        return False
    return seen >= datetime.now(timezone.utc) - timedelta(hours=max_age_hours)


def _customer_rank_value(offer, trip):
    """Rank customer results differently from global deal discovery.

    When the customer already chose the destination, schedule/route/baggage fit is
    more important than whether the fare is an unusually cheap global 'deal'.
    Open searches keep the original deal score as the main signal.
    """
    deal_score = int(offer.get("score") or 0)
    answers = trip.get("answers") or {}
    budget_penalty = 0.0
    if answers.get("budget_mode") == "per_person" and answers.get("budget_amount"):
        try:
            budget = float(answers.get("budget_amount"))
            price_now = float(offer.get("price_ils") or 0)
            if budget > 0 and price_now > budget:
                # Gentle penalty: enough to prefer an in-budget equivalent, but not
                # enough to hide a materially better itinerary.
                budget_penalty = min(18.0, ((price_now - budget) / budget) * 35.0)
        except (TypeError, ValueError):
            pass

    if not _trip_is_destination_led(trip):
        return deal_score - budget_penalty

    route = int(offer.get("route_score") or 0)
    time_value = int(offer.get("time_value_score") or offer.get("hours_score") or 0)
    baggage = int(offer.get("baggage_score") or 0)
    price = int(offer.get("cost_score") or 0)
    rarity = int(offer.get("rarity_score") or 0)
    return (route * 2.0) + (time_value * 2.0) + (baggage * 1.5) + (price * 0.5) + (rarity * 0.25) - budget_penalty


def _customer_inventory_status(all_offers, trip):
    """Describe what already exists in DB without exposing incomplete records as deals."""
    same_destination = [
        o for o in all_offers
        if _offer_is_recent(o, 48)
        and _offer_destination_matches(o, trip)
        and (_trip_is_destination_led(trip) or int(o.get("score") or 0) >= 65)
    ]
    complete = [
        o for o in same_destination
        if _offer_has_complete_roundtrip(o) and _offer_has_baggage_pricing_when_needed(o)
    ]
    return {
        "same_destination_count": len(same_destination),
        "complete_count": len(complete),
        "has_incomplete_inventory": bool(same_destination) and not bool(complete),
    }


def _saved_match_offer_ids(trip):
    answers = trip.get("answers") or {}
    raw = answers.get("_matched_offer_ids") or []
    out = []
    for value in raw:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            pass
    return out


def _resolved_trip_offers(all_offers, trip, limit=5):
    """Use the exact DB offers that stopped the initial scan, then fresh dynamic matches.

    This prevents the UI from saying "database match" and then hiding the same offer
    when My Vacations is rendered again.
    """
    selected = []
    seen = set()

    pinned_ids = _saved_match_offer_ids(trip)
    if pinned_ids:
        by_id = {int(o.get("offer_id")): o for o in all_offers if o.get("offer_id") is not None}
        for oid in pinned_ids:
            offer = by_id.get(oid)
            if not offer or not _offer_is_recent(offer, 48):
                continue
            copy = dict(offer)
            copy["customer_choice_label_he"] = "הבחירה של אריאלה"
            copy["customer_choice_label_en"] = "Ariella's choice"
            sig = _offer_signature(copy)
            if sig not in seen:
                selected.append(copy)
                seen.add(sig)
            if len(selected) >= limit:
                return selected

    # Fresh offers produced specifically for this trip are also authoritative.
    try:
        trip_id = int(trip.get("id"))
    except (TypeError, ValueError):
        trip_id = None
    if trip_id is not None:
        for offer in all_offers:
            try:
                belongs = int(offer.get("trip_id")) == trip_id
            except (TypeError, ValueError):
                belongs = False
            if not belongs or not _offer_is_recent(offer, 48) or not _offer_has_complete_roundtrip(offer):
                continue
            copy = dict(offer)
            copy["customer_choice_label_he"] = "הבחירה של אריאלה"
            copy["customer_choice_label_en"] = "Ariella's choice"
            sig = _offer_signature(copy)
            if sig not in seen:
                selected.append(copy)
                seen.add(sig)
            if len(selected) >= limit:
                return selected

    for offer in _customer_deal_choices(all_offers, trip, limit=limit):
        sig = _offer_signature(offer)
        if sig in seen:
            continue
        selected.append(offer)
        seen.add(sig)
        if len(selected) >= limit:
            break
    return selected


def _customer_deal_choices(all_offers, trip, limit=5):
    """Database-first selection: exact request first, then valuable same-month alternatives."""
    # Destination-led searches are not blocked by the global deal-score threshold.
    # If the customer chose where to fly, relevance to that trip matters first.
    destination_led = _trip_is_destination_led(trip)
    qualified = [
        o for o in all_offers
        if _offer_is_recent(o, 48)
        and (destination_led or int(o.get("score") or 0) >= 65)
        and _offer_destination_matches(o, trip)
        and _offer_has_complete_roundtrip(o)
        and (destination_led or _offer_has_baggage_pricing_when_needed(o))
    ]

    exact = [o for o in qualified if _offer_matches_trip(o, trip, exact_dates=True)]
    same_month = [o for o in qualified if _offer_matches_trip(o, trip, same_month=True)]

    exact.sort(key=lambda o: (-_customer_rank_value(o, trip), float(o.get("price_ils") or 10**9)))
    same_month.sort(key=lambda o: (-_customer_rank_value(o, trip), float(o.get("price_ils") or 10**9)))

    selected = []
    seen = set()

    def add(offer, label_he, label_en):
        sig = _offer_signature(offer)
        if sig in seen or len(selected) >= limit:
            return
        copy = dict(offer)
        copy["customer_choice_label_he"] = label_he
        copy["customer_choice_label_en"] = label_en
        answers = trip.get("answers") or {}
        if answers.get("budget_mode") == "per_person" and answers.get("budget_amount"):
            try:
                budget = float(answers.get("budget_amount"))
                price_now = float(copy.get("price_ils") or 0)
                if budget > 0 and price_now > budget:
                    copy["budget_overage_ils"] = round(price_now - budget)
            except (TypeError, ValueError):
                pass
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

    offers = recent_offers(limit=3, minimum_score=_public_deal_threshold())
    return render_template("home.html", offers=offers)


@site.get("/deals")
def deals():
    all_qualified = [_localize_offer_airports(o) for o in recent_offers(limit=120, minimum_score=_public_deal_threshold())]

    # Current deals = qualified deals from today's scan batch.
    # We deliberately use the latest scan id instead of timestamp parsing so
    # older records cannot be misclassified by legacy timestamp formats.
    scan_ids = [int(o.get("scan_run_id")) for o in all_qualified if o.get("scan_run_id") is not None]
    latest_scan_id = max(scan_ids) if scan_ids else None

    # Include every qualified offer from scans run in the same current-day batch.
    # Existing data from the testing session may span several scan IDs, so use
    # scan_started_at where valid; otherwise keep recent scan IDs together.
    today_local = datetime.now(ZoneInfo(ISRAEL_TZ)).date()
    today_scan_ids = set()
    for offer in all_qualified:
        sid = offer.get("scan_run_id")
        raw = offer.get("scan_started_at")
        if sid is None:
            continue
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z","+00:00")) if raw else None
            if dt and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt and dt.astimezone(ZoneInfo(ISRAEL_TZ)).date() == today_local:
                today_scan_ids.add(int(sid))
        except Exception:
            pass

    # Legacy fallback: if historical scan timestamps cannot be interpreted,
    # the latest scan remains current rather than sending everything below the divider.
    if not today_scan_ids and latest_scan_id is not None:
        today_scan_ids.add(latest_scan_id)

    offers = [o for o in all_qualified if o.get("scan_run_id") is not None and int(o.get("scan_run_id")) in today_scan_ids]
    previous_offers = [o for o in all_qualified if o not in offers][:30]
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
        database_offers = [_localize_offer_airports(o) for o in recent_offers(limit=1500, minimum_score=None)]
        for row in rows:
            trip = _trip_dict(row)
            trip["offers"] = _resolved_trip_offers(database_offers, trip, limit=5)
            inventory = _customer_inventory_status(database_offers, trip)
            trip["database_match_found"] = bool(trip["offers"])
            trip["needs_fresh_search"] = not bool(trip["offers"])
            trip["has_incomplete_inventory"] = inventory["has_incomplete_inventory"]
            personal_trips.append(trip)
    member = _current_member() if session.get("member_id") else None
    return render_template("deals.html", offers=offers, previous_offers=previous_offers,
                           personal_trips=personal_trips, member=member)




@site.post("/whatsapp-opt-in")
def whatsapp_opt_in():
    member = _current_member()
    if not member:
        flash(_msg("כדי לקבל את הדילים לפני כולם ב-WhatsApp יש להירשם תחילה.", "Please join Ariella first to receive WhatsApp deal alerts."), "error")
        return redirect(url_for("site.join"))
    enabled = request.form.get("enabled", "1") == "1"
    with _db() as conn:
        conn.execute("UPDATE members SET whatsapp_opt_in=?, whatsapp_opt_in_at=? WHERE id=?",
                     (1 if enabled else 0, utc_now_iso() if enabled else None, member["id"]))
        conn.commit()
    return redirect(url_for("site.deals"))

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
        if not full_name or not email or not phone or not password or not preferred_airports:
            flash(_msg("יש למלא שם, כתובת דוא״ל, מספר נייד, סיסמה ולבחור לפחות שדה תעופה אחד.", "Please enter your name, email address, mobile number, password and select at least one departure airport."), "error")
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



@site.get("/book/<int:offer_id>")
def book_offer(offer_id):
    """Track intent-to-book, then open the exact selected round-trip whenever possible."""
    offer = next(
        (o for o in recent_offers(limit=1500, minimum_score=None)
         if int(o.get("id") or o.get("offer_id") or 0) == offer_id),
        None,
    )
    if not offer:
        return redirect(url_for("site.deals"))

    record_booking_click(
        visitor_id=session.get("_ariella_visitor_id"),
        member_id=session.get("member_id"),
        offer_id=offer_id,
        destination_code=offer.get("arrival_code"),
        airline=offer.get("airline"),
        supplier=offer.get("booking_supplier"),
        price_ils=offer.get("price_ils"),
        score=offer.get("score"),
        outbound_date=offer.get("outbound_date"),
        return_date=offer.get("return_date"),
        booking_url=offer.get("booking_url"),
    )

    # 1) Best case: use the exact booking request saved when Ariella selected
    # this outbound + return combination.
    exact_url = offer.get("booking_request_url")
    exact_post = offer.get("booking_request_post_data")
    if exact_url:
        if exact_post:
            return render_template(
                "booking_forward.html",
                action=exact_url,
                fields=parse_qsl(exact_post, keep_blank_values=True),
            )
        return redirect(exact_url)

    # 2) Older stored deals may not have the exact request persisted yet.
    # Refresh booking options from the stored booking token and prefer the SAME
    # supplier Ariella showed on the card, then direct airline, then cheapest.
    token = offer.get("booking_token") or (offer.get("flight") or {}).get("booking_token")
    preferred_supplier = str(offer.get("booking_supplier") or "").strip().lower()

    if token and SERPAPI_API_KEY:
        try:
            data = requests.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google_flights",
                    "booking_token": token,
                    "api_key": SERPAPI_API_KEY,
                    "hl": "en",
                    "gl": "il",
                    "currency": "ILS",
                },
                timeout=45,
            ).json()

            choices = []
            for option in data.get("booking_options") or []:
                part = option.get("together") or {}
                req = part.get("booking_request") or {}
                if not req.get("url"):
                    continue

                supplier = str(part.get("book_with") or "").strip().lower()
                same_supplier = bool(preferred_supplier and supplier == preferred_supplier)
                direct_airline = bool(part.get("airline") is True)
                try:
                    price = float(part.get("price") or 10**9)
                except (TypeError, ValueError):
                    price = 10**9

                # exact supplier first, then direct airline, then price
                priority = 0 if same_supplier else (1 if direct_airline else 2)
                choices.append((priority, price, req))

            if choices:
                _, _, req = sorted(choices, key=lambda x: (x[0], x[1]))[0]
                if req.get("post_data"):
                    return render_template(
                        "booking_forward.html",
                        action=req["url"],
                        fields=parse_qsl(req["post_data"], keep_blank_values=True),
                    )
                return redirect(req["url"])
        except Exception:
            pass

    # 3) Last resort only: the Google Flights/result URL already carries the
    # route/date context, but may require the user to choose the flights again.
    return redirect(offer.get("booking_url") or url_for("site.deals"))


@site.get("/account")
@login_required
def account():
    member_id = session["member_id"]
    with _db() as conn:
        member_row = conn.execute(
            "SELECT id, full_name, email, phone, country, preferred_airports, created_at, whatsapp_opt_in, whatsapp_opt_in_at FROM members WHERE id=? AND status='active'",
            (member_id,),
        ).fetchone()
        if member_row is None:
            session.pop("member_id", None)
            return redirect(url_for("site.login", next=request.path))
        _expire_finished_trips(conn, member_id)
        rows = conn.execute("SELECT * FROM trip_requests WHERE member_id=? ORDER BY id DESC", (member_id,)).fetchall()
        conn.commit()
    trips = [_trip_dict(row) for row in rows]
    database_offers = [_localize_offer_airports(o) for o in recent_offers(limit=1500, minimum_score=None)]
    for trip in trips:
        trip["offers"] = _resolved_trip_offers(database_offers, trip, limit=5)
        inventory = _customer_inventory_status(database_offers, trip)
        trip["needs_fresh_search"] = not bool(trip["offers"])
        trip["has_incomplete_inventory"] = inventory["has_incomplete_inventory"]
        answers = trip.get("answers") or {}
        destination_codes = sorted(_trip_destination_codes(trip))
        destination_info = _AIRPORT_LOCALIZATION.get(destination_codes[0], {}) if destination_codes else {}
        if destination_codes:
            code = destination_codes[0]
            city_he = destination_info.get("city_he") or code
            city_en = destination_info.get("city_en") or code
            trip["destination_display"] = f"{city_en} ({code})" if _lang() == "en" else f"{city_he} ({code})"
        elif str(answers.get("destination_mode") or "") == "ski":
            trip["destination_display"] = _msg("חופשת סקי", "Ski vacation")
        else:
            trip["destination_display"] = _msg("אריאלה תמליץ", "Ariella recommends")

        if str(answers.get("vacation_type") or "") == "ski" or str(answers.get("destination_mode") or "") == "ski":
            trip["image_url"] = "https://images.unsplash.com/photo-1454496522488-7a8e488e8606?auto=format&fit=crop&w=900&q=82"
        elif destination_codes:
            # OTP/Bucharest gets a dedicated recognizable city image; other known
            # destinations keep the curated landmark map.
            dedicated = {
                "OTP": "https://images.unsplash.com/photo-1584646098378-0874589d76b1?auto=format&fit=crop&w=900&q=82",
            }
            trip["image_url"] = dedicated.get(destination_codes[0]) or DESTINATION_LANDMARK_IMAGES.get(destination_codes[0]) or "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=900&q=82"
        else:
            trip["image_url"] = "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?auto=format&fit=crop&w=900&q=82"
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
    """Legacy safety route: never spend API quota from an old/stale button."""
    flash(_msg(
        "המשך חיפוש מתבצע רק לאחר בחירת מסלול ואישור תשלום.",
        "Search continuation starts only after choosing a plan and confirmed payment."
    ), "info")
    return redirect(url_for("site.account") + f"#vacation-{trip_id}")


@site.post("/trip/<int:trip_id>/free-alternative")
@login_required
def free_trip_alternative(trip_id):
    """Exactly one additional complimentary search after an unsuccessful initial search."""
    choice = request.form.get("alternative", "").strip()
    if choice not in {"nearby_dates", "other_destination"}:
        return redirect(url_for("site.account") + f"#vacation-{trip_id}")

    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM trip_requests WHERE id=? AND member_id=?",
            (trip_id, session["member_id"]),
        ).fetchone()
        if not row or int(row["free_scan_count"] or 0) > 1:
            return redirect(url_for("site.account") + f"#vacation-{trip_id}")
        trip = _trip_dict(row)
        answers = dict(trip.get("answers") or {})

        if choice == "nearby_dates":
            # One bounded alternative request: shift the exact window by 3 days.
            # It remains a single search job per stored origin.
            try:
                out = datetime.strptime(answers.get("departure_date"), "%Y-%m-%d").date()
                ret = datetime.strptime(answers.get("return_date"), "%Y-%m-%d").date()
                answers["departure_date"] = (out + timedelta(days=3)).isoformat()
                answers["return_date"] = (ret + timedelta(days=3)).isoformat()
                answers["date_mode"] = "exact"
            except Exception:
                return redirect(url_for("site.account") + f"#vacation-{trip_id}")
        else:
            # Destination alternatives need the recommendation engine/controlled
            # destination pool. Do not burn multiple API calls until that engine is wired.
            conn.execute(
                "UPDATE trip_requests SET free_scan_count=2, free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
                (utc_now_iso(), "alternative_destination_pending", trip_id),
            )
            conn.commit()
            flash(_msg(
                "הבחירה נשמרה. חיפוש יעד חלופי יופעל לאחר חיבור מנוע ההמלצות, בלי להפעיל סריקות אקראיות.",
                "Your choice was saved. The alternative-destination search will run once the recommendation engine is connected, without random scans."
            ), "info")
            return redirect(url_for("site.account") + f"#vacation-{trip_id}")

    scan_result = run_customer_trip_search(trip_id, answers)
    with _db() as conn:
        conn.execute(
            "UPDATE trip_requests SET free_scan_count=2, free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
            (utc_now_iso(), str(scan_result.get("status") or "unknown"), trip_id),
        )
        conn.commit()
    return redirect(url_for("site.account") + f"#vacation-{trip_id}")


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
    # Checkout will replace this pending step. Selecting a plan does NOT start scans.
    # Only a confirmed payment may activate the paid monthly search period.
    # Four days before expiry, send a renewal reminder with a link back to My Vacations.
    # No automatic renewal or recurring charge.
    return redirect(url_for("site.account", payment="pending", trip_id=trip_id))


@site.route("/trip/new", methods=["GET", "POST"])
@login_required
def new_trip():
    if request.method == "POST":
        form = request.form
        destination_mode = form.get("destination_mode", "open")
        destinations = form.get("destinations", "").strip()
        date_mode = form.get("date_mode", "anytime")
        outbound_month = form.get("outbound_month", "").strip()
        return_month = form.get("return_month", "").strip()
        # Backward compatibility with older saved forms.
        travel_month = form.get("travel_month", "").strip()
        if not outbound_month and travel_month:
            outbound_month = travel_month
        if not return_month and outbound_month:
            return_month = outbound_month
        departure_date = form.get("departure_date", "").strip()
        return_date = form.get("return_date", "").strip()
        today = date.today().isoformat()
        current_month = today[:7]

        if destination_mode in {"specific", "several"} and not destinations:
            flash(_msg("יש לכתוב את היעד או היעדים שמעניינים אתכם.", "Please enter the destination or destinations you are interested in."), "error")
            return render_template("trip_form.html", today=today, current_month=current_month)
        if date_mode == "month":
            if not outbound_month or not return_month or outbound_month < current_month or return_month < current_month:
                flash(_msg("יש לבחור חודש יציאה וחודש חזרה נוכחיים או עתידיים.", "Please choose a current or future departure month and return month."), "error")
                return render_template("trip_form.html", today=today, current_month=current_month)
            if return_month < outbound_month:
                flash(_msg("חודש החזרה חייב להיות זהה לחודש היציאה או מאוחר ממנו.", "The return month must be the same as or later than the departure month."), "error")
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

        destination_title = destinations if destinations else (_msg("חופשת סקי", "Ski vacation") if destination_mode == "ski" else _msg("הצעות של אריאלה", "Ariella suggestions"))
        if date_mode == "month":
            travel_window = outbound_month if outbound_month == return_month else f"{outbound_month} → {return_month}"
        elif date_mode == "exact":
            travel_window = f"{departure_date} – {return_date}"
        elif date_mode == "ski_flexible":
            travel_window = _msg("אריאלה תבחר — עונת סקי", "Ariella chooses — ski season")
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
        origin_selection_mode = form.get("origin_selection_mode", "default")
        # A deliberate vacation-level airport choice ALWAYS wins over account/country defaults.
        # Defaults are used only when the customer did not replace them for this vacation.
        origin_airports = override_airports if origin_selection_mode == "custom" else (override_airports or profile_airports)

        payload = {
            "origin_airports": origin_airports,
            "destination_mode": destination_mode, "vacation_type": "ski" if destination_mode == "ski" else "standard", "destinations": destinations,
            "date_mode": date_mode, "travel_month": outbound_month,
            "outbound_month": outbound_month, "return_month": return_month,
            "departure_date": departure_date, "return_date": return_date,
            "travel_party": travel_party, "adults": adults,
            "children": form.get("children"), "age_groups": form.getlist("age_groups"),
            "holiday_priorities": form.getlist("holiday_priorities"),
            "deal_priorities": form.getlist("deal_priorities"),
            "budget_mode": budget_mode,
            "budget_amount": form.get("budget_amount") if budget_mode == "per_person" else "",
            "special_needs": form.getlist("special_needs") if destination_mode != "specific" else [], "notes": form.get("notes", "").strip(),
        }
        with _db() as conn:
            cur = conn.execute(
                "INSERT INTO trip_requests (member_id,request_name,travel_window,status,answers_json,created_at,mobile_notifications) VALUES(?,?,?,?,?,?,?)",
                (session["member_id"], request_name, travel_window, "active", json.dumps(payload, ensure_ascii=False), utc_now_iso(), 0),
            )
            trip_id = int(cur.lastrowid)
            conn.commit()

        # DATABASE FIRST. A matching usable offer already paid for in inventory
        # is shown immediately and prevents another SerpAPI search.
        trip_for_match = {"id": trip_id, "answers": payload, "request_name": request_name, "travel_window": travel_window}
        existing_inventory = [_localize_offer_airports(o) for o in recent_offers(limit=1500, minimum_score=None)]
        existing_matches = _customer_deal_choices(existing_inventory, trip_for_match, limit=5)

        scan_status = "database_match" if existing_matches else "not_started"
        scan_count = 0
        if existing_matches:
            matched_ids = [int(o["offer_id"]) for o in existing_matches if o.get("offer_id") is not None]
            payload["_matched_offer_ids"] = matched_ids
            with _db() as conn:
                conn.execute(
                    "UPDATE trip_requests SET answers_json=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), trip_id),
                )
                conn.commit()
        if not existing_matches:
            try:
                scan_result = run_customer_trip_search(trip_id, payload)
                scan_status = str(scan_result.get("status") or "unknown")
                scan_count = 1
                # Pin any fresh results produced for this vacation.
                refreshed = [_localize_offer_airports(o) for o in recent_offers(limit=1500, minimum_score=None)]
                created_for_trip = []
                for o in refreshed:
                    try:
                        if int(o.get("trip_id")) == trip_id and _offer_is_recent(o, 48):
                            created_for_trip.append(int(o["offer_id"]))
                    except (TypeError, ValueError, KeyError):
                        pass
                if created_for_trip:
                    payload["_matched_offer_ids"] = created_for_trip[:5]
                    with _db() as conn:
                        conn.execute(
                            "UPDATE trip_requests SET answers_json=? WHERE id=?",
                            (json.dumps(payload, ensure_ascii=False), trip_id),
                        )
                        conn.commit()
            except Exception as exc:
                # The vacation was committed above. Search errors must never erase it
                # or send the customer to Flask's Internal Server Error page.
                scan_status = "search_error"
                scan_count = 1

        with _db() as conn:
            conn.execute(
                "UPDATE trip_requests SET free_scan_count=?, free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
                (scan_count, utc_now_iso(), scan_status, trip_id),
            )
            conn.commit()
        return redirect(url_for("site.account") + f"#vacation-{trip_id}")

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
