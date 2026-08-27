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
from booker import resolve_booking_target



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

_SKI_DB_FILE = Path(__file__).resolve().parent / "data" / "ski_resorts.json"
try:
    _SKI_RESORTS = json.loads(_SKI_DB_FILE.read_text(encoding="utf-8")).get("resorts", [])
except Exception:
    _SKI_RESORTS = []


def _ski_picker_options():
    countries = {}
    resorts = []
    for row in _SKI_RESORTS:
        country = str(row.get("country") or "").strip()
        country_he = str(row.get("country_he") or country).strip()
        if country:
            countries[country] = country_he
        resorts.append({
            "value": f"resort:{row.get('resort')}",
            "label_he": f"{row.get('resort')} — {country_he}",
            "label_en": f"{row.get('resort')} — {country}",
            "country": country,
        })
    country_opts = [
        {"value": f"country:{country}", "label_he": f"{he} — כל אתרי הסקי", "label_en": f"{country} — any ski resort"}
        for country, he in sorted(countries.items(), key=lambda kv: kv[1])
    ]
    resorts.sort(key=lambda x: (x["country"], x["label_en"]))
    return country_opts + resorts


def _resolve_ski_targets(raw_values, mode, skill_level=None, max_transfer_minutes=None):
    """Resolve resort/country choices into a curated resort subset + gateway airports."""
    selected = [str(x).strip() for x in (raw_values or []) if str(x).strip()]
    rows = list(_SKI_RESORTS)

    if mode in {"specific", "several"} and selected:
        resort_names = {x.split(":", 1)[1] for x in selected if x.startswith("resort:")}
        countries = {x.split(":", 1)[1] for x in selected if x.startswith("country:")}
        rows = [
            r for r in rows
            if str(r.get("resort")) in resort_names or str(r.get("country")) in countries
        ]

    if skill_level:
        rows = [
            r for r in rows
            if skill_level == "mixed" or skill_level in set(r.get("levels") or [])
        ]

    if max_transfer_minutes:
        try:
            cap = int(max_transfer_minutes)
            rows = [
                r for r in rows
                if int(r.get("transfer_minutes_estimate") or 9999) <= cap
            ]
        except (TypeError, ValueError):
            pass

    airports, names, countries = [], [], []
    for r in rows:
        names.append(str(r.get("resort")))
        countries.append(str(r.get("country")))
        for code in r.get("gateway_airports") or []:
            code = str(code).upper()
            if code and code not in airports:
                airports.append(code)
    return {
        "resorts": rows,
        "resort_names": names,
        "countries": sorted(set(countries)),
        "gateway_airports": airports,
    }


def _ski_row_for_offer(offer, trip):
    answers = trip.get("answers") or {}
    if str(answers.get("vacation_type") or "standard") != "ski":
        return None
    allowed_names = set(answers.get("ski_resort_names") or [])
    arrival = str(offer.get("arrival_code") or "").upper()
    candidates = []
    for row in _SKI_RESORTS:
        if allowed_names and str(row.get("resort")) not in allowed_names:
            continue
        if arrival in {str(x).upper() for x in (row.get("gateway_airports") or [])}:
            candidates.append(row)
    if not candidates:
        return None
    candidates.sort(key=lambda r: int(r.get("transfer_minutes_estimate") or 9999))
    return candidates[0]


def _decorate_ski_offer(offer, trip):
    if str((trip.get("answers") or {}).get("vacation_type") or "standard") != "ski":
        return offer
    copy = dict(offer)
    row = _ski_row_for_offer(copy, trip)
    if row:
        copy["ski_resort"] = row.get("resort")
        copy["ski_country"] = row.get("country")
        copy["ski_transfer_minutes"] = row.get("transfer_minutes_estimate")
        copy["ski_resort_scores"] = row.get("scores") or {}
        copy["ski_resort_levels"] = row.get("levels") or []
    return copy


def _ski_offer_constraints_ok(offer, trip):
    answers = trip.get("answers") or {}
    if str(answers.get("vacation_type") or "standard") != "ski":
        return True
    if not offer.get("ski_resort"):
        return False

    level = str(answers.get("ski_skill_level") or "")
    if level and level != "mixed":
        if level not in set(offer.get("ski_resort_levels") or []):
            return False

    try:
        cap = int(answers.get("ski_max_transfer_minutes") or 0)
    except (TypeError, ValueError):
        cap = 0
    if cap and int(offer.get("ski_transfer_minutes") or 9999) > cap:
        return False
    return True


def _ski_preference_score(offer, trip):
    answers = trip.get("answers") or {}
    if str(answers.get("vacation_type") or "standard") != "ski":
        return 0.0
    scores = offer.get("ski_resort_scores") or {}
    priorities = set(answers.get("ski_priorities") or [])
    mapping = {
        "snow": "snow", "family": "family", "large": "size",
        "value": "value", "atmosphere": "atmosphere",
        "nightlife": "nightlife", "spa": "spa",
    }
    total = 0.0
    for pref, key in mapping.items():
        if pref in priorities:
            total += float(scores.get(key) or 0) * 10.0
    if "proximity" in priorities:
        mins = float(offer.get("ski_transfer_minutes") or 999)
        total += max(0.0, 50.0 - mins / 5.0)
    if "level" in priorities:
        total += 25.0
    return total


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




def _strict_public_offer(offer):
    """Final public rendering gate for current AND previous deal cards."""
    def present(value):
        if value is None:
            return False
        s = str(value).strip()
        return bool(s and s not in {"—", "-", "None", "null"})
    required = (
        "outbound_date", "return_date",
        "departure_time", "arrival_time",
        "return_departure_time", "return_arrival_time",
    )
    return all(present(offer.get(k)) for k in required)

def _offer_is_publicly_bookable(offer):
    """Public deal cards must contain a complete round trip."""
    return _strict_public_offer(offer)


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
        try:
            flex = max(0, min(3, int(answers.get("date_flex_days") or 0)))
        except (TypeError, ValueError):
            flex = 0
        req_out = _date_from_iso(answers.get("departure_date")); req_ret = _date_from_iso(answers.get("return_date"))
        off_out = _date_from_iso(outbound); off_ret = _date_from_iso(inbound)
        if not all([req_out, req_ret, off_out, off_ret]):
            return False
        if abs((off_out - req_out).days) > flex or abs((off_ret - req_ret).days) > flex:
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



def _qa_fixture_offers():
    """Deterministic fake inventory used only when admin QA test mode is enabled.

    These rows never enter the offers table and therefore never contaminate price
    history, Radar statistics or production deal discovery.
    """
    # Testing build: fixtures are active by default, but can be disabled from settings.
    if str(get_setting("qa_test_mode", "1") or "1") == "0":
        return []

    now = datetime.now(timezone.utc).isoformat()

    def bag(personal=True, carry=False, checked=False):
        return {
            "personal_item": {"included": bool(personal), "known": True},
            "carry_on_8kg": {
                "included": bool(carry), "known": True,
                "roundtrip_price_ils": 0 if carry else 180,
            },
            "checked_bag_23kg": {
                "included": bool(checked), "known": True,
                "roundtrip_price_ils": 0 if checked else 320,
            },
        }

    def offer(oid, code, city_he, city_en, out_date, ret_date, price,
              dep_time, arr_time, ret_dep, ret_arr, stops=0,
              carry=False, checked=False, score=80, qa_type="standard",
              resort=None, ski_transfer_minutes=None, image=None):
        duration = 165 if code in {"SOF","MXP"} else 285 if code == "GVA" else 155
        return {
            "id": oid, "offer_id": oid, "qa_test_deal": True,
            "qa_vacation_type": qa_type,
            "last_seen_at": now, "observed_at": now, "scan_started_at": now,
            "departure_code": "TLV", "arrival_code": code,
            "departure_city_he": "תל אביב", "departure_city_en": "Tel Aviv",
            "arrival_city_he": city_he, "arrival_city_en": city_en,
            "outbound_date": out_date, "return_date": ret_date,
            "departure_time": dep_time, "arrival_time": arr_time,
            "return_departure_time": ret_dep, "return_arrival_time": ret_arr,
            "airline": "QA AIR", "return_airline": "QA AIR",
            "price_ils": float(price), "score": int(score),
            "discount_percent": 15, "reference_price_ils": float(price) * 1.18,
            "price_reference_reliable": True,
            "stops": int(stops), "return_stops": int(stops),
            "connections": [] if stops == 0 else [{"airport": "QA1", "duration_minutes": 75}],
            "return_connections": [] if stops == 0 else [{"airport": "QA1", "duration_minutes": 70}],
            "total_duration_minutes": duration + stops * 95,
            "return_total_duration_minutes": duration + stops * 90,
            "arrival_days_after": 0, "return_arrival_days_after": 0,
            "baggage": bag(True, carry, checked),
            "route_score": 100 if stops == 0 else 72 if stops == 1 else 50,
            "time_value_score": 90 if dep_time[:2] in {"07","08","09","10"} and ret_dep[:2] in {"18","19","20","21"} else 55,
            "hours_score": 90 if dep_time[:2] in {"07","08","09","10"} and ret_dep[:2] in {"18","19","20","21"} else 55,
            "baggage_score": 100 if checked else 82 if carry else 45,
            "cost_score": max(20, 100 - int(price/15)),
            "rarity_score": 50,
            "consumer_protection_label": "יש לבדוק מול הספק",
            "consumer_protection_class": "check",
            "change_cancel_label": "בכפוף לתנאי הספק",
            "display_reasons": ["דיל בדיקה QA"],
            "destination_image_url": image or "https://images.unsplash.com/photo-1470770841072-f978cf4d019e?auto=format&fit=crop&w=900&q=82",
            "ski_resort": resort,
            "ski_transfer_minutes": ski_transfer_minutes,
            "booking_url": None,
        }

    # REGULAR QA: Sofia, November 2026. Five deliberately different offers.
    regular = [
        offer(-910501, "SOF", "סופיה", "Sofia", "2026-11-10", "2026-11-18", 620, "08:00", "10:45", "19:30", "22:15", 0, False, False, 82),
        offer(-910502, "SOF", "סופיה", "Sofia", "2026-11-10", "2026-11-18", 690, "22:30", "01:15", "06:00", "08:45", 0, True, False, 79),
        offer(-910503, "SOF", "סופיה", "Sofia", "2026-11-10", "2026-11-18", 650, "09:30", "13:45", "18:30", "22:40", 1, False, True, 77),
        offer(-910504, "SOF", "סופיה", "Sofia", "2026-11-12", "2026-11-20", 520, "02:30", "08:30", "03:30", "09:20", 2, False, False, 70),
        offer(-910505, "SOF", "סופיה", "Sofia", "2026-11-10", "2026-11-18", 760, "10:00", "12:45", "20:30", "23:15", 0, False, True, 88),
    ]

    ski_img = "https://images.unsplash.com/photo-1486911278844-a81c5267e227?auto=format&fit=crop&w=900&q=82"
    ski = [
        offer(-910551, "SOF", "סופיה", "Sofia", "2027-01-10", "2027-01-17", 700, "07:30", "10:15", "20:00", "22:45", 0, False, True, 86, "ski", "Bansko", 120, ski_img),
        offer(-910552, "TBS", "טביליסי", "Tbilisi", "2027-01-10", "2027-01-17", 600, "06:30", "11:05", "18:30", "21:15", 0, True, False, 81, "ski", "Gudauri", 145, ski_img),
        offer(-910553, "GVA", "ז׳נבה", "Geneva", "2027-01-10", "2027-01-17", 900, "08:00", "12:05", "20:30", "00:35", 0, False, True, 90, "ski", "Chamonix", 75, ski_img),
        offer(-910554, "MXP", "מילאנו", "Milan", "2027-01-10", "2027-01-17", 780, "09:00", "12:20", "19:30", "22:50", 0, False, True, 87, "ski", "Cervinia", 130, ski_img),
        offer(-910555, "GVA", "ז׳נבה", "Geneva", "2027-01-10", "2027-01-17", 740, "11:30", "17:20", "16:00", "21:45", 1, True, False, 78, "ski", "Les Gets", 65, ski_img),
    ]
    return regular + ski


