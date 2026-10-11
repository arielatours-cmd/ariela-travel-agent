"""Task 006a - bridges one inbound WhatsApp message into Ariella's real
engine (the same one the website uses), and performs server-side the exact
follow-up actions templates/trip_form.html's own JS performs in the browser
after every /api/ariella/chat-clean reply (see that file, ~line 280-478):
persist_trip_plan -> save-trip-plan, reopen_trip_id -> track the active
trip, open_existing_flights -> link to the existing results,
start_flight_search -> start-flight-search, and the lodging/car/route
post-flight-continuation loop (syncPostFlight there) -> save-trip-lodging /
save-trip-car / save-trip-plan / sync-trip-services.

Deliberately reuses those exact HTTP routes via Flask's own test client,
authenticated with the member's real session, rather than reimplementing
their business logic a second time - the safest way to guarantee the
website's own behavior cannot change, per the task's explicit constraint.
A browser has localStorage (tripIdKey, savedDomainsKey) to track the active
trip and which domains were already saved; WhatsApp has neither, so
whatsapp_conversation_state.active_trip_id/saved_domains_json (database.py)
stands in for them instead.
"""
from __future__ import annotations

import logging

from config import PUBLIC_BASE_URL
from database import (
    load_ariella_conversation, get_whatsapp_conversation_state,
    set_whatsapp_active_trip, mark_whatsapp_domain_saved,
)

log = logging.getLogger(__name__)

_DOMAIN_SAVE_ENDPOINTS = {
    "lodging": "/api/ariella/save-trip-lodging",
    "car": "/api/ariella/save-trip-car",
    "trip_planning": "/api/ariella/save-trip-plan",
}
_DOMAIN_LABELS = {"lodging": "הלינה", "car": "השכרת הרכב", "trip_planning": "המסלול"}


def _client_for_member(member_id: int):
    """A fresh Flask test client, authenticated exactly the way a real
    browser session would be - member_id is the only thing chat-clean and
    the save-trip-*/start-flight-search/sync-trip-services routes actually
    check (via @login_required / session.get('member_id'))."""
    from app import app as flask_app
    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
        # Read by chat_clean() only - tags this turn's ai_usage rows with
        # channel='whatsapp' without changing anything else about the route.
        sess["ariella_channel"] = "whatsapp"
    return client


def _post_json(client, path: str, payload: dict) -> dict:
    try:
        resp = client.post(path, json=payload)
        data = resp.get_json(silent=True) or {}
        data["_http_status"] = resp.status_code
        return data
    except Exception:
        log.exception("WhatsApp bridge: POST %s failed", path)
        return {"_http_status": 0}


def _waiting_link(waiting_url: str | None) -> str:
    if not waiting_url:
        return ""
    if waiting_url.startswith("http"):
        return waiting_url
    return f"{PUBLIC_BASE_URL}{waiting_url}" if PUBLIC_BASE_URL else waiting_url


def _sync_post_flight(client, member_id: int, trip_id: int, trip_update: dict, history_for_save: list) -> str:
    """Mirrors trip_form.html's syncPostFlight(): for every domain that just
    became 'complete' and hasn't been saved yet for this trip, save it (which
    also fires its real search) and remember it was saved. Once lodging/car/
    trip_planning are all resolved (complete or declined), sync and hand the
    customer a link to the finished vacation. Returns extra text to append
    to the reply, or ''."""
    session_status = trip_update.get("session_status") if isinstance(trip_update.get("session_status"), dict) else {}
    state = get_whatsapp_conversation_state(member_id)
    saved = state.get("saved_domains") or {}
    for domain, endpoint in _DOMAIN_SAVE_ENDPOINTS.items():
        if session_status.get(domain) == "complete" and not saved.get(domain):
            _post_json(client, endpoint, {
                "trip_id": trip_id, "trip_state": trip_update, "history": history_for_save,
            })
            mark_whatsapp_domain_saved(member_id, domain)
            saved[domain] = True

    all_resolved = all(session_status.get(d) in ("complete", "declined") for d in ("lodging", "car", "trip_planning"))
    if not all_resolved:
        return ""
    _post_json(client, "/api/ariella/sync-trip-services", {"trip_id": trip_id, "trip_state": trip_update})
    set_whatsapp_active_trip(member_id, None)
    link = _waiting_link(f"/trip/{trip_id}/waiting")
    return f"\n\nהחופשה שלך מוכנה - אפשר לעקוב אחרי התוצאות כאן: {link}" if link else ""


