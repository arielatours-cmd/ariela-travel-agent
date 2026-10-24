"""QA: the itinerary cards are created in the vacation's language (Shlomo /
business owner, 24.10) - no translation, one structuring call.

  - no answers["_lang"] (every vacation today) or "he": the Hebrew prompt and
    message exactly as before, catalog duration from "משך מומלץ"
  - answers["_lang"] == "en": _STRUCTURE_PROMPT_EN, an English context and
    message, the model's "name" becomes the card's display name, catalog
    duration from duration_en (never the Hebrew value)
  - core_itinerary_text also trims an English "Day 1: ..." itinerary

Offline (the model call and the Wikipedia lookup are stubbed).
Run: python3 tools/qa_itinerary_lang_prompt.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import itinerary_cards as ic  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


ic._wiki_image_licensed = lambda *a, **k: ("", None)
ic._load_db = lambda: [{
    "שם האטרקציה": "Hagar Qim and Mnajdra Archaeological Park",
    "משך מומלץ": "שעתיים–שלוש שעות",
    "duration_en": "2-3 hours",
}]

calls = []


def fake_post(reply):
    def post(key, model, system, context, history, message, max_tokens, include_history=False):
        calls.append({"system": system, "context": context, "message": message, "max_tokens": max_tokens})
        return json.dumps(reply, ensure_ascii=False)
    return post


HE_REPLY = {"days": [{"day": 1, "title": "עמק המקדשים", "city": "קרנדי", "summary": "יום של היסטוריה",
                      "items": [{"name_he": "מקדשי הג'אר קים", "name_en": "Hagar Qim and Mnajdra Archaeological Park",
                                 "city": "קרנדי", "description": "מקדשים עתיקים", "duration": None}]}]}
EN_REPLY = {"days": [{"day": 1, "title": "Temple valley", "city": "Qrendi", "summary": "A day of history",
                      "items": [{"name": "Hagar Qim temples", "name_en": "Hagar Qim and Mnajdra Archaeological Park",
                                 "city": "Qrendi", "description": "Ancient temples above the sea", "duration": None}]}]}
HE_TEXT = "יום 1: מקדשי הג'אר קים בקרנדי\nיום 2: ולטה"
EN_TEXT = "Here is your plan!\nDay 1: Hagar Qim temples in Qrendi\nDay 2: Valletta\nShall I save it?"

# --- Hebrew: no _lang, and _lang == "he" - unchanged -----------------------------------------
for label, answers in (("no _lang", {}), ("_lang=he", {"_lang": "he"})):
    calls.clear()
    days = ic.build_itinerary_days(HE_TEXT, dict(answers, departure_date="2027-05-01"), fake_post(HE_REPLY), "k", "m")
    c = calls[0]
    check(f"{label}: the Hebrew prompt, unchanged", c["system"] is ic._STRUCTURE_PROMPT)
    check(f"{label}: Hebrew context and message", c["context"].startswith("תאריך יציאה: 2027-05-01") and c["message"].startswith("המסלול שאושר:\n"))
    check(f"{label}: max_tokens unchanged (6000)", c["max_tokens"] == 6000)
    item = days[0]["items"][0]
    check(f"{label}: Hebrew card name", item["name_he"] == "מקדשי הג'אר קים")
    check(f"{label}: catalog duration from 'משך מומלץ'", item["duration"] == "שעתיים–שלוש שעות", item["duration"])

# --- English: _lang == "en" ---------------------------------------------------------------
calls.clear()
days = ic.build_itinerary_days(EN_TEXT, {"_lang": "en", "departure_date": "2027-05-01"}, fake_post(EN_REPLY), "k", "m")
c = calls[0]
check("en: one structuring call (no translation call)", len(calls) == 1)
check("en: the English prompt", c["system"] is ic._STRUCTURE_PROMPT_EN)
check("en: English context and message", c["context"].startswith("Departure date: 2027-05-01") and c["message"].startswith("Approved itinerary:\n"))
check("en: the message is the trimmed English itinerary", "Here is your plan" not in c["message"] and "Shall I save it?" not in c["message"]
      and "Day 1:" in c["message"] and "Day 2:" in c["message"])
item = days[0]["items"][0]
check("en: the model's 'name' is the card's display name", item["name_he"] == "Hagar Qim temples", item["name_he"])
check("en: catalog duration from duration_en, never Hebrew", item["duration"] == "2-3 hours", item["duration"])
check("en: day title/summary as the model wrote them", days[0]["title"] == "Temple valley" and days[0]["summary"] == "A day of history")
check("en: the English prompt has the same JSON keys as the Hebrew one (except name)",
      all(k in ic._STRUCTURE_PROMPT_EN for k in ('"days"', '"title"', '"city"', '"base"', '"summary"', '"items"', '"name_en"', '"description"', '"duration"'))
      and '"name_he"' not in ic._STRUCTURE_PROMPT_EN)

print()
print("ALL ITINERARY-LANG-PROMPT TESTS PASSED" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