def _offer_matches_vacation_type(offer, trip):
    qa_type = str(offer.get("qa_vacation_type") or "").strip()
    if not qa_type:
        return True
    requested = str((trip.get("answers") or {}).get("vacation_type") or "standard")
    return qa_type == requested


def _offer_within_budget(offer, trip):
    """Per-person budget is a hard ceiling with the agreed 10% tolerance."""
    answers = trip.get("answers") or {}
    if answers.get("budget_mode") != "per_person":
        return True
    try:
        budget = float(answers.get("budget_amount") or 0)
        price = float(offer.get("price_ils") or 0)
    except (TypeError, ValueError):
        return False
    return budget <= 0 or price <= budget * 1.10


def _over_budget_alternatives(all_offers, trip, limit=3):
    """Offers that satisfy every requested hard condition except budget.

    Used only as a transparent fallback: these offers are NOT treated as budget matches.
    """
    answers = trip.get("answers") or {}
    if answers.get("budget_mode") != "per_person" or not answers.get("budget_amount"):
        return []
    try:
        ceiling = float(answers.get("budget_amount") or 0) * 1.10
    except (TypeError, ValueError):
        return []
    if ceiling <= 0:
        return []

    prepared = [_decorate_ski_offer(o, trip) for o in all_offers]
    candidates = []
    for o in prepared:
        if not _offer_is_recent(o, 48):
            continue
        if not _offer_destination_matches(o, trip):
            continue
        if not _offer_has_complete_roundtrip(o):
            continue
        if not _offer_matches_vacation_type(o, trip):
            continue
        if not _offer_meets_selected_conditions(o, trip):
            continue
        if not _ski_offer_constraints_ok(o, trip):
            continue
        if answers.get("date_mode") == "exact" and not _offer_matches_trip(o, trip, exact_dates=True):
            continue
        if answers.get("date_mode") == "month" and not _offer_matches_trip(o, trip, same_month=True):
            continue
        try:
            if float(o.get("price_ils") or 0) <= ceiling:
                continue
        except (TypeError, ValueError):
            continue
        candidates.append(o)

    candidates.sort(key=lambda o: (float(o.get("price_ils") or 10**9), -int(o.get("score") or 0)))
    out, seen = [], set()
    for offer in candidates:
        sig = _offer_signature(offer)
        if sig in seen:
            continue
        copy = dict(offer)
        copy["customer_choice_label_he"] = "אפשרות שכדאי להכיר"
        copy["customer_choice_label_en"] = "An option worth seeing"
        out.append(copy)
        seen.add(sig)
        if len(out) >= limit:
            break
    return out


def _time_minutes(value):
    try:
        hh, mm = str(value)[-5:].split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return None


def _offer_meets_selected_conditions(offer, trip):
    """Selected Q04 conditions are AND filters where a clear pass/fail exists."""
    answers = trip.get("answers") or {}
    priorities = {str(x) for x in (answers.get("deal_priorities") or [])}

    if "direct" in priorities and int(offer.get("stops") or 0) != 0:
        return False

    if "baggage" in priorities:
        baggage = offer.get("baggage") or {}
        carry = (baggage.get("carry_on_8kg") or {}).get("included") is True
        checked = (baggage.get("checked_bag_23kg") or {}).get("included") is True
        if not (carry or checked):
            return False

    if "dates" in priorities:
        if answers.get("date_mode") == "exact":
            if not _offer_matches_trip(offer, trip, exact_dates=True):
                return False
        elif answers.get("date_mode") == "month":
            if not _offer_matches_trip(offer, trip, same_month=True):
                return False

    return True


def _priority_sort_key(offer, trip):
    """Rank after hard filtering; selected preference order is deterministic."""
    answers = trip.get("answers") or {}
    priorities = {str(x) for x in (answers.get("deal_priorities") or [])}
    price = float(offer.get("price_ils") or 10**9)
    rank = float(_customer_rank_value(offer, trip))

    arrival = _time_minutes(offer.get("arrival_time"))
    ret = _time_minutes(offer.get("return_departure_time"))
    # "Maximize the trip" is a strong preference, never a hard filter:
    # arrival by 10:00 and return departure from 20:00 receive the strongest score.
    maximize = 0
    if arrival is not None:
        maximize += 2 if arrival <= 600 else max(0, 1 - (arrival - 600) / 360)
    if ret is not None:
        maximize += 2 if ret >= 1200 else max(0, 1 - (1200 - ret) / 360)

    key = []
    if str(answers.get("destination_mode") or "") == "open":
        key.append(-_holiday_preference_score(offer, trip))
    if str(answers.get("vacation_type") or "standard") == "ski":
        key.append(-_ski_preference_score(offer, trip))
    if "price" in priorities:
        key.append(price)
    if "maximize" in priorities:
        key.append(-maximize)
    if "ski_proximity" in priorities and isinstance(offer.get("ski_transfer_minutes"), (int, float)):
        key.append(float(offer.get("ski_transfer_minutes")))
    if "balanced" in priorities or not priorities:
        key.append(-rank)
    key.extend([-rank, price])
    return tuple(key)


def _date_from_iso(value):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _business_offer_date_relevant(offer, trip):
    answers = trip.get("answers") or {}
    if str(answers.get("vacation_type") or "") != "business":
        return True
    req_out = _date_from_iso(answers.get("departure_date"))
    req_ret = _date_from_iso(answers.get("return_date"))
    off_out = _date_from_iso(offer.get("outbound_date"))
    off_ret = _date_from_iso(offer.get("return_date"))
    if not all([req_out, req_ret, off_out, off_ret]):
        return False

    try:
        flex = max(0, min(3, int(answers.get("business_flex_days") or 0)))
    except (TypeError, ValueError):
        flex = 0

    if flex:
        return abs((off_out - req_out).days) <= flex and abs((off_ret - req_ret).days) <= flex

    # No customer flexibility: exact dates, with one operational exception.
    # If an arrival deadline was supplied, allow departure one day earlier so
    # Ariella can actually meet an early-morning business commitment.
    earliest_out = req_out - timedelta(days=1) if answers.get("business_arrive_by_time") else req_out
    return earliest_out <= off_out <= req_out and off_ret == req_ret


def _business_deadline_ok(offer, trip):
    answers = trip.get("answers") or {}
    target_time = _time_minutes(answers.get("business_arrive_by_time"))
    if target_time is None:
        return None
    target_date = _date_from_iso(answers.get("business_arrive_by_date") or answers.get("departure_date"))
    out_date = _date_from_iso(offer.get("outbound_date"))
    if not target_date or not out_date:
        return False
    arrival_date = out_date + timedelta(days=int(offer.get("arrival_days_after") or 0))
    if arrival_date < target_date:
        return True
    if arrival_date > target_date:
        return False
    arrival_time = _time_minutes(offer.get("arrival_time"))
    return arrival_time is not None and arrival_time <= target_time


def _business_return_time_ok(offer, trip):
    answers = trip.get("answers") or {}
    target_time = _time_minutes(answers.get("business_return_after_time"))
    if target_time is None:
        return None
    target_date = _date_from_iso(answers.get("business_return_after_date") or answers.get("return_date"))
    off_ret = _date_from_iso(offer.get("return_date"))
    if not target_date or not off_ret:
        return False
    if off_ret > target_date:
        return True
    if off_ret < target_date:
        return False
    ret_time = _time_minutes(offer.get("return_departure_time"))
    return ret_time is not None and ret_time >= target_time


