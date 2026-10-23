"""QA for the unified destination-resolution rule (23.10.2026, the business
owner's explicit directive, relayed by Shlomo, after dry-run 5i and her own
architectural pushback: "צריך להכניס חוק כללי שמקיף הכל... אם יהיו עוד לקוחות
שיטעו בכיתוב? לשם ליון שבצרפת או ליוון המדינה?"):

_destination_gateway_answer_by_meaning, _reresolve_ambiguous_fresh_
destination, _reinforce_explicit_destination_correction and _guard_
destination_change_evidence - four separate functions/call sites, each
patched point-by-point across dry-runs 5b-5i - are replaced by ONE function,
_resolve_destination_by_meaning, that every shape of a destination
determination goes through: not yet resolved, freshly resolved this turn,
or already settled and possibly being corrected. Carmit's own root-cause
complaint (dry-run 5h/5i): the raw extractor's own direct resolution never
went through the gateway's catalog-ambiguity check at all, because the two
were separate code paths gated on different conditions - "לא מוסיפים עוד
טלאי... לא נתיב אחד עובר דרך regex ואחר עובר דרך הקלאסיפייר. רק נתיב אחד,
חוק אחד."

The rule itself, exactly as approved:
1. An EXACT catalog match (city or country) for a word the customer
   actually wrote always wins - never second-guessed by a merely-similar
   different real place.
2. Otherwise, the raw customer wording plus every near-catalog candidate
   (cities AND countries together, not cities alone) go to one model call.
   A single verified candidate is trusted outright unless the catalog's
   own structural signal found a genuine 2-way near-ambiguity, in which
   case it needs a separate corroborating quote.
3. Two genuinely plausible candidates (city vs city, country vs country,
   or a city vs a DIFFERENT country - her own Lyon/Greece example) are
   never silently resolved to one - ask once, naming both.
4. An explicit customer correction always overrides what's already saved,
   and is itself saved.
5. Ariella's reply text never confirms a change that isn't actually in
   the state received this turn (see the matching TINKERBELL_SYSTEM rule).

This file is the single source of truth for the unified function's own
behavior (complementing, not replacing, the sibling QA files that still
test the UNCHANGED catalog primitives directly -
tools/qa_dryrun5c_catalog_ambiguity_signal.py, tools/qa_dryrun5e_e_fix_
performance.py, tools/qa_dryrun5c_scenario_b_zadar.py, tools/qa_stage3_
run5_diagnostics.py, tools/qa_destination_gateway_answer_by_meaning.py -
all already migrated to call _resolve_destination_by_meaning directly).

Run: python3 tools/qa_dryrun5j_unified_destination_rule.py
"""
import os
import sys
import json
import sqlite3
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

from unittest.mock import patch
import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


def _fake(mapping):
    """mapping: {"classifier": <json string>} - everything else returns {}."""
    def fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
        return mapping.get(source, "{}")
    return fake


def _no_recognition(*a, **kw):
    return json.dumps({"evidence": None, "candidates": [], "disambiguating_evidence": None})


# =====================================================================
# 1. Condition 1 (exact match wins): a message exactly naming a real
#    catalog city is decisive even though it structurally neighbors a
#    different real city/country - no model call needed, no question.
# =====================================================================
exact_hit, near, needle = chat._scan_destination_tokens(chat._destination_message_tokens("רוצים לטוס לוינה בקיץ", None))
check("condition 1: an exact catalog match ('וינה'/Vienna) is decisive even though it's "
      "distance-1 from 'ורנה'/'וילנה' too", exact_hit is True)

res_mali = chat._catalog_near_neighbor_places("מאלי")
check("condition 1: writing the country name exactly ('מאלי'/Mali) is decisive over the "
      "near city 'באלי'/Bali", len(res_mali) == 1 and res_mali.get("מאלי") == ("country", None))

