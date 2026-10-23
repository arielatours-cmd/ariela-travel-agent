"""QA for dry-run 5d item 1 (Shaked, 23.10.2026, qa/reports/2026-10-23-
dryrun5d.md, scenario A) - called BLOCKING, the dry-run 5c/5d PRV-18 fix
closed the wrong door:

Turn 2 ("אמא שלי עברה ניתוח בברך והיא מתקשה ללכת מרחקים ארוכים"), with
budget as the live guided question (accessibility already closed on turn
1 via the safe "other" fallback): trip_update.accessibility ended up
{"details": "אמא עברה ניתוח בברך ומתקשה ללכת מרחקים ארוכים", "needs":
["mobility"]} - raw medical text, and "mobility" isn't even in
_GUIDED_ACCESSIBILITY_NEED_VALUES. This never went through
_guided_field_update_and_confirm's own closed table at all - the GENERAL
extractor (EXTRACTOR_SYSTEM/_extract_trip_update, which runs every turn
regardless of which guided field is live) wrote it directly, with no
constraint on the field's shape in its own prompt. _medical_detail_
mentioned was never set either, so the PRV-18 reply backstop
(_retry_if_medical_detail_leaked) never even ran.

Two-part fix:
1. _parse_trip_update now unconditionally strips "accessibility" from
   the model's own JSON output (same "code-owned, not on you" principle
   already applied to session_status/active_session) - accessibility can
   only ever be written by the guided mechanism's own closed-table path,
   regardless of prompt compliance.
2. A new independent signal, mentions_medical_reason (a JSON sibling of
   trip_update, parsed by _parse_medical_reason_signal exactly like
   restart_request), lets this SAME extractor call (cost-neutral) flag a
   medical reason mentioned on ANY turn - decoupled entirely from
   whichever field is the live guided question. The call site merges
   this into accessibility._medical_detail_mentioned (sticky, same
   mechanism the guided path already uses), so the PRV-18 reply backstop
   runs regardless of which path the mention came through.

Run: python3 tools/qa_dryrun5d_prv18_extractor_bypass.py
"""
import inspect
import os
import sys
import json
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import ariella_chat_clean as chat  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


KEY = os.getenv("ANTHROPIC_API_KEY", "test-key-not-real")
MODEL = "claude-sonnet-5"

check("EXTRACTOR_SYSTEM documents that accessibility is never the general extractor's to write",
      "accessibility שייך אך ורק" in chat.EXTRACTOR_SYSTEM)
check("EXTRACTOR_SYSTEM's JSON schema includes the new mentions_medical_reason sibling",
      "mentions_medical_reason" in chat.EXTRACTOR_SYSTEM)


# =====================================================================
# Part 1: _parse_trip_update unconditionally strips accessibility, same
# as the existing session_status/active_session precedent - code-level
# guarantee, never trusted to the prompt alone.
# =====================================================================
RAW_WITH_BAD_ACCESSIBILITY = json.dumps({
    "restart_request": False, "restart_evidence": None, "dates_evidence": None,
    "destination_evidence": None, "trip_type_evidence": None, "relative_date_hint": None,
    "relative_date_hint_evidence": None, "link_request": False, "link_request_evidence": None,
    "baggage_evidence": None, "mentions_medical_reason": True,
    "trip_update": {
        "accessibility": {
            "needed": True, "needs": ["mobility"],
            "details": "אמא עברה ניתוח בברך ומתקשה ללכת מרחקים ארוכים",
        },
        "budget_per_person": {"amount": 1300, "currency": "ILS", "status": "known"},
    },
}, ensure_ascii=False)

parsed = chat._parse_trip_update(RAW_WITH_BAD_ACCESSIBILITY)
check("scenario A repro FIX: _parse_trip_update strips accessibility entirely, even when the "
      "model's own raw JSON writes a free-text detail and an out-of-table needs value",
      "accessibility" not in parsed)
check("regression: every OTHER field in the same trip_update still passes through untouched",
      parsed.get("budget_per_person", {}).get("amount") == 1300)