def ariella_turn(member_id: int, message: str) -> str:
    """One WhatsApp turn through Ariella's real chat-clean engine. Never
    raises - any failure returns a short apology so the customer always gets
    *some* reply, matching the rest of nova_conversation.py's own style."""
    try:
        saved = load_ariella_conversation(member_id) or {}
        history = saved.get("history") or []
        trip_state = saved.get("trip_state") or {}

        client = _client_for_member(member_id)
        data = _post_json(client, "/api/ariella/chat-clean", {
            "message": message, "history": history, "trip_state": trip_state,
        })
        if data.get("_http_status") != 200 or data.get("status") != "success":
            log.error("WhatsApp bridge: chat-clean call failed: %s", data)
            return "קלטתי, אבל הייתה תקלה זמנית אצלי. אפשר לנסות שוב בעוד רגע? 🙏"

        reply = str(data.get("reply") or "").strip() or "אני איתכם 😊"
        trip_update = data.get("trip_update") if isinstance(data.get("trip_update"), dict) else {}
        turn_history = history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": reply},
        ]

        if data.get("reopen_trip_id"):
            set_whatsapp_active_trip(member_id, int(data["reopen_trip_id"]))

        state = get_whatsapp_conversation_state(member_id)
        active_trip_id = state.get("active_trip_id")

        if data.get("persist_trip_plan") is True and active_trip_id:
            _post_json(client, "/api/ariella/save-trip-plan", {
                "trip_id": active_trip_id, "trip_state": trip_update, "history": turn_history,
            })
            mark_whatsapp_domain_saved(member_id, "trip_planning")

        if data.get("open_existing_flights") is True:
            link = _waiting_link(f"/account#flights-{active_trip_id}") if active_trip_id else f"{PUBLIC_BASE_URL}/account"
            return f"{reply}\n\nהנה הקישור: {link}"

        if data.get("start_flight_search") is True:
            started = _post_json(client, "/api/ariella/start-flight-search", {
                "trip_state": trip_update, "history": turn_history, "existing_trip_id": active_trip_id,
            })
            status = started.get("status")
            if status in ("success", "queued") and started.get("waiting_url"):
                new_trip_id = started.get("trip_id")
                if new_trip_id:
                    set_whatsapp_active_trip(member_id, int(new_trip_id))
                link = _waiting_link(started.get("waiting_url"))
                session_status = trip_update.get("session_status") if isinstance(trip_update.get("session_status"), dict) else {}
                nothing_left = all(session_status.get(d) in ("complete", "declined") for d in ("lodging", "car", "trip_planning"))
                if nothing_left:
                    set_whatsapp_active_trip(member_id, None)
                    return f"{reply}\n\nמתחילה לחפש ✈️ התוצאות יופיעו כאן: {link}"
                return reply
            if status == "change_requires_payment" and started.get("account_url"):
                return f"{started.get('message') or reply}\n\n{_waiting_link(started['account_url'])}"
            if status == "duplicate_active_trip" and started.get("waiting_url"):
                return f"{started.get('message') or reply}\n\n{_waiting_link(started['waiting_url'])}"
            return f"{reply}\n\n{started.get('message') or 'לא הצלחתי להתחיל את החיפוש כרגע. כתבו מאשרת שוב כדי לנסות פעם נוספת.'}"

        if active_trip_id:
            reply += _sync_post_flight(client, member_id, int(active_trip_id), trip_update, turn_history)

        return reply
    except Exception:
        log.exception("WhatsApp bridge: ariella_turn failed for member %s", member_id)
        return "קרתה תקלה זמנית, ננסה שוב בעוד רגע 🙏"