# =====================================================================
# 2. E1 (dry-run 5g/5h/5i live repro): the raw extractor resolves "לברגם"
#    directly to Bergamo (BGY) on turn 0, bypassing the old separate
#    gateway path entirely - the unified function must catch this FRESH
#    resolution itself, revert it, and chain straight into the SAME
#    recognition call (no second, separately-scheduled pass needed).
# =====================================================================
E1_PRIOR_STATE = {}
E1_FRESH_UPDATE = {
    "destination": {"places": ["ברגמו"], "mode": "specific", "status": "known"},
    "destination_airports": ["BGY"],
}
E1_MESSAGE = "אני, אשתי והתינוק שלנו בן שנה לברגם, 12 עד 17 ביוני"


def _fake_e1_single_no_corroboration(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier":
        return json.dumps({"evidence": "לברגם", "disambiguating_evidence": None,
                            "candidates": [{"type": "city", "city_en": "Bergamo", "iata_code": "BGY"}]})
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_e1_single_no_corroboration):
    e1_result = chat._resolve_destination_by_meaning(E1_PRIOR_STATE, dict(E1_FRESH_UPDATE), "לברגם", E1_MESSAGE, [])
check("E1 FIX: the fresh same-turn resolution to 'ברגם'/Bergamo is reverted - "
      "destination_airports is NOT silently kept as BGY",
      not e1_result.get("destination_airports"))
check("E1 FIX: a single unsupported model pick (Bergamo, no genuine corroborating quote) "
      "is overridden - both real candidates are asked about instead",
      bool(e1_result.get("_destination_ambiguous_hint"))
      and "ברגמו" in e1_result["_destination_ambiguous_hint"] and "ברגן" in e1_result["_destination_ambiguous_hint"])

# Genuine corroboration (the quote names Bergamo's own country, Italy, or
# a different real Italian catalog city) is still honored - never a
# blanket rejection of every single-candidate pick.
E1_MESSAGE_WITH_CORROBORATION = E1_MESSAGE + ", ליד מילאנו"
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: json.dumps({
        "evidence": "לברגם", "disambiguating_evidence": "ליד מילאנו",
        "candidates": [{"type": "city", "city_en": "Bergamo", "iata_code": "BGY"}]})):
    e1_corroborated = chat._resolve_destination_by_meaning(
        E1_PRIOR_STATE, dict(E1_FRESH_UPDATE), "לברגם", E1_MESSAGE_WITH_CORROBORATION, [])
check("E1 regression: a genuine corroborating quote ('ליד מילאנו', a real Italian catalog "
      "city) lets the single pick (Bergamo) through",
      e1_corroborated.get("destination_airports") == ["BGY"])

# =====================================================================
# 3. E2 (dry-run 5g): the raw unresolved place keeps its leading ל/ב/מ
#    preposition - the old gateway path needed its own stripped-form
#    retry; the unified function's shared tokenizer must still catch it.
# =====================================================================
exact_hit_e2, near_e2, needle_e2 = chat._scan_destination_tokens(chat._destination_message_tokens(E1_MESSAGE, "לברגם"))
check("E2 regression: the shared tokenizer still finds the 2-way Bergen/Bergamo ambiguity "
      "through the raw ל-prefixed message token, no exact hit anywhere",
      exact_hit_e2 is False and len(near_e2) == 2)

# =====================================================================
# 4. Macau ordering fix (Shaked's static review of bbf7d990): the raw
#    form alone must never win over the ל/ב/מ-stripped form's own exact
#    match - condition 1 applies across every candidate FORM, not just
#    the first one tried.
# =====================================================================
exact_hit_macau, _, _ = chat._scan_destination_tokens(chat._destination_message_tokens("רוצים לטוס במקאו בסוף השנה", None))
check("Macau ordering FIX: 'במקאו' (ב-prefixed) resolves via its stripped exact match "
      "('מקאו') rather than stopping at a near-miss on the raw form", exact_hit_macau is True)

# =====================================================================
# 5. Explicit correction (dry-run 5h live finding): once a destination is
#    already resolved, an explicit, catalog-verified correction to a
#    DIFFERENT real destination always wins and is itself saved - even
#    when the extractor's own trip_update proposes no change at all.
# =====================================================================
TRIP_STATE_BGY = {"destination_airports": ["BGY"], "destination": {"places": ["ברגמו"]}}