def _business_match_details(offer, trip):
    """One point per customer condition met. No business preference hard-filters an offer."""
    answers = trip.get("answers") or {}
    selected = set(answers.get("business_priorities") or [])
    points, possible, reasons = 0, 0, []

    def add(condition, he, en):
        nonlocal points, possible
        possible += 1
        if condition:
            points += 1
            reasons.append(en if _lang() == "en" else he)

    if "direct" in selected:
        add(int(offer.get("stops") or 0) == 0, "טיסה ישירה", "Direct flight")
    if "max_one_connection" in selected:
        add(int(offer.get("stops") or 0) <= 1, "עד קונקשן אחד", "Up to one connection")
    if "baggage" in selected:
        baggage = offer.get("baggage") or {}
        carry = (baggage.get("carry_on_8kg") or {}).get("included") is True
        checked = (baggage.get("checked_bag_23kg") or {}).get("included") is True
        add(carry or checked, "כולל כבודה", "Baggage included")
    if "flexible_ticket" in selected:
        label = str(offer.get("change_cancel_label") or "").lower()
        add(
            ("ללא תשלום" in label) or ("no charge" in label) or ("free" in label),
            "כרטיס גמיש",
            "Flexible ticket",
        )
    if "short_duration" in selected:
        duration = offer.get("total_duration_minutes")
        route = int(offer.get("route_score") or 0)
        add(
            (isinstance(duration, (int, float)) and duration <= 480) or route >= 80,
            "זמן נסיעה כולל קצר",
            "Short total travel time",
        )

    deadline = _business_deadline_ok(offer, trip)
    if deadline is not None:
        add(deadline, "עומדת בזמן ההגעה שביקשת", "Meets your arrival deadline")
    ret_ok = _business_return_time_ok(offer, trip)
    if ret_ok is not None:
        add(ret_ok, "מתאימה לשעת החזרה שביקשת", "Fits your requested return time")

    cabin = str(answers.get("business_cabin_class") or "any")
    if cabin != "any":
        offer_cabin = str(offer.get("cabin_class") or offer.get("travel_class") or "").lower()
        names = {
            "economy": {"economy", "תיירים"},
            "premium": {"premium", "premium economy", "פרימיום"},
            "business": {"business", "עסקים"},
            "first": {"first", "first class", "ראשונה"},
        }
        add(any(x in offer_cabin for x in names.get(cabin, {cabin})), "מחלקה מבוקשת", "Requested cabin")

    if answers.get("budget_mode") == "per_person" and answers.get("budget_amount"):
        try:
            add(float(offer.get("price_ils") or 0) <= float(answers.get("budget_amount")) * 1.10,
                "בתקציב שביקשת", "Within your budget")
        except (TypeError, ValueError):
            pass

    return points, possible, reasons


def _decorate_business_offer(offer, trip):
    if str((trip.get("answers") or {}).get("vacation_type") or "") != "business":
        return offer
    copy = dict(offer)
    points, possible, reasons = _business_match_details(copy, trip)
    copy["business_match_points"] = points
    copy["business_match_possible"] = possible
    existing = [r for r in (copy.get("display_reasons") or []) if r]
    copy["display_reasons"] = reasons + [r for r in existing if r not in reasons]
    copy["customer_choice_label_he"] = "התאמה גבוהה לבקשה העסקית"
    copy["customer_choice_label_en"] = "Strong business-trip match"
    return copy


def _business_sort_key(offer, trip):
    offer = _decorate_business_offer(offer, trip)
    points = int(offer.get("business_match_points") or 0)
    duration = float(offer.get("total_duration_minutes") or 10**9)
    price = float(offer.get("price_ils") or 10**9)
    return (-points, duration, price)


def _closest_condition_matches(all_offers, trip, limit=3):
    """Last-resort DB fallback: rank recent offers by how many customer conditions they satisfy."""
    answers = trip.get("answers") or {}
    original = {str(x).upper() for x in _customer_destination_codes(answers)}
    candidates = []
    for raw in all_offers:
        o = _localize_offer_airports(raw)
        if not _offer_is_recent(o, 48) or not _offer_has_complete_roundtrip(o):
            continue
        if str(o.get("arrival_code") or "").upper() in original:
            continue
        points, reasons = 0, []
        if answers.get("date_mode") == "exact" and _offer_matches_trip(o, trip, exact_dates=True):
            points += 1; reasons.append(_msg("מתאים לתאריכים שביקשת", "Matches your requested dates"))
        elif answers.get("date_mode") == "month" and _offer_matches_trip(o, trip, same_month=True):
            points += 1; reasons.append(_msg("מתאים לחודשים שביקשת", "Matches your requested months"))
        priorities = set(answers.get("deal_priorities") or [])
        if "direct" in priorities and int(o.get("stops") or 0) == 0:
            points += 1; reasons.append(_msg("טיסה ישירה", "Direct flight"))
        if "baggage" in priorities:
            bag = o.get("baggage") or {}
            if (bag.get("carry_on_8kg") or {}).get("included") is True or (bag.get("checked_bag_23kg") or {}).get("included") is True:
                points += 1; reasons.append(_msg("כולל כבודה", "Baggage included"))
        if "maximize" in priorities:
            arr = _time_minutes(o.get("arrival_time"))
            ret = _time_minutes(o.get("return_departure_time"))
            if arr is not None and ret is not None and arr <= 600 and ret >= 1200:
                points += 1; reasons.append(_msg("ממקסמת את זמן החופשה", "Maximizes usable trip time"))
        if answers.get("budget_mode") == "per_person" and answers.get("budget_amount"):
            try:
                if float(o.get("price_ils") or 0) <= float(answers.get("budget_amount")) * 1.10:
                    points += 1; reasons.append(_msg("בתקציב", "Within budget"))
            except (TypeError, ValueError):
                pass
        if points <= 0:
            continue
        copy = dict(o)
        copy["closest_match_points"] = points
        copy["display_reasons"] = reasons + list(copy.get("display_reasons") or [])
        copy["customer_choice_label_he"] = "אפשרות קרובה לבקשה שלך"
        copy["customer_choice_label_en"] = "A close match to your request"
        candidates.append(copy)
    candidates.sort(key=lambda o: (-int(o.get("closest_match_points") or 0), -int(o.get("score") or 0), float(o.get("price_ils") or 10**9)))
    return candidates[:limit]

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


def _offer_age_hours(offer):
    seen = _offer_seen_at(offer)
    if seen is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - seen).total_seconds() / 3600.0)


@site.app_template_filter("offer_age")
def _offer_age_filter(offer):
    hours = _offer_age_hours(offer)
    if hours is None:
        return "—"
    if hours < 1:
        return "פחות משעה"
    return f"{int(hours)} שעות"


def _offer_is_recent(offer, max_age_hours=48):
    seen = _offer_seen_at(offer)
    if seen is None:
        return False
    return seen >= datetime.now(timezone.utc) - timedelta(hours=max_age_hours)



# Customer-facing vacation-style preferences for open-destination searches.
# These are intentionally broad tags: they guide ranking, never hard-filter a destination.
_DESTINATION_STYLE_TAGS = {
    "ATH": {"beach","city","food","shopping","nightlife","weather"},
    "LCA": {"beach","relax","family","weather","quiet"},
    "BUD": {"city","food","shopping","nightlife"},
    "VIE": {"city","food","shopping","family"},
    "SOF": {"city","nature","food","quiet"},
    "PRG": {"city","food","shopping","nightlife"},
    "FCO": {"city","food","shopping","family"},
    "MXP": {"city","shopping","food","nightlife"},
    "CDG": {"city","food","shopping","family"},
    "AMS": {"city","food","nightlife","family"},
    "BCN": {"beach","city","food","shopping","nightlife","weather"},
    "MAD": {"city","food","shopping","nightlife"},
    "LIS": {"city","food","weather","relax"},
    "LHR": {"city","shopping","family","food"},
    "BER": {"city","nightlife","food","shopping"},
    "MUC": {"city","nature","food","family"},
    "ZRH": {"nature","hiking","quiet","city"},
    "BRU": {"city","food","shopping"},
    "OTP": {"city","food","shopping","nightlife"},
    "KRK": {"city","food","quiet"},
    "WAW": {"city","food","shopping"},
    "TBS": {"nature","hiking","food","city","quiet"},
    "EVN": {"nature","food","city","quiet"},
    "BEG": {"city","food","nightlife"},
    "SKP": {"nature","city","quiet","food"},
    "TGD": {"nature","hiking","quiet","relax"},
    "ZAG": {"city","food","nature","quiet"},
    "LJU": {"nature","hiking","quiet","city"},
    "BKK": {"beach","relax","food","shopping","nightlife","city","weather"},
    "JFK": {"city","shopping","food","nightlife","family"},
}

# Seasonal fit is deliberately a scoring signal, never a hard filter.
# It answers: "is this destination suitable for this vacation style *at the requested time*?"
# Codes not listed remain neutral rather than being guessed.
_SEASONAL_DESTINATION_PROFILES = {
    # Mediterranean / southern Europe: strongest for beach in late spring through early autumn.
    "ATH": {"beach_months": {5,6,7,8,9,10}, "pleasant_months": {4,5,6,9,10,11}},
    "LCA": {"beach_months": {4,5,6,7,8,9,10,11}, "pleasant_months": {3,4,5,6,9,10,11}},
    "BCN": {"beach_months": {5,6,7,8,9,10}, "pleasant_months": {4,5,6,9,10}},
    "LIS": {"beach_months": {5,6,7,8,9,10}, "pleasant_months": {3,4,5,6,9,10,11}},
    "TGD": {"beach_months": {5,6,7,8,9}, "pleasant_months": {4,5,6,9,10}},
    # Thailand is a strong warm-weather / beach alternative through the Israeli winter.
    "BKK": {"beach_months": {1,2,3,4,11,12}, "pleasant_months": {1,2,3,11,12}},
    # Mountain / hiking destinations: shoulder and summer months are generally the best fit.
    "ZRH": {"hiking_months": {5,6,7,8,9,10}, "pleasant_months": {5,6,7,8,9}},
    "TBS": {"hiking_months": {4,5,6,7,8,9,10}, "pleasant_months": {4,5,6,9,10}},
    "LJU": {"hiking_months": {5,6,7,8,9,10}, "pleasant_months": {5,6,7,8,9}},
    "ZAG": {"hiking_months": {5,6,7,8,9,10}, "pleasant_months": {4,5,6,9,10}},
    "MUC": {"hiking_months": {5,6,7,8,9,10}, "pleasant_months": {5,6,7,8,9}},
}