RAW_WITHOUT_ACCESSIBILITY = json.dumps({
    "restart_request": False, "restart_evidence": None, "dates_evidence": None,
    "destination_evidence": None, "trip_type_evidence": None, "relative_date_hint": None,
    "relative_date_hint_evidence": None, "link_request": False, "link_request_evidence": None,
    "baggage_evidence": None, "mentions_medical_reason": False,
    "trip_update": {"budget_per_person": {"amount": 1300, "currency": "ILS", "status": "known"}},
}, ensure_ascii=False)
check("regression: a response that never mentions accessibility at all still parses cleanly, "
      "no crash from popping an absent key",
      "accessibility" not in chat._parse_trip_update(RAW_WITHOUT_ACCESSIBILITY))


# =====================================================================
# Part 2: _parse_medical_reason_signal - the new independent signal.
# =====================================================================
check("_parse_medical_reason_signal reads mentions_medical_reason=true correctly",
      chat._parse_medical_reason_signal(RAW_WITH_BAD_ACCESSIBILITY) is True)
check("_parse_medical_reason_signal reads mentions_medical_reason=false correctly",
      chat._parse_medical_reason_signal(RAW_WITHOUT_ACCESSIBILITY) is False)
check("regression: unparseable text defaults to False, never assumed True",
      chat._parse_medical_reason_signal("not json at all") is False)
check("regression: empty/None text defaults to False",
      chat._parse_medical_reason_signal(None) is False and chat._parse_medical_reason_signal("") is False)


# =====================================================================
# Part 3: _extract_trip_update end-to-end - the new 14th tuple element,
# and the accessibility strip surviving the full call (not just the
# parse helper in isolation).
# =====================================================================
def _fake_extractor_with_medical_mention(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return RAW_WITH_BAD_ACCESSIBILITY
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_extractor_with_medical_mention):
    result = chat._extract_trip_update(KEY, MODEL, [], "אמא שלי עברה ניתוח בברך והיא מתקשה ללכת מרחקים ארוכים", {})
check("_extract_trip_update returns exactly 14 elements (mentions_medical_reason appended)",
      len(result) == 14)
(parsed_tu, _restart, _restart_ev, _dates_ev, _dest_ev, _tt_ev, _rel_hint, _rel_ev,
 _link, _link_ev, _bag_ev, _parse_err, _diag, mentions_medical) = result
check("end-to-end: accessibility never reaches the caller even through the full extractor call",
      "accessibility" not in parsed_tu)
check("end-to-end: mentions_medical_reason is correctly surfaced as the 14th element",
      mentions_medical is True)

def _fake_extractor_no_mention(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return RAW_WITHOUT_ACCESSIBILITY
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_extractor_no_mention):
    result2 = chat._extract_trip_update(KEY, MODEL, [], "עד 1300 שקל לאחת", {})
check("regression: an ordinary turn with no medical mention returns mentions_medical_reason=False",
      result2[13] is False)


# =====================================================================
# Part 4: the sticky merge itself (accessibility._medical_detail_mentioned),
# and that it is actually wired into the real per-turn handler (not just
# defined and never called).
# =====================================================================
EXISTING_ACCESSIBILITY_OTHER = {"asked": True, "needed": True, "needs": ["other"], "details": "התאמה מיוחדת אחרת"}
merged = chat._merge_trip_state(
    {"accessibility": EXISTING_ACCESSIBILITY_OTHER},
    {"accessibility": {"_medical_detail_mentioned": True}},
)
check("the sticky merge preserves the guided path's own safe closed-table fields alongside the new flag",
      merged["accessibility"]["needs"] == ["other"]
      and merged["accessibility"]["details"] == "התאמה מיוחדת אחרת")
check("the sticky merge adds _medical_detail_mentioned without introducing any raw medical text",
      merged["accessibility"]["_medical_detail_mentioned"] is True
      and "ניתוח" not in json.dumps(merged, ensure_ascii=False))

_chat_impl_source = inspect.getsource(chat._chat_clean_impl)
check("wiring check: the real per-turn handler actually merges mentions_medical_reason into "
      "accessibility._medical_detail_mentioned (not just defined, never called)",
      'if mentions_medical_reason:' in _chat_impl_source
      and '"accessibility": {"_medical_detail_mentioned": True}' in _chat_impl_source)


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5D-PRV18-EXTRACTOR-BYPASS TESTS PASSED")