def _fake_correction(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier":
        return json.dumps({"evidence": "ברגן, בנורווגיה", "disambiguating_evidence": None,
                            "candidates": [{"type": "city", "city_en": "Bergen", "iata_code": "BGO"}]})
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_correction):
    correction_result = chat._resolve_destination_by_meaning(
        TRIP_STATE_BGY, dict(TRIP_STATE_BGY), None, "לא, בעצם ברגן, בנורווגיה", [])
check("dry-run 5h FIX: an explicit correction to a different real destination (Bergen) "
      "is recognized and saved even though the extractor's own trip_update proposed no "
      "change at all", correction_result.get("destination_airports") == ["BGO"])
check("dry-run 5h FIX: destination.places reflects the catalog's own verified spelling",
      correction_result.get("destination", {}).get("places") == ["ברגן"])

# Cost control: the common, already-correctly-extracted case (extractor's
# own destination_evidence already verifies) never spends an extra call.
_calls = []


def _counting_fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    _calls.append(source)
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_counting_fake):
    already_verified = chat._resolve_destination_by_meaning(
        TRIP_STATE_BGY, dict(TRIP_STATE_BGY), "ברגן, בנורווגיה", "לא, בעצם ברגן, בנורווגיה", [])
check("cost control: when the extractor's own destination_evidence already verifies, "
      "no extra classifier call is spent at all", len(_calls) == 0)

# Fabricated evidence (not verbatim in the message) is rejected exactly
# like every other evidence gate in this file.
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: json.dumps({
        "evidence": "משהו שלא נאמר בהודעה בכלל", "disambiguating_evidence": None,
        "candidates": [{"type": "city", "city_en": "Bergen", "iata_code": "BGO"}]})):
    fabricated_result = chat._resolve_destination_by_meaning(
        TRIP_STATE_BGY, dict(TRIP_STATE_BGY), None, "לא, בעצם ברגן, בנורווגיה", [])
check("regression: fabricated evidence not actually in the message is rejected",
      fabricated_result.get("destination_airports") == ["BGY"])

# A "correction" to the SAME already-resolved destination is a no-op.
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: json.dumps({
        "evidence": "כן, ברגמו מתאים", "disambiguating_evidence": None,
        "candidates": [{"type": "city", "city_en": "Bergamo", "iata_code": "BGY"}]})):
    same_dest_result = chat._resolve_destination_by_meaning(
        TRIP_STATE_BGY, dict(TRIP_STATE_BGY), None, "כן, ברגמו מתאים", [])
check("regression: a 'correction' to the SAME already-resolved destination is a no-op",
      same_dest_result.get("destination_airports") == ["BGY"])

# =====================================================================
# 6. The business owner's own city/country collision concern (Lyon vs
#    Greece) - generalized here to a real catalog pair at edit-distance 1
#    from the SAME raw word ("ואלי" is near both Bali/city and Mali/
#    country): never silently resolved to one, a country candidate is
#    exactly as real and catalog-checkable as a city one.
# =====================================================================
def _fake_bali_mali(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier":
        return json.dumps({
            "evidence": "ואלי", "disambiguating_evidence": None,
            "candidates": [
                {"type": "city", "city_en": "Bali", "iata_code": "DPS"},
                {"type": "country", "country_en": "Mali"},
            ],
        })
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_bali_mali):
    collision_result = chat._resolve_destination_by_meaning(
        {}, {"destination": {"places": ["ואלי"]}}, None, "אני חושב לטוס לואלי", [])
check("city/country collision FIX: never silently picks one - asks via "
      "_destination_ambiguous_hint naming both", bool(collision_result.get("_destination_ambiguous_hint")))
check("city/country collision FIX: nothing is written to destination_airports or "
      "destination.mode while the question is open",
      not collision_result.get("destination_airports") and not collision_result.get("destination", {}).get("mode"))