def _requested_travel_month(trip, offer=None):
    """Return the customer's requested outbound month when one exists.

    If Ariella chose the dates, use the offer month only for season-aware ranking;
    if the customer supplied a month/date, that requested month is authoritative.
    """
    answers = trip.get("answers") or {}
    mode = str(answers.get("date_mode") or "anytime")
    raw = ""
    if mode == "month":
        raw = str(answers.get("outbound_month") or answers.get("travel_month") or "")
    elif mode == "exact":
        raw = str(answers.get("departure_date") or "")
    elif offer is not None:
        raw = str(offer.get("outbound_date") or "")
    try:
        return int(raw[5:7]) if len(raw) >= 7 else None
    except (TypeError, ValueError):
        return None

def _seasonal_vacation_fit_score(offer, trip, selected):
    """Score destination × vacation style × travel month.

    Positive values reward a seasonally strong match; negative values demote a
    destination that is normally associated with the requested style but is out
    of season. This remains soft so Ariella can still show the best alternatives.
    """
    month = _requested_travel_month(trip, offer)
    if month is None:
        return 0
    code = str(offer.get("arrival_code") or "").upper()
    profile = _SEASONAL_DESTINATION_PROFILES.get(code)
    if not profile:
        return 0
    tags = _DESTINATION_STYLE_TAGS.get(code, set())
    score = 0

    if "beach" in selected and "beach" in tags:
        if month in profile.get("beach_months", set()):
            score += 14
        else:
            # Strong demotion: Greece/Med in winter should not outrank a genuinely
            # warm destination merely because it is a good beach destination in July.
            score -= 18

    if "hiking" in selected and ("hiking" in tags or "nature" in tags):
        months = profile.get("hiking_months")
        if months:
            score += 8 if month in months else -7

    if "weather" in selected:
        months = profile.get("pleasant_months")
        if months:
            score += 8 if month in months else -6

    # Nature is less season-sensitive than beach/hiking; only a modest bonus is used.
    if "nature" in selected and "nature" in tags and month in profile.get("hiking_months", set()):
        score += 4
    return score

def _holiday_preference_score(offer, trip):
    """How well an open-search destination fits Q04 choices, including season."""
    answers = trip.get("answers") or {}
    if str(answers.get("destination_mode") or "") != "open":
        return 0
    selected = {str(x) for x in (answers.get("holiday_priorities") or []) if x}
    if not selected:
        return 0
    code = str(offer.get("arrival_code") or "").upper()
    tags = _DESTINATION_STYLE_TAGS.get(code, set())
    # Price is judged from the actual fare rather than a static destination tag.
    non_price = selected - {"price"}
    score = len(non_price & tags) * 10
    score += _seasonal_vacation_fit_score(offer, trip, selected)
    if "price" in selected:
        score += int(offer.get("cost_score") or 0) / 10
    return score


def _month_distance(a, b):
    try:
        ay, am = [int(x) for x in str(a)[:7].split("-")]
        by, bm = [int(x) for x in str(b)[:7].split("-")]
        return abs((ay * 12 + am) - (by * 12 + bm))
    except Exception:
        return 999


def _within_primary_date_window(offer, trip):
    """Initial alternatives stay within one month of each requested leg.

    Wider dates are only exposed after the customer explicitly chooses
    'same destination / other dates'.
    """
    answers = trip.get("answers") or {}
    if answers.get("_alternative_nearby_dates"):
        return True
    mode = str(answers.get("date_mode") or "anytime")
    if mode == "anytime":
        return True
    out = str(offer.get("outbound_date") or "")[:7]
    ret = str(offer.get("return_date") or "")[:7]
    if mode == "month":
        req_out = str(answers.get("outbound_month") or answers.get("travel_month") or "")[:7]
        req_ret = str(answers.get("return_month") or req_out)[:7]
    elif mode == "exact":
        req_out = str(answers.get("departure_date") or "")[:7]
        req_ret = str(answers.get("return_date") or "")[:7]
    else:
        return True
    return _month_distance(out, req_out) <= 1 and _month_distance(ret, req_ret) <= 1

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
        # In open searches the customer's vacation-style choices are the first
        # signal for *where* Ariella should send them; deal quality then breaks ties.
        return deal_score + (_holiday_preference_score(offer, trip) * 2.5) - budget_penalty

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
        by_id = {
            int(o.get("offer_id") or o.get("id")): o
            for o in all_offers
            if (o.get("offer_id") or o.get("id")) is not None
        }
        for oid in pinned_ids:
            offer = by_id.get(oid)
            if not offer or not _offer_is_recent(offer, 48):
                continue
            copy = _decorate_availability_note(offer, trip)
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
            copy = _decorate_availability_note(offer, trip)
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


def _requested_passenger_count(trip):
    answers = trip.get("answers") or {}
    try:
        return max(1, int(answers.get("adults") or 1) + int(answers.get("children") or 0))
    except (TypeError, ValueError):
        return 1


def _decorate_availability_note(offer, trip):
    """Never promise group inventory unless the supplier explicitly confirmed it."""
    copy = dict(offer)
    pax = _requested_passenger_count(trip)
    available = copy.get("available_seats")
    verified = copy.get("availability_verified") is True
    copy["requested_passengers"] = pax
    if pax > 1 and (not verified or not isinstance(available, (int, float)) or int(available) < pax):
        copy["availability_note_he"] = "יש לוודא מול ספק ההזמנה שיש מספיק מקומות לכל הנוסעים לפני השלמת ההזמנה."
        copy["availability_note_en"] = "Please confirm with the booking provider that enough seats remain for all travelers before completing the booking."
    return copy


def _standard_match_details(offer, trip):
    """Return transparent match points for a regular/ski personal request.

    Destination and freshness are handled before this function. Dates, budget,
    direct/baggage preferences are deliberately soft so Ariella can rank the
    closest useful alternatives rather than returning an empty page.
    """
    answers = trip.get("answers") or {}
    points = possible = 0
    matched, missed = [], []
    def add(ok, he, en, weight=1):
        nonlocal points, possible
        weight=max(1,int(weight))
        possible += weight
        (matched if ok else missed).append(en if _lang()=="en" else he)
        if ok: points += weight

    date_mode = str(answers.get("date_mode") or "anytime")
    if date_mode == "exact":
        req_out=_date_from_iso(answers.get("departure_date")); req_ret=_date_from_iso(answers.get("return_date"))
        off_out=_date_from_iso(offer.get("outbound_date")); off_ret=_date_from_iso(offer.get("return_date"))
        try: flex=max(0,min(3,int(answers.get("date_flex_days") or 0)))
        except (TypeError,ValueError): flex=0
        date_weight = 3 if "dates" in {str(x) for x in (answers.get("deal_priorities") or [])} else 1
        add(bool(req_out and off_out and abs((off_out-req_out).days)<=flex), "תאריך יציאה", "Departure date", date_weight)
        add(bool(req_ret and off_ret and abs((off_ret-req_ret).days)<=flex), "תאריך חזרה", "Return date", date_weight)
    elif date_mode == "month":
        om=str(answers.get("outbound_month") or answers.get("travel_month") or "")[:7]
        rm=str(answers.get("return_month") or om)[:7]
        date_weight = 3 if "dates" in {str(x) for x in (answers.get("deal_priorities") or [])} else 1
        add(bool(om and str(offer.get("outbound_date") or "").startswith(om)), "חודש יציאה", "Departure month", date_weight)
        add(bool(rm and str(offer.get("return_date") or "").startswith(rm)), "חודש חזרה", "Return month", date_weight)

    if answers.get("budget_mode") == "per_person" and answers.get("budget_amount"):
        try: add(float(offer.get("price_ils") or 0) <= float(answers.get("budget_amount"))*1.10, "תקציב", "Budget")
        except (TypeError,ValueError): pass

    priorities={str(x) for x in (answers.get("deal_priorities") or [])}
    if "direct" in priorities: add(int(offer.get("stops") or 0)==0, "טיסה ישירה", "Direct flight")
    if "baggage" in priorities:
        b=offer.get("baggage") or {}; carry=(b.get("carry_on_8kg") or {}).get("included") is True; checked=(b.get("checked_bag_23kg") or {}).get("included") is True
        add(carry or checked, "כבודה", "Baggage")
    return points, possible, matched, missed


def _customer_alternative_choices(all_offers, trip, exclude=None, limit=5):
    """Closest same-destination offers in the 48h inventory, ranked by request fit."""
    exclude=set(exclude or [])
    answers=trip.get("answers") or {}; vacation_type=str(answers.get("vacation_type") or "standard")
    prepared=[_decorate_ski_offer(o,trip) for o in all_offers]
    ranked=[]
    for o in prepared:
        if not _offer_is_recent(o,48) or not _offer_destination_matches(o,trip) or not _offer_has_complete_roundtrip(o): continue
        if not _within_primary_date_window(o, trip): continue
        if not _offer_matches_vacation_type(o,trip) or not _ski_offer_constraints_ok(o,trip): continue
        sig=_offer_signature(o)
        if sig in exclude: continue
        points, possible, matched, missed=_standard_match_details(o,trip)
        ratio=(points/possible) if possible else 1.0
        ranked.append((-ratio,-points,-_customer_rank_value(o,trip),float(o.get("price_ils") or 10**9),o,matched,missed))
    ranked.sort(key=lambda x:x[:4])
    out=[]
    for _,_,_,_,o,matched,missed in ranked[:limit]:
        c=_decorate_availability_note(o,trip)
        c["request_match_reasons"]=matched; c["request_missed_reasons"]=missed
        c["customer_choice_label_he"]="אפשרות קרובה לבקשה שלך"; c["customer_choice_label_en"]="A close match to your request"
        out.append(c)
    return out


