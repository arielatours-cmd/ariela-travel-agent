from pathlib import Path
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import random
import requests
from urllib.parse import parse_qsl
from datetime import date, datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (
    Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash

from config import DB_PATH, MIN_DEAL_SCORE, ISRAEL_TZ, SERPAPI_API_KEY
from database import recent_offers, save_feedback, utc_now_iso, record_site_event, record_booking_click, DESTINATION_LANDMARK_IMAGES, get_setting, set_setting
from destination_fit import DESTINATION_CONDITION_MONTHS, condition_met as _destination_condition_met, seasonality_met as _destination_seasonality_met
from scanner import run_customer_trip_search
from booker import resolve_booking_target
from ski_catalog import SKI_RESORTS as _EMBEDDED_SKI_RESORTS



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
    _loaded_ski = json.loads(_SKI_DB_FILE.read_text(encoding="utf-8")).get("resorts", [])
except Exception:
    _loaded_ski = []
# Never let the ski questionnaire collapse because a deployment omitted/failed to
# read the JSON data file. The embedded catalog is shipped as normal Python code.
_SKI_RESORTS = _loaded_ski if _loaded_ski else list(_EMBEDDED_SKI_RESORTS)


def _ski_picker_options():
    """Autocomplete rows: every selectable item is a real ski resort + its country.

    Searching a country therefore returns all resorts in that country instead of a
    synthetic country-only choice that cannot be shown as a vacation later.
    """
    resorts = []
    for row in _SKI_RESORTS:
        country = str(row.get("country") or "").strip()
        country_he = str(row.get("country_he") or country).strip()
        region = str(row.get("region") or "").strip()
        region_he = str(row.get("region_he") or region).strip()
        resort = str(row.get("resort") or "").strip()
        if not resort:
            continue
        resorts.append({
            "value": f"resort:{resort}",
            "label_he": f"{resort} — {country_he}",
            "label_en": f"{resort} — {country}",
            "resort": resort,
            "country": country,
            "country_he": country_he,
            "region": region,
            "region_he": region_he,
            "season_months": list(row.get("season_months") or []),
        })
    resorts.sort(key=lambda x: (x["country_he"], x["resort"]))
    return resorts


def _resolve_ski_targets(raw_values, mode, skill_level=None, max_transfer_minutes=None):
    """Resolve manual/open ski choices to resort rows and gateway airports.

    Skill level and transfer distance are ranking conditions, not reasons to erase a
    resort before ranking. Season availability is filtered separately once the dates
    are known.
    """
    selected = [str(x).strip() for x in (raw_values or []) if str(x).strip()]
    rows = list(_SKI_RESORTS)

    if mode in {"specific", "several"} and selected:
        resort_names = {x.split(":", 1)[1] for x in selected if x.startswith("resort:")}
        # Backward compatibility for older saved country selections.
        countries = {x.split(":", 1)[1] for x in selected if x.startswith("country:")}
        rows = [
            r for r in rows
            if str(r.get("resort")) in resort_names or str(r.get("country")) in countries
        ]

    names, countries = [], []
    gateway_stats = {}
    for r in rows:
        names.append(str(r.get("resort")))
        countries.append(str(r.get("country")))
        transfer = int(r.get("transfer_minutes_estimate") or 9999)
        for code in r.get("gateway_airports") or []:
            code = str(code).upper()
            if not code:
                continue
            stat = gateway_stats.setdefault(code, {"count": 0, "best_transfer": 9999})
            stat["count"] += 1
            stat["best_transfer"] = min(stat["best_transfer"], transfer)
    # In open ski searches the scanner has an API safety cap. Put gateways that
    # serve the most resorts (then the shortest transfers) first, so the first
    # controlled scan covers the broadest useful ski inventory rather than the
    # arbitrary JSON row order. Manual resort selection still keeps every gateway.
    airports = sorted(gateway_stats, key=lambda c: (-gateway_stats[c]["count"], gateway_stats[c]["best_transfer"], c))
    return {
        "resorts": rows,
        "resort_names": names,
        "countries": sorted(set(countries)),
        "gateway_airports": airports,
    }


def _ski_months_for_request(date_mode, outbound_month="", return_month="", departure_date="", return_date=""):
    values = []
    raw_values = []
    if date_mode == "month":
        raw_values = [outbound_month, return_month]
    elif date_mode == "exact":
        raw_values = [departure_date, return_date]
    for raw in raw_values:
        try:
            month = int(str(raw).strip()[5:7])
        except Exception:
            continue
        if 1 <= month <= 12 and month not in values:
            values.append(month)
    return values


def _ski_resorts_in_season(rows, months):
    if not months:
        return list(rows)
    return [r for r in rows if all(m in set(r.get("season_months") or []) for m in months)]


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

    # Transfer distance is a ranking condition. A farther resort may still be the
    # best overall match when it satisfies more of the customer's ski preferences.
    return True


def _ski_selected_condition_details(offer, trip):
    """Selected ski questionnaire conditions, each worth one transparent point."""
    answers = trip.get("answers") or {}
    scores = offer.get("ski_resort_scores") or {}
    priorities = set(answers.get("ski_priorities") or [])
    level = str(answers.get("ski_skill_level") or "")
    levels = set(offer.get("ski_resort_levels") or [])
    mins = float(offer.get("ski_transfer_minutes") or 9999)
    out = []

    if level:
        out.append((level == "mixed" or level in levels, "מתאים לרמת הגלישה", "Matches ski level"))
    transfer_choice = str(answers.get("ski_transfer_choice") or "any")
    if transfer_choice in {"90", "180"}:
        cap = 90 if transfer_choice == "90" else 180
        out.append((mins <= cap, "מרחק מתאים משדה התעופה", "Airport transfer distance"))

    labels = {
        "snow": ("snow", "סיכוי גבוה לשלג טוב", "Snow reliability"),
        "family": ("family", "מתאים למשפחות", "Family friendly"),
        "large": ("size", "אתר גדול ומגוון", "Large & varied resort"),
        "value": ("value", "מחיר משתלם", "Good value"),
        "atmosphere": ("atmosphere", "מסעדות ואווירה", "Restaurants & atmosphere"),
        "nightlife": ("nightlife", "Après-ski וחיי לילה", "Après-ski & nightlife"),
        "spa": ("spa", "ספא ופינוקים", "Spa & pampering"),
    }
    for pref in priorities:
        if pref in {"level", "proximity"}:
            continue
        if pref in labels:
            key, he, en = labels[pref]
            out.append((float(scores.get(key) or 0) >= 0.6, he, en))
    if "level" in priorities and not level:
        out.append((False, "אתר שמתאים לרמת הגלישה", "Resort fits ski level"))
    if "proximity" in priorities and transfer_choice != "any":
        cap = 90 if transfer_choice == "90" else 180
        out.append((mins <= cap, "הגעה קצרה ונוחה משדה התעופה", "Short/easy airport transfer"))
    return out


def _ski_preference_score(offer, trip):
    """Transparent ski ranking from the resort table: +1 per met condition."""
    answers = trip.get("answers") or {}
    if str(answers.get("vacation_type") or "standard") != "ski":
        return 0.0
    total = float(sum(1 for ok, _, _ in _ski_selected_condition_details(offer, trip) if ok))
    requested_months = _ski_months_for_request(
        answers.get("date_mode"), answers.get("outbound_month", ""),
        answers.get("return_month", ""), answers.get("departure_date", ""),
        answers.get("return_date", ""),
    )
    row = _ski_row_for_offer(offer, trip)
    if row and requested_months and all(m in set(row.get("season_months") or []) for m in requested_months):
        total += 1.0
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
    answers = trip.get("answers") or {}
    if answers.get("_alternative_other_destination"):
        return bool(requested) and str(offer.get("arrival_code") or "").upper() not in requested
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
    """QA inventory was retired in v9.7.122. Production/customer results use real DB offers only."""
    return []

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
        key.append(-_customer_rank_value(offer, trip))
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
        add(_offer_is_direct(offer), "טיסה ישירה", "Direct flight")
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
    original = {str(x).upper() for x in _trip_destination_codes(trip)}
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
    # Mediterranean / warm south
    "ATH": {"beach_months": {5,6,7,8,9,10}, "pleasant_months": {4,5,6,9,10,11}},
    "LCA": {"beach_months": {4,5,6,7,8,9,10,11}, "pleasant_months": {3,4,5,6,9,10,11}},
    "BCN": {"beach_months": {5,6,7,8,9,10}, "pleasant_months": {4,5,6,9,10}},
    "LIS": {"beach_months": {5,6,7,8,9,10}, "pleasant_months": {3,4,5,6,9,10,11}},
    "MAD": {"pleasant_months": {3,4,5,6,9,10,11}},
    "FCO": {"pleasant_months": {3,4,5,6,9,10,11}},
    "TGD": {"beach_months": {5,6,7,8,9}, "pleasant_months": {4,5,6,9,10}},
    "ZAG": {"hiking_months": {5,6,7,8,9,10}, "pleasant_months": {4,5,6,9,10}},
    "LJU": {"hiking_months": {5,6,7,8,9,10}, "pleasant_months": {5,6,7,8,9}},
    "SKP": {"hiking_months": {4,5,6,7,8,9,10}, "pleasant_months": {4,5,6,9,10}},
    "BEG": {"pleasant_months": {4,5,6,9,10}},
    "SOF": {"hiking_months": {5,6,7,8,9,10}, "pleasant_months": {5,6,7,8,9}},
    # Central / western Europe — pleasant-weather preference should demote deep winter.
    "BUD": {"pleasant_months": {4,5,6,9,10}},
    "VIE": {"pleasant_months": {4,5,6,9,10}},
    "PRG": {"pleasant_months": {4,5,6,9,10}},
    "MXP": {"pleasant_months": {4,5,6,9,10}},
    "CDG": {"pleasant_months": {4,5,6,9,10}},
    "AMS": {"pleasant_months": {4,5,6,7,8,9}},
    "LHR": {"pleasant_months": {5,6,7,8,9}},
    "BER": {"pleasant_months": {5,6,7,8,9}},
    "MUC": {"hiking_months": {5,6,7,8,9,10}, "pleasant_months": {5,6,7,8,9}},
    "ZRH": {"hiking_months": {5,6,7,8,9,10}, "pleasant_months": {5,6,7,8,9}},
    "BRU": {"pleasant_months": {5,6,7,8,9}},
    "OTP": {"pleasant_months": {4,5,6,9,10}},
    "KRK": {"pleasant_months": {5,6,7,8,9}},
    "WAW": {"pleasant_months": {5,6,7,8,9}},
    # Caucasus / mountains
    "TBS": {"hiking_months": {4,5,6,7,8,9,10}, "pleasant_months": {4,5,6,9,10}},
    "EVN": {"hiking_months": {5,6,7,8,9,10}, "pleasant_months": {5,6,9,10}},
    # Warm long-haul
    "BKK": {"beach_months": {1,2,3,4,11,12}, "pleasant_months": {1,2,3,11,12}},
    "JFK": {"pleasant_months": {4,5,6,9,10}},
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
    """Keep initial alternatives inside the customer's actual date tolerance."""
    answers = trip.get("answers") or {}
    if answers.get("_alternative_nearby_dates"):
        return True
    mode = str(answers.get("date_mode") or "anytime")
    if mode in {"anytime", "ski_flexible"}:
        return True
    if mode == "exact":
        try:
            req_out = datetime.strptime(str(answers.get("departure_date")), "%Y-%m-%d").date()
            req_ret = datetime.strptime(str(answers.get("return_date")), "%Y-%m-%d").date()
            off_out = datetime.strptime(str(offer.get("outbound_date"))[:10], "%Y-%m-%d").date()
            off_ret = datetime.strptime(str(offer.get("return_date"))[:10], "%Y-%m-%d").date()
            flex = max(0, min(3, int(answers.get("date_flex_days") or 0)))
        except Exception:
            return False
        if flex:
            return abs((off_out-req_out).days) <= flex and abs((off_ret-req_ret).days) <= flex
        return off_out == req_out and off_ret == req_ret
    if mode == "month":
        out = str(offer.get("outbound_date") or "")[:7]
        ret = str(offer.get("return_date") or "")[:7]
        req_out = str(answers.get("outbound_month") or answers.get("travel_month") or "")[:7]
        req_ret = str(answers.get("return_month") or req_out)[:7]
        return _month_distance(out, req_out) <= 1 and _month_distance(ret, req_ret) <= 1
    return True


def _open_flight_preference_score(offer, trip):
    """Legacy compatibility helper.

    Regular-vacation ordering no longer uses weighted preference math.  The
    authoritative customer score is _open_customer_points: one point per met
    condition, plus one seasonal-fit point.  Keep this function for callers in
    older routes, but make it equivalent to the transparent points model.
    """
    return float(_open_customer_points(offer, trip))


def _good_price_condition(offer):
    """Customer-facing 'good price' condition.

    Prefer a trustworthy historical/Google reference.  Historical observations are
    now limited to the same travel month in the last 24 months (see database.py).
    If a trustworthy reference explicitly says the fare is not good, return False.
    If no trustworthy reference exists at all, do not punish the customer for our
    missing history: treat the price condition as satisfied for full-match purposes.
    This implements the agreed fallback until Ariella accumulates enough history.
    """
    reliable = offer.get("price_reference_reliable") is True
    try:
        discount = float(offer.get("discount_percent"))
    except (TypeError, ValueError):
        discount = None
    if reliable and discount is not None:
        return discount >= 10.0

    try:
        typical_low = float(offer.get("typical_low_ils"))
        price = float(offer.get("price_ils"))
        if typical_low > 0 and price > 0:
            return price <= typical_low * 0.90
    except (TypeError, ValueError):
        pass

    # A strong normalized cost score remains a positive signal, but a low/empty
    # cost score without a reliable reference is not evidence that the fare is bad.
    try:
        if float(offer.get("cost_score") or 0) >= 65:
            return True
    except (TypeError, ValueError):
        pass
    return True


def _seasonal_condition_met(offer, trip, selected):
    """One explicit seasonality point from the destination matrix."""
    month = _requested_travel_month(trip, offer)
    return _destination_seasonality_met(str(offer.get("arrival_code") or ""), month)

def _open_customer_point_details(offer, trip):
    """Return transparent +1/0 details for every customer condition."""
    answers = trip.get("answers") or {}
    selected = [str(x) for x in (answers.get("holiday_priorities") or []) if x]
    priorities = {str(x) for x in (answers.get("deal_priorities") or []) if x}
    code = str(offer.get("arrival_code") or "").upper()
    month = _requested_travel_month(trip, offer)
    detail = {}

    for pref in selected:
        if pref == "price":
            detail[pref] = bool(_good_price_condition(offer))
        else:
            detail[pref] = bool(_destination_condition_met(code, pref, month))

    if "direct" in priorities:
        detail["direct"] = _offer_is_direct(offer)
    if "baggage" in priorities:
        bag = offer.get("baggage") or {}
        detail["baggage"] = ((bag.get("carry_on_8kg") or {}).get("included") is True or
                             (bag.get("checked_bag_23kg") or {}).get("included") is True)
    if "maximize" in priorities:
        arr = _time_minutes(offer.get("arrival_time"))
        ret = _time_minutes(offer.get("return_departure_time"))
        detail["maximize"] = arr is not None and ret is not None and arr <= 600 and ret >= 1200

    if answers.get("budget_mode") == "per_person" and answers.get("budget_amount"):
        try:
            detail["budget"] = float(offer.get("price_ils") or 0) <= float(answers.get("budget_amount")) * 1.10
        except (TypeError, ValueError):
            detail["budget"] = False

    try:
        is_family = str(answers.get("travel_party") or "") == "family" or int(answers.get("children") or 0) > 0
    except (TypeError, ValueError):
        is_family = str(answers.get("travel_party") or "") == "family"
    if is_family:
        detail["family_party"] = bool(_destination_condition_met(code, "family", month))

    # Exactly one extra point for overall seasonal suitability.
    detail["seasonality"] = bool(_destination_seasonality_met(code, month))
    return detail


def _open_customer_points(offer, trip):
    """One point for each met customer condition; no hidden weights."""
    return sum(1 for met in _open_customer_point_details(offer, trip).values() if met)


def _customer_rank_value(offer, trip):
    """Customer ranking value. Open searches use points; fixed destinations use flight quality."""
    deal_score = int(offer.get("score") or 0)
    if not _trip_is_destination_led(trip):
        return (_open_customer_points(offer, trip) * 1000.0) + deal_score
    route = int(offer.get("route_score") or 0)
    time_value = int(offer.get("time_value_score") or offer.get("hours_score") or 0)
    baggage = int(offer.get("baggage_score") or 0)
    price = int(offer.get("cost_score") or 0)
    rarity = int(offer.get("rarity_score") or 0)
    return (route * 2.0) + (time_value * 2.0) + (baggage * 1.5) + (price * 0.5) + (rarity * 0.25)


def _normalized_stop_count(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"direct", "nonstop", "non-stop", "non stop", "ישירה", "ללא עצירות"}:
        return 0
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _offer_leg_stops(offer, *, return_leg=False):
    """Resolve one authoritative stop count for ranking and rendering logic."""
    if return_leg:
        keys = ("return_stops", "return_stop_count", "return_stops_count")
        connection_key = "return_connections"
        explicit_direct_keys = ("return_direct", "return_is_direct", "return_nonstop")
    else:
        keys = ("stops", "stop_count", "stops_count")
        connection_key = "connections"
        explicit_direct_keys = ("direct", "is_direct", "nonstop")

    for key in keys:
        if key in offer:
            resolved = _normalized_stop_count(offer.get(key))
            if resolved is not None:
                return resolved
    if connection_key in offer and offer.get(connection_key) is not None:
        try:
            return len(offer.get(connection_key) or [])
        except TypeError:
            pass
    for key in explicit_direct_keys:
        if offer.get(key) is True:
            return 0
    return None


def _offer_is_direct(offer):
    """A round trip is direct only when both legs are known to be nonstop.

    The same resolver handles numeric/string stop counts and connection arrays,
    preventing a deal card from looking direct while matching classifies it
    differently. For legacy records with a known outbound direct leg but no
    return stop metadata, fall back to the outbound value only when return flight
    metadata itself exists and no return-connection evidence is present.
    """
    outbound = _offer_leg_stops(offer, return_leg=False)
    inbound = _offer_leg_stops(offer, return_leg=True)
    if outbound != 0:
        return False
    if inbound is None:
        # Legacy DB rows often omitted return_stops while still carrying a full
        # return leg. They were previously shown as direct by the card; preserve
        # that interpretation only when there is no evidence of a connection.
        has_return_leg = bool(offer.get("return_departure_time") and offer.get("return_arrival_time"))
        return has_return_leg and not bool(offer.get("return_connections"))
    return inbound == 0


def _objective_match_details(offer, trip):
    """Return the complete set of conditions the customer actually selected.

    Above the divider means 100% match.  Direct flight and baggage are evaluated
    first because they are fundamental flight conditions, but every selected
    vacation preference receives the same +1.  Unselected preferences never affect
    membership above/below the divider.
    """
    answers = trip.get("answers") or {}
    points = possible = 0
    matched, missed = [], []

    def add(ok, he, en):
        nonlocal points, possible
        possible += 1
        (matched if ok else missed).append(en if _lang() == "en" else he)
        if ok:
            points += 1

    priorities = {str(x) for x in (answers.get("deal_priorities") or []) if x}
    # Fundamental flight conditions first.
    if "direct" in priorities:
        add(_offer_is_direct(offer), "טיסה ישירה", "Direct flight")
    if "baggage" in priorities:
        b = offer.get("baggage") or {}
        carry = (b.get("carry_on_8kg") or {}).get("included") is True
        checked = (b.get("checked_bag_23kg") or {}).get("included") is True
        add(carry or checked, "כבודה", "Baggage")

    mode = str(answers.get("date_mode") or "anytime")
    if mode == "exact":
        add(_offer_matches_trip(offer, trip, exact_dates=True), "התאריכים שביקשת", "Requested dates")
    elif mode == "month":
        add(_offer_matches_trip(offer, trip, same_month=True), "החודשים שביקשת", "Requested months")

    if answers.get("budget_mode") == "per_person" and answers.get("budget_amount"):
        try:
            add(float(offer.get("price_ils") or 0) <= float(answers.get("budget_amount")) * 1.10, "תקציב", "Budget")
        except (TypeError, ValueError):
            add(False, "תקציב", "Budget")

    # Regular-vacation preferences: every selected item is part of the 100% match.
    if str(answers.get("vacation_type") or "standard") == "standard":
        code = str(offer.get("arrival_code") or "").upper()
        month = _requested_travel_month(trip, offer)
        labels = {
            "price": ("מחיר משתלם", "Good price"),
            "beach": ("בטן־גב", "Beach & relaxation"),
            "nature": ("טבע ונופים", "Nature & scenery"),
            "hiking": ("מסלולים וטיולים", "Hiking & touring"),
            "city": ("ערים ותרבות", "Cities & culture"),
            "family": ("אטרקציות לילדים", "Kids' attractions"),
            "food": ("אוכל וקולינריה", "Food & cuisine"),
            "shopping": ("קניות", "Shopping"),
            "quiet": ("יעד פחות עמוס", "Less crowded"),
            "weather": ("מזג אוויר נעים", "Pleasant weather"),
            "nightlife": ("חיי לילה", "Nightlife"),
            "relax": ("רוגע ופינוק", "Relaxation"),
        }
        for pref in [str(x) for x in (answers.get("holiday_priorities") or []) if x]:
            he, en = labels.get(pref, (pref, pref))
            ok = _good_price_condition(offer) if pref == "price" else _destination_condition_met(code, pref, month)
            add(bool(ok), he, en)

        if "maximize" in priorities:
            arr = _time_minutes(offer.get("arrival_time"))
            ret = _time_minutes(offer.get("return_departure_time"))
            add(arr is not None and ret is not None and arr <= 600 and ret >= 1200,
                "למקסם את החופשה", "Maximize the vacation")

    # Ski preferences are evaluated from the ski-resort table, not the generic
    # destination matrix.
    if str(answers.get("vacation_type") or "standard") == "ski":
        for ok, he, en in _ski_selected_condition_details(offer, trip):
            add(ok, he, en)

    return points, possible, matched, missed


def _customer_inventory_status(all_offers, trip):
    """Describe DB inventory without exposing incomplete records as deals."""
    same_destination = [
        o for o in all_offers
        if _offer_is_recent(o, 48)
        and _offer_destination_matches(o, trip)
        and (_trip_is_destination_led(trip) or int(o.get("score") or 0) >= 65)
    ]
    complete = [o for o in same_destination if _offer_has_complete_roundtrip(o) and _offer_has_baggage_pricing_when_needed(o)]
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
    """Always resolve through the current customer-condition ranking.

    Saved IDs and trip-produced offers must never bypass the latest request
    conditions; otherwise stale QA/customer selections can outrank valid deals.
    """
    return _customer_deal_choices(all_offers, trip, limit=limit)

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
    """Return transparent match information for a regular vacation."""
    points, possible, matched, missed = _objective_match_details(offer, trip)
    if not _trip_is_destination_led(trip):
        pref_points = _open_customer_points(offer, trip)
        points += pref_points
        possible += pref_points  # informational ratio is secondary; ordering uses points.
    return points, possible, matched, missed

def _alternative_date_tier(offer, trip):
    """Classify useful alternative dates without weakening the full-match rule."""
    answers = trip.get("answers") or {}
    if answers.get("_alternative_nearby_dates"):
        return 0
    mode = str(answers.get("date_mode") or "anytime")
    if mode in {"anytime", "ski_flexible"}:
        return 0
    if mode == "exact":
        try:
            req_out = datetime.strptime(str(answers.get("departure_date")), "%Y-%m-%d").date()
            req_ret = datetime.strptime(str(answers.get("return_date")), "%Y-%m-%d").date()
            off_out = datetime.strptime(str(offer.get("outbound_date"))[:10], "%Y-%m-%d").date()
            off_ret = datetime.strptime(str(offer.get("return_date"))[:10], "%Y-%m-%d").date()
            flex = max(0, min(3, int(answers.get("date_flex_days") or 0)))
        except Exception:
            return None
        if abs((off_out-req_out).days) <= flex and abs((off_ret-req_ret).days) <= flex:
            return 0
        if (off_out.year, off_out.month) == (req_out.year, req_out.month) and (off_ret.year, off_ret.month) == (req_ret.year, req_ret.month):
            return 1
        if answers.get("_second_chance_choice") == "nearby_dates":
            out_distance = _month_distance(off_out.strftime("%Y-%m"), req_out.strftime("%Y-%m"))
            ret_distance = _month_distance(off_ret.strftime("%Y-%m"), req_ret.strftime("%Y-%m"))
            if out_distance <= 1 and ret_distance <= 1:
                return 2
        return None
    if mode == "month":
        out = str(offer.get("outbound_date") or "")[:7]
        ret = str(offer.get("return_date") or "")[:7]
        req_out = str(answers.get("outbound_month") or answers.get("travel_month") or "")[:7]
        req_ret = str(answers.get("return_month") or req_out)[:7]
        if out == req_out and ret == req_ret:
            return 0
        if _month_distance(out, req_out) <= 1 and _month_distance(ret, req_ret) <= 1:
            return 2
        return None
    return 0


def _customer_alternative_choices(all_offers, trip, exclude=None, limit=5):
    """Rank below-divider DB alternatives: flex-window partials, then same-month date misses."""
    exclude = set(exclude or [])
    prepared = [_decorate_ski_offer(o, trip) for o in all_offers]
    ranked = []
    for o in prepared:
        if not _offer_is_recent(o, 48) or not _offer_destination_matches(o, trip) or not _offer_has_complete_roundtrip(o):
            continue
        date_tier = _alternative_date_tier(o, trip)
        if date_tier is None:
            continue
        if not _offer_matches_vacation_type(o, trip) or not _ski_offer_constraints_ok(o, trip):
            continue
        sig = _offer_signature(o)
        if sig in exclude:
            continue
        obj_points, obj_possible, matched, missed = _objective_match_details(o, trip)
        if obj_possible and not missed:
            continue
        non_date_misses = [m for m in missed if m not in {"התאריכים שביקשת", "Requested dates", "החודשים שביקשת", "Requested months"}]
        if non_date_misses or not _offer_within_budget(o, trip):
            continue
        ranked.append((date_tier, -obj_points, -int(o.get("score") or 0), float(o.get("price_ils") or 10**9), o, matched, missed, obj_points))
    ranked.sort(key=lambda x: x[:4])
    out = []
    for _, _, _, _, o, matched, missed, total_points in ranked[:limit]:
        c = _decorate_availability_note(o, trip)
        c["request_match_reasons"] = matched
        c["request_missed_reasons"] = missed
        c["customer_match_points"] = total_points
        c["customer_match_detail"] = _open_customer_point_details(o, trip) if not _trip_is_destination_led(trip) else {}
        c["customer_choice_label_he"] = "אפשרות קרובה לבקשה שלך"
        c["customer_choice_label_en"] = "A close match to your request"
        out.append(c)
    return out

def _trip_constraints_summary(trip):
    """Extra customer selections for My Vacations.

    Dates, travelers and budget are already rendered immediately above this block,
    so they are deliberately not repeated here.
    """
    a=trip.get("answers") or {}; out=[]; en=_lang()=="en"

    # Destination/search mode is intentionally omitted here: the card title already shows it.

    # The main card already renders the date window/flexibility. Only an explicit
    # +/- day tolerance is additional information worth showing here.
    dm=str(a.get("date_mode") or "")
    flex=a.get("date_flex_days")
    if dm=="exact" and flex:
        out.append(("Date flexibility" if en else "גמישות בתאריכים", f"±{flex} {'days' if en else 'ימים'}"))

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
    for key in ("direct","baggage","maximize","balanced"):
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
    """Select the primary customer results without hidden hard preference filters.

    Primary results are flights that satisfy all objective restrictions the user
    explicitly set (dates/month, budget when set, direct flight, baggage).  Open
    destination/style preferences determine ordering by one-point-per-condition.
    """
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
        if not _ski_offer_constraints_ok(o, trip):
            continue
        if vacation_type == "business":
            if _business_offer_date_relevant(o, trip):
                qualified.append(o)
            continue

        _, possible, _, missed = _objective_match_details(o, trip)
        if possible and missed:
            continue
        qualified.append(o)

    if vacation_type == "business":
        qualified.sort(key=lambda o: _business_sort_key(o, trip))
        return [_decorate_business_offer(o, trip) for o in qualified[:limit]]

    # Ariella-open searches: points first, deal score only as a tie-breaker.
    # Destination-led searches: the existing route/time quality value remains useful.
    if vacation_type == "ski":
        qualified.sort(key=lambda o: (-_ski_preference_score(o, trip), -int(o.get("score") or 0), float(o.get("price_ils") or 10**9)))
    elif _trip_is_destination_led(trip):
        qualified.sort(key=lambda o: (-_customer_rank_value(o, trip), float(o.get("price_ils") or 10**9)))
    else:
        qualified.sort(key=lambda o: (-_open_customer_points(o, trip), -int(o.get("score") or 0), float(o.get("price_ils") or 10**9)))
        # For an open-destination request, show the best qualifying deal from
        # different destinations first.  Otherwise several near-identical offers
        # for one city can hide other valid September/direct matches.
        diverse, overflow, seen_destinations = [], [], set()
        for offer in qualified:
            code = str(offer.get("arrival_code") or "").upper()
            if code and code not in seen_destinations:
                diverse.append(offer); seen_destinations.add(code)
            else:
                overflow.append(offer)
        qualified = diverse + overflow

    out = []
    for idx, offer in enumerate(qualified[:limit]):
        copy = _decorate_availability_note(offer, trip)
        copy["customer_match_points"] = _open_customer_points(offer, trip) if not _trip_is_destination_led(trip) else None
        copy["customer_match_detail"] = _open_customer_point_details(offer, trip) if not _trip_is_destination_led(trip) else {}
        copy["customer_choice_label_he"] = "הבחירה של אריאלה" if idx == 0 else "מתאים לבקשה שלך"
        copy["customer_choice_label_en"] = "Ariella's choice" if idx == 0 else "Matches your request"
        out.append(copy)
    return out

def _public_best_available(limit=30):
    """Live public feed: fresh, bookable deals at the approved 70+ threshold."""
    recent = [
        _localize_offer_airports(o)
        for o in recent_offers(limit=500, minimum_score=MIN_DEAL_SCORE)
        if _offer_is_publicly_bookable(o) and _offer_is_recent(o, 48)
        and int(o.get("score") or 0) >= MIN_DEAL_SCORE
    ]
    floor = datetime.min.replace(tzinfo=timezone.utc)
    recent.sort(key=lambda o: (_offer_seen_at(o) or floor, int(o.get("score") or 0), -float(o.get("price_ils") or 10**9)), reverse=True)
    return recent[:limit]


def _public_feed_version():
    offers = _public_best_available(limit=120)
    raw = "|".join(
        f"{o.get('offer_id')}:{o.get('observed_at')}:{o.get('score')}:{o.get('price_ils')}"
        for o in offers
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def refresh_public_deal_feed(limit=30):
    """Re-evaluate the public deal feed from the shared 48h DB only.

    This job does not call any external API. Personal-scan offers live in the
    same offers table, so every qualifying customer-found deal can immediately
    compete for the public Top Deals feed. The hourly scheduler records the
    resulting snapshot for observability/admin QA; page rendering still derives
    from the live DB so a strong new deal can surface even before the next hour.
    """
    selected = _public_best_available(limit=limit)
    snapshot = {
        "refreshed_at": utc_now_iso(),
        "offer_ids": [int(o.get("offer_id")) for o in selected if o.get("offer_id") is not None],
        "scores": [int(o.get("score") or 0) for o in selected],
        "count": len(selected),
    }
    try:
        set_setting("public_deal_feed_snapshot", json.dumps(snapshot, ensure_ascii=False))
        set_setting("public_deal_feed_refreshed_at", snapshot["refreshed_at"])
    except Exception:
        pass
    return snapshot


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
            if (trip.get("answers") or {}).get("_second_chance_choice") == "nearby_dates":
                try:
                    trip["alternative_offers"] = _customer_alternative_choices(
                        database_offers + _qa_fixture_offers(), trip, exclude=exact_sigs, limit=max(0, 6-len(trip["offers"]))
                    )
                except Exception:
                    trip["alternative_offers"] = []
            else:
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


@site.get("/api/deals-version")
def deals_version():
    response = jsonify({"version": _public_feed_version(), "minimum_score": MIN_DEAL_SCORE})
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response




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
    trips = []
    for row in rows:
        try:
            trips.append(_trip_dict(row))
        except Exception:
            # A damaged/legacy vacation row must never take down "My Vacations".
            trips.append({
                "id": row["id"],
                "request_name": row["request_name"] or _msg("חופשה", "Vacation"),
                "travel_window": row["travel_window"] or "",
                "status": row["status"] or "active",
                "answers": {},
                "offers": [],
                "alternative_offers": [],
                "no_exact_matches": False,
                "constraints_summary": [],
                "needs_fresh_search": False,
                "has_incomplete_inventory": False,
                "data_error": True,
            })
    database_offers = [_localize_offer_airports(o) for o in recent_offers(limit=1500, minimum_score=None)]
    for trip in trips:
        try:
            trip["offers"] = _resolved_trip_offers(database_offers, trip, limit=5)
        except Exception:
            # One malformed/legacy vacation must never take down "My Vacations".
            trip["offers"] = []
        exact_sigs={_offer_signature(o) for o in trip["offers"]}
        if (trip.get("answers") or {}).get("_second_chance_choice") == "nearby_dates":
            try:
                trip["alternative_offers"] = _customer_alternative_choices(database_offers + _qa_fixture_offers(), trip, exclude=exact_sigs, limit=max(0, 6-len(trip["offers"])))
            except Exception:
                trip["alternative_offers"] = []
        else:
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
        trip["second_chance_used"] = bool((trip.get("answers") or {}).get("_second_chance_used"))
        trip["second_chance_exhausted"] = bool((trip.get("answers") or {}).get("_second_chance_exhausted"))
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
            if ski_labels:
                trip["destination_display"] = _msg(
                    "חופשת סקי — " + " • ".join(ski_labels),
                    "Ski vacation — " + " • ".join(ski_labels),
                )
            else:
                trip["destination_display"] = _msg(
                    "חופשת סקי — אריאלה תבחר אתר סקי",
                    "Ski vacation — Ariella chooses a ski resort",
                )
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
                "OTP": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Bucharest%2C_Romania_%28Unsplash%29.jpg",
                "ZRH": "https://images.unsplash.com/photo-1527668752968-14dc70a27c95?auto=format&fit=crop&w=900&q=82",
                "OTP": "https://cdn.xplorer.co.il/xImages/site/image%2859%29.jpeg",
                "KRK": "https://plikimpi.krakow.pl/zalacznik/563964/4.jpg",
                "LCA": "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=900&q=82",
                "ATH": "https://images.unsplash.com/photo-1555993539-1732b0258235?auto=format&fit=crop&w=900&q=82",
            }
            trip["image_url"] = dedicated.get(destination_codes[0]) or DESTINATION_LANDMARK_IMAGES.get(destination_codes[0]) or "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=900&q=82"
        else:
            # Ariella-chooses-destination uses a curated vacation image pool.
            # Selection changes between renders but never pulls an arbitrary web image.
            open_destination_images = [
                "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=900&q=82",
                "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=900&q=82",
                "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?auto=format&fit=crop&w=900&q=82",
                "https://images.unsplash.com/photo-1469474968028-56623f02e42e?auto=format&fit=crop&w=900&q=82",
                "https://images.unsplash.com/photo-1470770841072-f978cf4d019e?auto=format&fit=crop&w=900&q=82",
            ]
            trip["image_url"] = random.choice(open_destination_images)
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
            # The initial external search already stocked the requested month.
            # The second chance checks that month before spending more API quota.
            if str(o.get("outbound_date") or "")[:7] != str(answers.get("departure_date") or "")[:7]:
                continue
            if str(o.get("return_date") or "")[:7] != str(answers.get("return_date") or "")[:7]:
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
            allowed_out = {_month_shift(out_month, -1), _month_shift(out_month, 1)}
            allowed_ret = {_month_shift(ret_month, -1), _month_shift(ret_month, 1)}
            if str(o.get("outbound_date") or "")[:7] not in allowed_out:
                continue
            if str(o.get("return_date") or "")[:7] not in allowed_ret:
                continue
        _, possible, _, missed = _objective_match_details(o, trip)
        # Ignore only the deliberately changed date/month condition; every other
        # selected hard condition must still pass.
        non_date_misses = [m for m in missed if m not in {"התאריכים שביקשת", "Requested dates", "החודשים שביקשת", "Requested months"}]
        if non_date_misses:
            continue
        if not _offer_within_budget(o, trip):
            continue
        matches.append(o)
    def nearby_key(o):
        if answers.get("date_mode") == "exact":
            req_out = _date_from_iso(answers.get("departure_date")); req_ret = _date_from_iso(answers.get("return_date"))
            off_out = _date_from_iso(o.get("outbound_date")); off_ret = _date_from_iso(o.get("return_date"))
            distance = abs((off_out-req_out).days) + abs((off_ret-req_ret).days) if all((req_out,req_ret,off_out,off_ret)) else 9999
        else:
            distance = 0
        return (distance, -_customer_rank_value(o, trip), float(o.get("price_ils") or 10**9))
    matches.sort(key=nearby_key)
    return matches[:limit]


def _same_dates_other_destination_db_matches(inventory, trip, limit=5):
    answers = trip.get("answers") or {}
    requested = _trip_destination_codes(trip)
    alt_trip = dict(trip)
    alt_answers = dict(answers)
    alt_answers["_alternative_other_destination"] = True
    alt_trip["answers"] = alt_answers
    matches = []
    for o in inventory:
        code = str(o.get("arrival_code") or "").upper()
        if not code or code in requested:
            continue
        if not _offer_has_complete_roundtrip(o):
            continue
        if answers.get("date_mode") == "exact":
            try:
                req_out = datetime.strptime(str(answers.get("departure_date") or "")[:10], "%Y-%m-%d").date()
                req_ret = datetime.strptime(str(answers.get("return_date") or "")[:10], "%Y-%m-%d").date()
                off_out = datetime.strptime(str(o.get("outbound_date") or "")[:10], "%Y-%m-%d").date()
                off_ret = datetime.strptime(str(o.get("return_date") or "")[:10], "%Y-%m-%d").date()
                flex = max(0, min(3, int(answers.get("date_flex_days") or 0)))
            except Exception:
                continue
            if abs((off_out - req_out).days) > flex or abs((off_ret - req_ret).days) > flex:
                continue
        elif answers.get("date_mode") == "month":
            out_month = str(answers.get("outbound_month") or answers.get("travel_month") or "")[:7]
            ret_month = str(answers.get("return_month") or out_month)[:7]
            if out_month and not str(o.get("outbound_date") or "").startswith(out_month):
                continue
            if ret_month and not str(o.get("return_date") or "").startswith(ret_month):
                continue
        # Direct flight, baggage and budget remain hard conditions in the
        # customer's one allowed "other destination / same time" second chance.
        _, possible, _, missed = _objective_match_details(o, alt_trip)
        if possible and missed:
            continue
        matches.append(o)
    def _alt_key(o):
        pts, possible, _, _ = _standard_match_details(o, alt_trip)
        return (-pts, -_customer_rank_value(o, alt_trip), float(o.get("price_ils") or 10**9))
    matches.sort(key=_alt_key)
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
    """Run the customer's single, explicit second-chance branch."""
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
        try:
            trip = _trip_dict(row)
            answers = dict(trip.get("answers") or {})
        except Exception:
            return redirect(url_for("site.account") + f"#vacation-{trip_id}")

    if answers.get("_second_chance_used"):
        return redirect(url_for("site.account") + f"#vacation-{trip_id}")

    inventory = _recent_inventory_48h()
    if choice == "nearby_dates":
        db_matches = _same_destination_other_dates_db_matches(inventory, trip, limit=5)
        if db_matches:
            answers["_second_chance_used"] = True
            answers["_second_chance_choice"] = choice
            _pin_offer_ids_to_trip(trip_id, answers, db_matches)
            with _db() as conn:
                conn.execute(
                    "UPDATE trip_requests SET free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
                    (utc_now_iso(), "database_alternative_match", trip_id),
                )
                conn.commit()
            return redirect(url_for("site.account") + f"#vacation-{trip_id}")
        scan_answers = dict(answers)
        if answers.get("date_mode") == "exact":
            try:
                out = datetime.strptime(answers.get("departure_date"), "%Y-%m-%d").date()
                ret = datetime.strptime(answers.get("return_date"), "%Y-%m-%d").date()
                span = max(1, (ret - out).days)
                base_month = out.strftime("%Y-%m")
                requested_ret_month = ret.strftime("%Y-%m")
                scan_answers.update({
                    "date_mode": "month", "outbound_month": base_month,
                    "return_month": requested_ret_month, "travel_month": base_month,
                    "_alternative_nearby_dates": True,
                    "_alternative_outbound_months": [_month_shift(base_month,-1), _month_shift(base_month,1)],
                    "_alternative_return_months": [_month_shift(requested_ret_month,-1), _month_shift(requested_ret_month,1)],
                    "_requested_trip_length_days": span,
                })
            except Exception:
                return redirect(url_for("site.account") + f"#vacation-{trip_id}")
        elif answers.get("date_mode") == "month":
            base_month = str(answers.get("outbound_month") or answers.get("travel_month") or "")[:7]
            if not base_month:
                return redirect(url_for("site.account") + f"#vacation-{trip_id}")
            ret_month = str(answers.get("return_month") or base_month)[:7]
            scan_answers.update({
                "_alternative_nearby_dates": True,
                "_alternative_outbound_months": [_month_shift(base_month,-1), _month_shift(base_month,1)],
                "_alternative_return_months": [_month_shift(ret_month,-1), _month_shift(ret_month,1)],
            })
        else:
            return redirect(url_for("site.account") + f"#vacation-{trip_id}")
    else:
        if str(answers.get("destination_mode") or "open") not in {"specific", "several"}:
            return redirect(url_for("site.account") + f"#vacation-{trip_id}")
        db_matches = _same_dates_other_destination_db_matches(inventory, trip, limit=5)
        if db_matches:
            answers["_alternative_other_destination"] = True
            answers["_second_chance_used"] = True
            answers["_second_chance_choice"] = choice
            _pin_offer_ids_to_trip(trip_id, answers, db_matches)
            with _db() as conn:
                conn.execute(
                    "UPDATE trip_requests SET free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
                    (utc_now_iso(), "database_other_destination_match", trip_id),
                )
                conn.commit()
            return redirect(url_for("site.account") + f"#vacation-{trip_id}")
        scan_answers = dict(answers)
        scan_answers["_alternative_other_destination"] = True

    try:
        scan_result = run_customer_trip_search(trip_id, scan_answers)
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
    answers["_second_chance_used"] = True
    answers["_second_chance_choice"] = choice
    if choice == "other_destination":
        answers["_alternative_other_destination"] = True
        check_trip = dict(trip); check_trip["answers"] = answers
        matches = _same_dates_other_destination_db_matches(refreshed, check_trip, limit=5)
    else:
        check_trip = dict(trip); check_trip["answers"] = answers
        matches = _customer_alternative_choices(refreshed, check_trip, limit=5)
    if matches:
        _pin_offer_ids_to_trip(trip_id, answers, matches)
    else:
        answers["_second_chance_exhausted"] = True
        with _db() as conn:
            conn.execute("UPDATE trip_requests SET answers_json=? WHERE id=?", (json.dumps(answers, ensure_ascii=False), trip_id))
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
                max_transfer_minutes=None,
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

            ski_months = _ski_months_for_request(
                date_mode, outbound_month, return_month, departure_date, return_date
            )
            if ski_months:
                in_season_rows = _ski_resorts_in_season(resolved["resorts"], ski_months)
                if not in_season_rows:
                    flash(_msg(
                        "לא נמצאו אתרי סקי פתוחים/מתאימים לתקופה שבחרתם. יש לבחור תאריכים אחרים.",
                        "No selected ski resorts are in season for these dates. Please choose different dates.",
                    ), "error")
                    return render_template("trip_form.html", **ctx)
                # Search flights only to gateways serving resorts that are actually in season.
                resolved = _resolve_ski_targets(
                    [f"resort:{r.get('resort')}" for r in in_season_rows], "several"
                )
                destinations = ",".join(resolved["gateway_airports"])

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
            ski_transfer_choice = "any"
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
            ski_transfer_choice = "any"
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
            # If the customer explicitly allowed date flexibility, the separate
            # "selected dates are important" preference is contradictory and must
            # not survive as hidden form state from a previous step.
            if date_mode == "exact" and date_flex_days > 0:
                deal_priorities = [x for x in deal_priorities if str(x) != "dates"]

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
        if vacation_type == "ski":
            if ski_target_labels:
                destination_title = _msg(
                    "חופשת סקי — " + " • ".join(ski_target_labels),
                    "Ski vacation — " + " • ".join(ski_target_labels),
                )
            else:
                destination_title = _msg(
                    "חופשת סקי — אריאלה תבחר אתר סקי",
                    "Ski vacation — Ariella chooses the resort",
                )

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
            "cabin_class": form.get("cabin_class", "any"),
            "ticket_flexibility": form.get("ticket_flexibility", "any"),
            "special_needs": special_needs,
            "notes": notes,
            # Ski-only fields remain empty for regular vacations.
            "ski_targets": ski_targets,
            "ski_target_labels": ski_target_labels,
            "ski_skill_level": ski_skill_level,
            "ski_max_transfer_minutes": ski_max_transfer_minutes,
            "ski_transfer_choice": ski_transfer_choice,
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

        # The customer's exact request has priority. If the fresh shared DB has no
        # full match, every route (including "Ariella chooses") gets an external
        # search before any alternative is offered.
        if not existing_matches:
            try:
                scan_result = run_customer_trip_search(trip_id, payload)
                scan_count = 1
                scan_status = str(scan_result.get("status") or "external_search")
                refreshed_inventory = [
                    _localize_offer_airports(o)
                    for o in recent_offers(limit=1500, minimum_score=None)
                    if _offer_is_recent(o, 48)
                ]
                existing_matches = _customer_deal_choices(refreshed_inventory, trip_for_match, limit=5)
            except Exception:
                scan_count = 1
                scan_status = "external_search_error"

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