check("city/country collision FIX: the hint tells Tinkerbell to continue into the normal "
      "country-level flow if the customer picks the country",
      "ברמת מדינה" in collision_result["_destination_ambiguous_hint"])

# =====================================================================
# 7. A genuine country-level typo ("גרמני", near-but-not-exact to
#    Germany only - no structural 2-way ambiguity) resolves to
#    destination.mode="country" with destination_airports left empty -
#    the EXISTING country-narrowing flow picks it up on a later turn,
#    no new code needed per Shlomo's own plan point.
# =====================================================================
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: json.dumps({
        "evidence": "גרמני", "disambiguating_evidence": None,
        "candidates": [{"type": "country", "country_en": "Germany"}]})):
    germany_result = chat._resolve_destination_by_meaning(
        {}, {"destination": {"places": ["גרמני"]}}, None, "רוצים לטוס לגרמני בקיץ", [])
check("country-level typo FIX: 'גרמני' resolves to destination.mode='country' with the "
      "catalog's own verified spelling",
      germany_result.get("destination", {}).get("mode") == "country"
      and germany_result.get("destination", {}).get("places") == ["גרמניה"])
check("country-level typo FIX: destination_airports stays empty - the existing "
      "narrowing flow (not this function) picks the actual gateway later",
      germany_result.get("destination_airports") == [])

# A country candidate that fails catalog verification (invented country)
# is never trusted on the model's claim alone.
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: json.dumps({
        "evidence": "לנרניה", "disambiguating_evidence": None,
        "candidates": [{"type": "country", "country_en": "Narnia"}]})):
    invented_country_result = chat._resolve_destination_by_meaning(
        {}, {"destination": {"places": ["לנרניה"]}}, None, "רוצים לטוס לנרניה", [])
check("regression: an invented/uncatalogued country is rejected, never trusted on the "
      "model's claim alone",
      invented_country_result.get("destination", {}).get("mode") != "country")

# =====================================================================
# 8. End-to-end through the real /api/ariella/chat-clean endpoint - the
#    exact live failure shape (extractor resolves destination_airports
#    directly on turn 0, from an ambiguous raw customer wording, with no
#    separate gateway path ever running).
# =====================================================================
import database
database.init_db()
import app as app_module
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
client = app_module.app.test_client()


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Unified Destination", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-unified-destination-rule@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id


def _fake_e2e(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "state_extractor":
        return json.dumps({
            "restart_request": None, "restart_evidence": None, "dates_evidence": None,
            "destination_evidence": "לברגם", "trip_type_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
            "link_request": None, "link_request_evidence": None, "baggage_evidence": None,
            "mentions_medical_reason": False,
            "trip_update": {
                "trip_type": "standard",
                "destination": {"places": ["ברגמו"], "mode": "specific", "status": "known"},
                "destination_airports": ["BGY"],
                "requested_services": ["flights"],
                "service_decisions": {"flights": {"wanted": True, "source": "x"}},
            },
        })
    if source == "classifier":
        return json.dumps({"evidence": "לברגם", "disambiguating_evidence": None,
                            "candidates": [{"type": "city", "city_en": "Bergamo", "iata_code": "BGY"}]})
    return "תשובה לדוגמה."


with patch.object(chat, "_post_claude", side_effect=_fake_e2e):
    resp_e2e = client.post("/api/ariella/chat-clean", json={
        "message": E1_MESSAGE, "history": [], "trip_state": {},
    })
tu_e2e = (resp_e2e.get_json() or {}).get("trip_update") or {}
check("E1 e2e (real endpoint): the extractor's own direct fresh resolution to Bergamo is "
      "caught and reverted through the single unified call site",
      not tu_e2e.get("destination_airports"))
check("E1 e2e (real endpoint): a one-turn ambiguous hint naming both real candidates is "
      "produced instead", bool(tu_e2e.get("_destination_ambiguous_hint")))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email='qa-unified-destination-rule@example.com'")
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5J-UNIFIED-DESTINATION-RULE TESTS PASSED")