def _trip_constraints_summary(trip):
    """Extra customer selections for My Vacations.

    Dates, travelers and budget are already rendered immediately above this block,
    so they are deliberately not repeated here.
    """
    a=trip.get("answers") or {}; out=[]; en=_lang()=="en"

    # Destination/search mode (the destination itself is already the card title).
    destination_mode=str(a.get("destination_mode") or "")
    destination_labels={
        "single":("One destination","יעד אחד"),
        "multiple":("Several destinations","כמה יעדים"),
        "ariella":("Let Ariella choose","אריאלה תבחר"),
        "anywhere":("Let Ariella choose","אריאלה תבחר"),
    }
    if destination_mode in destination_labels:
        out.append(("Destination search" if en else "חיפוש יעד", destination_labels[destination_mode][0 if en else 1]))

    # Date flexibility is useful context, without repeating the actual dates/months.
    dm=str(a.get("date_mode") or "")
    flex=a.get("date_flex_days")
    if dm=="exact" and flex:
        out.append(("Date flexibility" if en else "גמישות בתאריכים", f"±{flex} {'days' if en else 'ימים'}"))
    elif dm in {"anytime","ski_flexible"}:
        out.append(("Date flexibility" if en else "גמישות בתאריכים", "Any time" if en else "לא משנה / אריאלה תבחר"))

    if a.get("travel_party")=="friends" and a.get("friends_age_group"):
        m={"youth":("Youth / young adults","נוער / צעירים"),"adults":("Adults","מבוגרים"),"seniors":("Seniors","הגיל השלישי")}
        v=m.get(str(a.get("friends_age_group")))
        if v: out.append(("Group" if en else "סוג קבוצה",v[0 if en else 1]))

    holiday=list(a.get("holiday_priorities") or [])
    if holiday:
        holiday_labels={
            "price":("Good price","מחיר משתלם"),"beach":("Beach & relaxation","בטן־גב"),
            "nature":("Nature & scenery","טבע ונופים"),"hiking":("Hiking & touring","מסלולים וטיולים"),
            "city":("Cities & culture","ערים ותרבות"),"family":("Kids' attractions","אטרקציות לילדים"),
            "food":("Food & cuisine","אוכל וקולינריה"),"shopping":("Shopping","קניות"),
            "quiet":("Less crowded","יעד פחות עמוס"),"weather":("Pleasant weather","מזג אוויר נעים"),
            "nightlife":("Nightlife","חיי לילה"),"relax":("Relaxation","רוגע ופינוק"),
        }
        vals=[]
        for x in holiday:
            pair=holiday_labels.get(str(x),(str(x),str(x))); vals.append(pair[0 if en else 1])
        out.append(("Vacation preferences" if en else "מה מחפשים בחופשה", " · ".join(vals)))

    priorities=list(a.get("deal_priorities") or [])
    labels={
        "dates":("Selected dates","התאריכים שנבחרו"),
        "direct":("Direct flight","טיסה ישירה"),
        "baggage":("Baggage","כבודה"),
        "price":("Price","מחיר"),
        "maximize":("Maximize the vacation","למקסם את החופשה"),
        "balanced":("Let Ariella choose","תנו לאריאלה לבחור"),
    }
    chosen=[]
    for key in ("dates","direct","baggage","price","maximize","balanced"):
        if key in priorities: chosen.append(labels[key][0 if en else 1])
    if chosen:
        out.append(("What matters" if en else "מה חשוב", " · ".join(chosen)))

    origins=list(a.get("origin_airports") or [])
    if origins:
        out.append(("Departure airports" if en else "שדות יציאה", " · ".join(map(str,origins))))

    needs=list(a.get("special_needs") or [])
    if needs:
        special={
            "kosher":("Kosher","אוכל כשר"),"shabbat":("Shabbat observance","שמירת שבת"),
            "accessible":("Accessibility","נגישות"),"stroller":("Stroller","עגלה"),
            "walking":("Walking limitation","מגבלת הליכה"),"vegetarian":("Vegetarian / vegan","צמחוני/טבעוני"),
        }
        vals=[]
        for x in needs:
            pair=special.get(x,(str(x),str(x))); vals.append(pair[0 if en else 1])
        out.append(("Needs" if en else "צרכים", " · ".join(vals)))

    notes=str(a.get("notes") or "").strip()
    if notes:
        out.append(("Notes" if en else "הערות",notes))
    return out

def _customer_deal_choices(all_offers, trip, limit=5):
    """DB-first selection. Exact regular requests stay exact; business requests are ranked by points."""
    answers = trip.get("answers") or {}
    vacation_type = str(answers.get("vacation_type") or "standard")
    prepared = [_decorate_ski_offer(o, trip) for o in all_offers]
    if vacation_type == "business":
        prepared = [_decorate_business_offer(o, trip) for o in prepared]

    qualified = []
    for o in prepared:
        if not _offer_is_recent(o, 48):
            continue
        if not _offer_destination_matches(o, trip):
            continue
        if not _offer_has_complete_roundtrip(o):
            continue
        if not _offer_matches_vacation_type(o, trip):
            continue
        if vacation_type == "business":
            if not _business_offer_date_relevant(o, trip):
                continue
            qualified.append(o)
            continue
        if not _offer_within_budget(o, trip):
            continue
        if not _offer_meets_selected_conditions(o, trip):
            continue
        if not _ski_offer_constraints_ok(o, trip):
            continue
        qualified.append(o)

    if vacation_type == "business":
        qualified.sort(key=lambda o: _business_sort_key(o, trip))
        return [_decorate_business_offer(o, trip) for o in qualified[:limit]]

    date_mode = str(answers.get("date_mode") or "anytime")
    if date_mode == "exact":
        candidates = [o for o in qualified if _offer_matches_trip(o, trip, exact_dates=True)]
    elif date_mode == "month":
        candidates = [o for o in qualified if _offer_matches_trip(o, trip, same_month=True)]
    else:
        candidates = list(qualified)

    candidates.sort(key=lambda o: _priority_sort_key(o, trip))
    selected, seen = [], set()

    def add(offer, label_he, label_en):
        sig = _offer_signature(offer)
        if sig in seen or len(selected) >= limit:
            return
        copy = _decorate_availability_note(offer, trip)
        copy["customer_choice_label_he"] = label_he
        copy["customer_choice_label_en"] = label_en
        selected.append(copy); seen.add(sig)

    if not candidates:
        return []

    add(candidates[0], "הבחירה של אריאלה", "Ariella's choice")
    remaining = [o for o in candidates if _offer_signature(o) not in seen]
    if remaining:
        cheapest = min(remaining, key=lambda o: (float(o.get("price_ils") or 10**9), -int(o.get("score") or 0)))
        add(cheapest, "אפשרות משתלמת", "Good value option")
    remaining = [o for o in remaining if _offer_signature(o) not in seen]
    if remaining:
        best_time = max(remaining, key=lambda o: (int(o.get("time_value_score") or 0), int(o.get("score") or 0)))
        add(best_time, "הכי הרבה זמן ביעד", "Most time at destination")
    for offer in candidates:
        add(offer, "אפשרות נוספת ששווה לשקול", "Another option worth considering")
    return selected[:limit]


def _public_best_available(limit=30):
    """Public feed: target 70+, but always keep up to five useful deals down to 60."""
    recent=[_localize_offer_airports(o) for o in recent_offers(limit=300,minimum_score=60) if _offer_is_publicly_bookable(o) and _offer_is_recent(o,48)]
    recent.sort(key=lambda o:(-int(o.get("score") or 0),float(o.get("price_ils") or 10**9)))
    strong=[o for o in recent if int(o.get("score") or 0)>=MIN_DEAL_SCORE]
    if len(strong)>=5: chosen=strong
    else:
        chosen=list(strong)
        for floor in (65,60):
            for o in recent:
                if o in chosen: continue
                sc=int(o.get("score") or 0)
                if floor <= sc < (70 if floor==65 else 65): chosen.append(o)
                if len(chosen)>=5: break
            if len(chosen)>=5: break
    return chosen[:limit]


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

    offers = _public_best_available(limit=3)
    return render_template("home.html", offers=offers)


@site.get("/deals")
def deals():
    candidates = _public_best_available(limit=120)
    # Single source of truth for BOTH current and previous public deals.
    # Filter after localization/mapping so no legacy partial offer can leak into
    # "previous deals" through a later list split.
    all_qualified = [o for o in candidates if _offer_is_publicly_bookable(o)]

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

    offers = [
        o for o in all_qualified
        if _offer_is_publicly_bookable(o)
        and o.get("scan_run_id") is not None
        and int(o.get("scan_run_id")) in today_scan_ids
    ]
    previous_offers = [
        o for o in all_qualified
        if _offer_is_publicly_bookable(o) and o not in offers
    ][:30]
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
        database_offers = [_localize_offer_airports(o) for o in recent_offers(limit=1500, minimum_score=None)] + _qa_fixture_offers()
        for row in rows:
            trip = _trip_dict(row)
            try:
                trip["offers"] = _resolved_trip_offers(database_offers, trip, limit=5)
            except Exception:
                trip["offers"] = []
            exact_sigs = {_offer_signature(o) for o in trip["offers"]}
            try:
                trip["alternative_offers"] = _customer_alternative_choices(
                    database_offers + _qa_fixture_offers(), trip, exclude=exact_sigs, limit=5
                )
            except Exception:
                trip["alternative_offers"] = []
            try:
                inventory = _customer_inventory_status(database_offers, trip)
            except Exception:
                inventory = {"has_incomplete_inventory": False}
            trip["database_match_found"] = bool(trip["offers"])
            trip["needs_fresh_search"] = not bool(trip["offers"] or trip["alternative_offers"])
            trip["has_incomplete_inventory"] = inventory.get("has_incomplete_inventory", False)
            personal_trips.append(trip)
    # FINAL QA GATE: sanitize both lists immediately before rendering.
    offers = [o for o in offers if _strict_public_offer(o)]
    previous_offers = [o for o in previous_offers if _strict_public_offer(o)]
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
    """BOOKER: send the customer to the safest actionable booking flow."""
    offer = next(
        (o for o in recent_offers(limit=1500, minimum_score=None)
         if int(o.get("id") or o.get("offer_id") or 0) == offer_id),
        None,
    )
    if not offer or not _offer_is_publicly_bookable(offer):
        return redirect(url_for("site.deals"))

    target = resolve_booking_target(offer)

    record_booking_click(
        visitor_id=session.get("_ariella_visitor_id"),
        member_id=session.get("member_id"),
        offer_id=offer_id,
        destination_code=offer.get("arrival_code"),
        airline=offer.get("airline"),
        supplier=target.supplier or offer.get("booking_supplier"),
        price_ils=offer.get("price_ils"),
        score=offer.get("score"),
        outbound_date=offer.get("outbound_date"),
        return_date=offer.get("return_date"),
        booking_url=target.url or offer.get("booking_url"),
    )

    if target.url and target.fields:
        return render_template(
            "booking_forward.html",
            action=target.url,
            fields=target.fields,
        )
    if target.url:
        return redirect(target.url)
    return redirect(url_for("site.deals"))


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
        try:
            trip["offers"] = _resolved_trip_offers(database_offers, trip, limit=5)
        except Exception:
            # One malformed/legacy vacation must never take down "My Vacations".
            trip["offers"] = []
        exact_sigs={_offer_signature(o) for o in trip["offers"]}
        try:
            trip["alternative_offers"] = _customer_alternative_choices(database_offers + _qa_fixture_offers(), trip, exclude=exact_sigs, limit=5)
        except Exception:
            trip["alternative_offers"] = []
        trip["no_exact_matches"] = not bool(trip["offers"]) and bool(trip["alternative_offers"])
        try:
            trip["constraints_summary"] = _trip_constraints_summary(trip)
        except Exception:
            trip["constraints_summary"] = []
        trip["over_budget_offers"] = []
        trip["budget_fallback"] = False
        trip["closest_fallback_offers"] = []
        trip["nearby_dates_exhausted"] = bool((trip.get("answers") or {}).get("_nearby_dates_exhausted"))
        if not trip["offers"] and not trip["alternative_offers"] and (trip.get("answers") or {}).get("budget_mode") == "per_person":
            trip["over_budget_offers"] = _over_budget_alternatives(database_offers + _qa_fixture_offers(), trip, limit=3)
            trip["budget_fallback"] = bool(trip["over_budget_offers"])
        if not trip["offers"] and not trip["alternative_offers"] and not trip["budget_fallback"] and (trip.get("answers") or {}).get("_show_closest_fallback"):
            trip["closest_fallback_offers"] = _closest_condition_matches(database_offers + _qa_fixture_offers(), trip, limit=3)
        try:
            inventory = _customer_inventory_status(database_offers, trip)
        except Exception:
            inventory = {"has_incomplete_inventory": False}
        trip["needs_fresh_search"] = not bool(trip["offers"] or trip["alternative_offers"])
        trip["has_incomplete_inventory"] = inventory.get("has_incomplete_inventory", False)
        answers = trip.get("answers") or {}
        try:
            destination_codes = sorted(_trip_destination_codes(trip))
        except Exception:
            destination_codes = []
        destination_info = _AIRPORT_LOCALIZATION.get(destination_codes[0], {}) if destination_codes else {}
        if str(answers.get("vacation_type") or "") == "ski":
            ski_labels = answers.get("ski_target_labels") or []
            trip["destination_display"] = " • ".join(ski_labels) if ski_labels else _msg("אריאלה תבחר אתר סקי", "Ariella chooses a ski resort")
        elif destination_codes:
            labels = []
            for code in destination_codes:
                info = _AIRPORT_LOCALIZATION.get(code, {})
                city_he = info.get("city_he") or code
                city_en = info.get("city_en") or code
                labels.append(f"{city_en} ({code})" if _lang() == "en" else f"{city_he} ({code})")
            trip["destination_display"] = " • ".join(labels)
        else:
            trip["destination_display"] = _msg("אריאלה תמליץ", "Ariella recommends")

        if str(answers.get("vacation_type") or "") == "ski":
            trip["image_url"] = "https://images.unsplash.com/photo-1454496522488-7a8e488e8606?auto=format&fit=crop&w=900&q=82"
        elif len(destination_codes) > 1:
            # Multiple destinations: neutral green mountain/nature image. Snow is reserved for ski.
            trip["image_url"] = "https://images.unsplash.com/photo-1470770841072-f978cf4d019e?auto=format&fit=crop&w=900&q=82"
        elif destination_codes:
            dedicated = {
                "OTP": "https://images.unsplash.com/photo-1584646098378-0874589d76b1?auto=format&fit=crop&w=900&q=82",
                "ZRH": "https://images.unsplash.com/photo-1527668752968-14dc70a27c95?auto=format&fit=crop&w=900&q=82",
                "KRK": "https://images.unsplash.com/photo-1519197924294-4ba991a11128?auto=format&fit=crop&w=900&q=82",
                "LCA": "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=900&q=82",
                "ATH": "https://images.unsplash.com/photo-1555993539-1732b0258235?auto=format&fit=crop&w=900&q=82",
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



def _recent_inventory_48h():
    offers = [
        _localize_offer_airports(o)
        for o in recent_offers(limit=2000, minimum_score=None)
        if _offer_is_recent(o, 48)
    ] + _qa_fixture_offers()
    offers.sort(key=lambda o: _offer_seen_at(o) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return offers


def _same_destination_other_dates_db_matches(inventory, trip, limit=5):
    answers = trip.get("answers") or {}
    requested = _trip_destination_codes(trip)
    if not requested:
        return []
    matches = []
    for o in inventory:
        if str(o.get("arrival_code") or "").upper() not in requested:
            continue
        if not _offer_has_complete_roundtrip(o):
            continue
        # Same destination but deliberately NOT the original requested dates/month.
        if answers.get("date_mode") == "exact":
            same_original = (
                str(o.get("outbound_date") or "") == str(answers.get("departure_date") or "")
                and str(o.get("return_date") or "") == str(answers.get("return_date") or "")
            )
            if same_original:
                continue
        elif answers.get("date_mode") == "month":
            out_month = str(answers.get("outbound_month") or answers.get("travel_month") or "")[:7]
            ret_month = str(answers.get("return_month") or out_month)[:7]
            same_original = (
                str(o.get("outbound_date") or "").startswith(out_month)
                and str(o.get("return_date") or "").startswith(ret_month)
            )
            if same_original:
                continue
        matches.append(o)
    matches.sort(key=lambda o: (-_customer_rank_value(o, trip), float(o.get("price_ils") or 10**9)))
    return matches[:limit]


def _same_dates_other_destination_db_matches(inventory, trip, limit=5):
    answers = trip.get("answers") or {}
    requested = _trip_destination_codes(trip)
    matches = []
    for o in inventory:
        code = str(o.get("arrival_code") or "").upper()
        if not code or code in requested:
            continue
        if not _offer_has_complete_roundtrip(o):
            continue
        if answers.get("date_mode") == "exact":
            if str(o.get("outbound_date") or "") != str(answers.get("departure_date") or ""):
                continue
            if str(o.get("return_date") or "") != str(answers.get("return_date") or ""):
                continue
        elif answers.get("date_mode") == "month":
            out_month = str(answers.get("outbound_month") or answers.get("travel_month") or "")[:7]
            ret_month = str(answers.get("return_month") or out_month)[:7]
            if out_month and not str(o.get("outbound_date") or "").startswith(out_month):
                continue
            if ret_month and not str(o.get("return_date") or "").startswith(ret_month):
                continue
        matches.append(o)
    matches.sort(key=lambda o: (-int(o.get("score") or 0), float(o.get("price_ils") or 10**9)))
    return matches[:limit]


def _month_shift(month_value, delta):
    try:
        y, m = [int(x) for x in str(month_value)[:7].split("-")]
        total = y * 12 + (m - 1) + int(delta)
        return f"{total // 12:04d}-{total % 12 + 1:02d}"
    except Exception:
        return ""


def _pin_offer_ids_to_trip(trip_id, answers, offers):
    ids = [
        int(o.get("offer_id") or o.get("id"))
        for o in offers
        if (o.get("offer_id") or o.get("id")) is not None
    ][:5]
    if ids:
        answers["_matched_offer_ids"] = ids
    with _db() as conn:
        conn.execute(
            "UPDATE trip_requests SET answers_json=? WHERE id=?",
            (json.dumps(answers, ensure_ascii=False), trip_id),
        )
        conn.commit()
    return ids


@site.post("/trip/<int:trip_id>/free-alternative")
@login_required
def free_trip_alternative(trip_id):
    """DB-first alternative search. API is used only when 48h inventory has no match."""
    choice = request.form.get("alternative", "").strip()
    if choice not in {"nearby_dates", "other_destination"}:
        return redirect(url_for("site.account") + f"#vacation-{trip_id}")

    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM trip_requests WHERE id=? AND member_id=?",
            (trip_id, session["member_id"]),
        ).fetchone()
        if not row:
            return redirect(url_for("site.account"))
        trip = _trip_dict(row)
        answers = dict(trip.get("answers") or {})

    inventory = _recent_inventory_48h()

    # 1) SAME DESTINATION, OTHER DATES: first mine the 48h DB.
    if choice == "nearby_dates":
        db_matches = _same_destination_other_dates_db_matches(inventory, trip, limit=5)
        if db_matches:
            _pin_offer_ids_to_trip(trip_id, answers, db_matches)
            with _db() as conn:
                conn.execute(
                    "UPDATE trip_requests SET free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
                    (utc_now_iso(), "database_alternative_match", trip_id),
                )
                conn.commit()
            return redirect(url_for("site.account") + f"#vacation-{trip_id}")

        # No DB match: record that DB-first completed, then widen the scan.
        with _db() as conn:
            conn.execute(
                "UPDATE trip_requests SET free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
                (utc_now_iso(), "db_checked_48h_no_nearby_match", trip_id),
            )
            conn.commit()

        if answers.get("date_mode") == "exact":
            try:
                answers["_original_date_mode"] = answers.get("date_mode")
                answers["_original_departure_date"] = answers.get("departure_date")
                answers["_original_return_date"] = answers.get("return_date")
                answers["_original_outbound_month"] = answers.get("outbound_month")
                answers["_original_return_month"] = answers.get("return_month")
                out = datetime.strptime(answers.get("departure_date"), "%Y-%m-%d").date()
                ret = datetime.strptime(answers.get("return_date"), "%Y-%m-%d").date()
                span = max(1, (ret - out).days)
                base_month = out.strftime("%Y-%m")
                requested_ret_month = ret.strftime("%Y-%m")
                answers["date_mode"] = "month"
                answers["outbound_month"] = base_month
                answers["return_month"] = requested_ret_month
                answers["travel_month"] = base_month
                answers["_alternative_nearby_dates"] = True
                answers["_alternative_outbound_months"] = [_month_shift(base_month,-1), base_month, _month_shift(base_month,1)]
                answers["_alternative_return_months"] = [_month_shift(requested_ret_month,-1), requested_ret_month, _month_shift(requested_ret_month,1)]
                answers["_alternative_months"] = sorted(set(answers["_alternative_outbound_months"] + answers["_alternative_return_months"]))
                answers["_requested_trip_length_days"] = span
            except Exception:
                return redirect(url_for("site.account") + f"#vacation-{trip_id}")
        elif answers.get("date_mode") == "month":
            answers["_original_date_mode"] = answers.get("date_mode")
            answers["_original_departure_date"] = answers.get("departure_date")
            answers["_original_return_date"] = answers.get("return_date")
            answers["_original_outbound_month"] = answers.get("outbound_month")
            answers["_original_return_month"] = answers.get("return_month")
            base_month = str(answers.get("outbound_month") or answers.get("travel_month") or "")[:7]
            if not base_month:
                return redirect(url_for("site.account") + f"#vacation-{trip_id}")
            answers["_alternative_nearby_dates"] = True
            ret_month = str(answers.get("return_month") or base_month)[:7]
            answers["_alternative_outbound_months"] = [_month_shift(base_month,-1), base_month, _month_shift(base_month,1)]
            answers["_alternative_return_months"] = [_month_shift(ret_month,-1), ret_month, _month_shift(ret_month,1)]
            answers["_alternative_months"] = sorted(set(answers["_alternative_outbound_months"] + answers["_alternative_return_months"]))
        else:
            return redirect(url_for("site.account") + f"#vacation-{trip_id}")

    # 2) SAME DATES, OTHER DESTINATION: first mine the 48h DB.
    else:
        db_matches = _same_dates_other_destination_db_matches(inventory, trip, limit=5)
        if db_matches:
            _pin_offer_ids_to_trip(trip_id, answers, db_matches)
            with _db() as conn:
                conn.execute(
                    "UPDATE trip_requests SET free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
                    (utc_now_iso(), "database_other_destination_match", trip_id),
                )
                conn.commit()
            return redirect(url_for("site.account") + f"#vacation-{trip_id}")

        # No exact DB match for another destination. Before spending API quota,
        # show the closest existing 48h options ranked by how many customer conditions they meet.
        answers["_show_closest_fallback"] = True
        answers["_alternative_other_destination"] = True
        with _db() as conn:
            conn.execute(
                "UPDATE trip_requests SET answers_json=?, free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
                (json.dumps(answers, ensure_ascii=False), utc_now_iso(), "closest_db_fallback", trip_id),
            )
            conn.commit()
        return redirect(url_for("site.account") + f"#vacation-{trip_id}")

    try:
        scan_result = run_customer_trip_search(trip_id, answers)
    except Exception:
        # Never return a raw Flask 500 to the customer.
        with _db() as conn:
            conn.execute(
                "UPDATE trip_requests SET free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
                (utc_now_iso(), "search_error", trip_id),
            )
            conn.commit()
        return redirect(url_for("site.account") + f"#vacation-{trip_id}")

    refreshed = _recent_inventory_48h()
    created_for_trip = []
    for o in refreshed:
        try:
            if int(o.get("trip_id")) == trip_id and _offer_has_complete_roundtrip(o):
                created_for_trip.append(o)
        except (TypeError, ValueError):
            pass

    if choice == "nearby_dates" and answers.get("_original_date_mode"):
        answers["date_mode"] = answers.pop("_original_date_mode", answers.get("date_mode"))
        answers["departure_date"] = answers.pop("_original_departure_date", answers.get("departure_date"))
        answers["return_date"] = answers.pop("_original_return_date", answers.get("return_date"))
        answers["outbound_month"] = answers.pop("_original_outbound_month", answers.get("outbound_month"))
        answers["return_month"] = answers.pop("_original_return_month", answers.get("return_month"))
        answers["travel_month"] = answers.get("outbound_month") or answers.get("travel_month")
        answers.pop("_alternative_nearby_dates", None)
        answers.pop("_alternative_months", None)
        answers.pop("_alternative_outbound_months", None)
        answers.pop("_alternative_return_months", None)
        answers.pop("_requested_trip_length_days", None)

    if created_for_trip:
        _pin_offer_ids_to_trip(trip_id, answers, created_for_trip)
    else:
        # If "same destination / other dates" was exhausted, do not show that
        # same question again. The next useful step is "other destination / same dates".
        if choice == "nearby_dates":
            answers["_nearby_dates_exhausted"] = True
        with _db() as conn:
            conn.execute(
                "UPDATE trip_requests SET answers_json=? WHERE id=?",
                (json.dumps(answers, ensure_ascii=False), trip_id),
            )
            conn.commit()

    with _db() as conn:
        conn.execute(
            "UPDATE trip_requests SET free_scan_count=COALESCE(free_scan_count,0)+1, free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
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
    def form_context():
        today_value = date.today().isoformat()
        return {
            "today": today_value,
            "current_month": today_value[:7],
            "ski_options": _ski_picker_options(),
        }

    if request.method == "POST":
        form = request.form
        ctx = form_context()
        today = ctx["today"]
        current_month = ctx["current_month"]

        raw_vacation_type = form.get("vacation_type")
        vacation_type = raw_vacation_type if raw_vacation_type in {"standard","ski","business"} else "standard"
        business_extra = {}

        # ---------------- Separate REGULAR / SKI / BUSINESS questionnaires ----------------
        if vacation_type == "ski":
            destination_mode = form.get("ski_destination_mode", "open")
            ski_targets = form.getlist("ski_targets")
            ski_skill_level = form.get("ski_skill_level", "").strip()
            ski_transfer_choice = form.get("ski_transfer_choice", "any").strip()
            ski_max_transfer_minutes = {"90": 90, "180": 180}.get(ski_transfer_choice)
            resolved = _resolve_ski_targets(
                ski_targets, destination_mode,
                skill_level=ski_skill_level or None,
                max_transfer_minutes=ski_max_transfer_minutes,
            )

            if destination_mode in {"specific", "several"} and not ski_targets:
                flash(_msg("יש לבחור אתר סקי, אזור או מדינה.", "Please choose a ski resort, region or country."), "error")
                return render_template("trip_form.html", **ctx)
            if not resolved["resorts"]:
                flash(_msg("לא נמצאו אתרי סקי שמתאימים לבחירה. נסו להרחיב את ההגדרות.", "No ski resorts match these choices. Please widen the criteria."), "error")
                return render_template("trip_form.html", **ctx)

            # The flight engine works with airport codes; Ski DB narrows the resort search first.
            destinations = ",".join(resolved["gateway_airports"])
            ski_target_labels = []
            for raw in ski_targets:
                if raw.startswith("resort:"):
                    ski_target_labels.append(raw.split(":",1)[1])
                elif raw.startswith("country:"):
                    country = raw.split(":",1)[1]
                    row = next((r for r in _SKI_RESORTS if r.get("country")==country), None)
                    ski_target_labels.append((row or {}).get("country_he") or country)

            date_mode = form.get("ski_date_mode", "ski_flexible")
            outbound_month = form.get("ski_outbound_month", "").strip()
            return_month = form.get("ski_return_month", "").strip()
            departure_date = form.get("ski_departure_date", "").strip()
            return_date = form.get("ski_return_date", "").strip()

            travel_party = form.get("ski_travel_party")
            adults = form.get("ski_family_adults") if travel_party == "family" else form.get("ski_adults")
            if travel_party == "solo":
                adults = "1"
            elif travel_party == "couple":
                adults = "2"

            children = form.get("ski_children")
            age_groups = form.getlist("ski_age_groups")
            if travel_party == "friends" and form.get("ski_friends_age_group"):
                age_groups = [form.get("ski_friends_age_group")]
            holiday_priorities = []
            deal_priorities = []
            ski_priorities = form.getlist("ski_priorities")

            budget_mode = form.get("ski_budget_mode", "unlimited")
            budget_amount = form.get("ski_budget_amount", "").strip()
            # "all_flights" is normalized to a per-person ceiling for the flight engine.
            if budget_mode == "all_flights":
                try:
                    pax = max(1, int(adults or 1) + int(children or 0))
                    budget_amount = str(round(float(budget_amount) / pax, 2))
                    budget_mode = "per_person"
                except (TypeError, ValueError):
                    budget_mode = "unlimited"
                    budget_amount = ""
            elif budget_mode not in {"per_person", "unlimited"}:
                budget_mode = "unlimited"
                budget_amount = ""

            special_needs = []
            notes = form.get("ski_notes", "").strip()
            try:
                date_flex_days = max(0, min(3, int(form.get("ski_date_flex_days") or 0))) if form.get("ski_date_flexible") == "1" else 0
            except (TypeError, ValueError):
                date_flex_days = 0
        elif vacation_type == "business":
            destination_mode = form.get("business_destination_mode", "specific")
            destinations = form.get("business_destinations", "").strip()
            if destination_mode in {"specific", "several"} and not destinations:
                flash(_msg("יש לבחור יעד או יעדים לטיסת העסקים.", "Please choose one or more business-trip destinations."), "error")
                return render_template("trip_form.html", **ctx)

            ski_targets = []
            ski_target_labels = []
            ski_skill_level = ""
            ski_max_transfer_minutes = None
            ski_priorities = []
            holiday_priorities = []
            deal_priorities = []

            date_mode = "exact"
            outbound_month = return_month = ""
            departure_date = form.get("business_departure_date", "").strip()
            return_date = form.get("business_return_date", "").strip()

            travel_party = "business"
            adults = form.get("business_travelers", "1").strip() or "1"
            children = "0"
            age_groups = []

            budget_mode = form.get("business_budget_mode", "unlimited")
            if budget_mode not in {"per_person", "unlimited"}:
                budget_mode = "unlimited"
            budget_amount = form.get("business_budget_amount", "").strip() if budget_mode == "per_person" else ""
            special_needs = []
            notes = form.get("business_notes", "").strip()

            try:
                flex_days = max(0, min(3, int(form.get("business_flex_days") or 0))) if form.get("business_flexible_dates") == "1" else 0
            except (TypeError, ValueError):
                flex_days = 0
            date_flex_days = flex_days
            business_extra = {
                "business_flex_days": flex_days,
                "business_arrive_by_date": form.get("business_arrive_by_date", "").strip() if not flex_days else "",
                "business_arrive_by_time": form.get("business_arrive_by_time", "").strip() if not flex_days else "",
                "business_return_after_date": form.get("business_return_after_date", "").strip() if not flex_days else "",
                "business_return_after_time": form.get("business_return_after_time", "").strip() if not flex_days else "",
                "business_cabin_class": form.get("business_cabin_class", "any"),
                "business_priorities": form.getlist("business_priorities"),
            }
        else:
            destination_mode = form.get("destination_mode", "open")
            destinations = form.get("destinations", "").strip()
            ski_targets = []
            ski_target_labels = []
            ski_skill_level = ""
            ski_max_transfer_minutes = None
            ski_priorities = []

            date_mode = form.get("date_mode", "anytime")
            outbound_month = form.get("outbound_month", "").strip()
            return_month = form.get("return_month", "").strip()
            departure_date = form.get("departure_date", "").strip()
            return_date = form.get("return_date", "").strip()

            travel_party = form.get("travel_party")
            adults = form.get("family_adults") if travel_party == "family" else form.get("adults")
            if travel_party == "solo":
                adults = "1"
            elif travel_party == "couple":
                adults = "2"

            children = form.get("children")
            age_groups = form.getlist("age_groups")
            if travel_party == "friends" and form.get("friends_age_group"):
                age_groups = [form.get("friends_age_group")]
            holiday_priorities = form.getlist("holiday_priorities")
            deal_priorities = form.getlist("deal_priorities")
            budget_mode = form.get("budget_mode", "unlimited")
            budget_amount = form.get("budget_amount", "").strip() if budget_mode == "per_person" else ""
            special_needs = form.getlist("special_needs") if destination_mode != "specific" else []
            notes = form.get("notes", "").strip()
            try:
                date_flex_days = max(0, min(3, int(form.get("date_flex_days") or 0))) if form.get("date_flexible") == "1" else 0
            except (TypeError, ValueError):
                date_flex_days = 0

            if destination_mode in {"specific", "several"} and not destinations:
                flash(_msg("יש לכתוב את היעד או היעדים שמעניינים אתכם.", "Please enter the destination or destinations you are interested in."), "error")
                return render_template("trip_form.html", **ctx)

        # ---------------- Shared date validation ----------------
        if date_mode == "month":
            if not outbound_month or not return_month or outbound_month < current_month or return_month < current_month:
                flash(_msg("יש לבחור חודש יציאה וחודש חזרה נוכחיים או עתידיים.", "Please choose a current or future departure month and return month."), "error")
                return render_template("trip_form.html", **ctx)
            if return_month < outbound_month:
                flash(_msg("חודש החזרה חייב להיות זהה לחודש היציאה או מאוחר ממנו.", "The return month must be the same as or later than the departure month."), "error")
                return render_template("trip_form.html", **ctx)
        elif date_mode == "exact":
            if not departure_date or not return_date:
                flash(_msg("יש לבחור תאריך יציאה ותאריך חזרה.", "Please choose a departure date and a return date."), "error")
                return render_template("trip_form.html", **ctx)
            if departure_date < today or return_date <= departure_date:
                flash(_msg("יש לבחור תאריכים עתידיים כאשר החזרה אחרי היציאה.", "Please choose future dates with return after departure."), "error")
                return render_template("trip_form.html", **ctx)

        destination_title = destinations if destinations else (
            _msg("הצעות סקי של אריאלה", "Ariella ski suggestions")
            if vacation_type == "ski"
            else _msg("הצעות של אריאלה", "Ariella suggestions")
        )
        if vacation_type == "ski" and ski_target_labels:
            destination_title = " • ".join(ski_target_labels)

        if date_mode == "month":
            travel_window = outbound_month if outbound_month == return_month else f"{outbound_month} → {return_month}"
        elif date_mode == "exact":
            travel_window = f"{departure_date} – {return_date}"
        elif date_mode == "ski_flexible":
            travel_window = _msg("אריאלה תבחר — עונת סקי", "Ariella chooses — ski season")
        else:
            travel_window = _msg("כל השנה", "Anytime")

        member = _current_member() or {}
        profile_airports = member.get("preferred_airports_list", [])
        override_airports = [x.strip().upper() for x in form.get("origin_airports", "").replace(";", ",").split(",") if x.strip()]
        origin_selection_mode = form.get("origin_selection_mode", "default")
        origin_airports = override_airports if origin_selection_mode == "custom" else (override_airports or profile_airports)

        payload = {
            "origin_airports": origin_airports,
            "destination_mode": destination_mode,
            "vacation_type": vacation_type,
            "destinations": destinations,
            "date_mode": date_mode,
            "travel_month": outbound_month,
            "outbound_month": outbound_month,
            "return_month": return_month,
            "departure_date": departure_date,
            "return_date": return_date,
            "date_flex_days": date_flex_days,
            "travel_party": travel_party,
            "adults": adults,
            "children": children,
            "age_groups": age_groups,
            "holiday_priorities": holiday_priorities,
            "deal_priorities": deal_priorities,
            "budget_mode": budget_mode,
            "budget_amount": budget_amount,
            "special_needs": special_needs,
            "notes": notes,
            # Ski-only fields remain empty for regular vacations.
            "ski_targets": ski_targets,
            "ski_target_labels": ski_target_labels,
            "ski_skill_level": ski_skill_level,
            "ski_max_transfer_minutes": ski_max_transfer_minutes,
            "ski_priorities": ski_priorities,
        }
        payload.update(business_extra)
        if vacation_type == "ski":
            payload["ski_resort_names"] = resolved["resort_names"]
            payload["ski_countries"] = resolved["countries"]

        with _db() as conn:
            cur = conn.execute(
                "INSERT INTO trip_requests (member_id,request_name,travel_window,status,answers_json,created_at,mobile_notifications) VALUES(?,?,?,?,?,?,?)",
                (session["member_id"], destination_title, travel_window, "active", json.dumps(payload, ensure_ascii=False), utc_now_iso(), 0),
            )
            trip_id = int(cur.lastrowid)
            conn.commit()

        trip_for_match = {"id": trip_id, "answers": payload, "request_name": destination_title, "travel_window": travel_window}
        existing_inventory = [
            _localize_offer_airports(o)
            for o in recent_offers(limit=1500, minimum_score=None)
            if _offer_is_recent(o, 48)
        ] + _qa_fixture_offers()

        # Initial DB match obeys the user's exact date mode. No hidden date alternatives.
        existing_matches = _customer_deal_choices(existing_inventory, trip_for_match, limit=5)
        scan_status = "database_match" if existing_matches else "no_database_match"
        scan_count = 0

        if existing_matches:
            matched_ids = [
                int(o.get("offer_id") or o.get("id"))
                for o in existing_matches
                if (o.get("offer_id") or o.get("id")) is not None
            ]
            payload["_matched_offer_ids"] = matched_ids
            with _db() as conn:
                conn.execute(
                    "UPDATE trip_requests SET answers_json=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), trip_id),
                )
                conn.commit()

        with _db() as conn:
            conn.execute(
                "UPDATE trip_requests SET free_scan_count=?, free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
                (scan_count, utc_now_iso(), scan_status, trip_id),
            )
            conn.commit()
        return redirect(url_for("site.account") + f"#vacation-{trip_id}")

    return render_template("trip_form.html", **form_context())


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
