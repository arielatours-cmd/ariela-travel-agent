"""QA for the attraction-price fields (Bezalel's task 7, 22.10; structure from
product/attraction-prices.md on the ofek branch) + the Malta airport fix.

  - every record in data/attractions*.json carries every price field, with a
    valid type; price_status is only ok / needs_check
  - "ok" always has a numeric adult price or free entry, an official URL and
    a checked-at date; nothing guessed
  - the original free-text "מחיר/הערת מחיר" field is untouched
  - nothing new reaches the customer: the itinerary card and travel_agents
    still read only their own named fields (display waits for testing)
  - static/airports.json: Malta's country is the code "MT", so a member from
    Malta gets MLA offered like every other country

Offline. Run: python3 tools/qa_attraction_prices.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tempfile  # noqa: E402
os.environ.update({"DB_PATH": os.path.join(tempfile.mkdtemp(prefix="ariella-qa-prices-"), "qa.db"),
                   "SCHEDULER_ENABLED": "false", "SCANNER_ENABLED": "false"})

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


FILES = ["data/attractions.json", "data/attractions_global30.json",
         "data/attractions_global30_extra.json", "data/attractions_malta.json"]
FIELDS = ["price_adult", "price_child", "child_age_range", "free_under_age", "currency", "free_entry",
          "advance_booking", "price_official_url", "price_source", "price_checked_at", "price_status",
          "price_status_reason"]
records = []
for rel in FILES:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        records += [(rel, r) for r in json.load(fh)["attractions"]]

check("all 122 attractions loaded", len(records) == 122)
missing = [(rel, r["שם האטרקציה"]) for rel, r in records if any(f not in r for f in FIELDS)]
check("every record has every price field", not missing)


def num_or_none(v):
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0)


bad_types = []
for rel, r in records:
    ok = (num_or_none(r["price_adult"]) and num_or_none(r["price_child"])
          and (r["free_under_age"] is None or (isinstance(r["free_under_age"], int) and 0 <= r["free_under_age"] < 120))
          and (r["currency"] is None or re.fullmatch(r"[A-Z]{3}", str(r["currency"])))
          and r["free_entry"] in (None, True, False)
          and r["advance_booking"] in (None, "required", "recommended", "not_needed")
          and (r["price_official_url"] is None or str(r["price_official_url"]).startswith(("http://", "https://")))
          and (r["price_checked_at"] is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r["price_checked_at"])))
          and r["price_status"] in ("ok", "needs_check"))
    if not ok:
        bad_types.append((rel, r["שם האטרקציה"]))
check("all price fields have valid types / values", not bad_types)
if bad_types:
    print("   ", bad_types[:5])

ok_rows = [r for _, r in records if r["price_status"] == "ok"]
check("there are 'ok' rows (Ofek's verified prices made it in)", len(ok_rows) >= 30)
weak_ok = [r["שם האטרקציה"] for r in ok_rows
           if not (r["price_official_url"] and (r["price_adult"] is not None or r["free_entry"] is True))]
check("every 'ok' row has an official URL and an adult price or free entry", not weak_ok)
if weak_ok:
    print("   ", weak_ok[:5])
acropolis = next(r for _, r in records if r["שם האטרקציה"] == "Acropolis of Athens")
check("stage 2 applied: Acropolis €30, free under 18, ok",
      acropolis["price_adult"] == 30 and acropolis["currency"] == "EUR" and acropolis["free_under_age"] == 17
      and acropolis["price_status"] == "ok")
colosseum = next(r for _, r in records if r["שם האטרקציה"] == "Colosseum")
check("stage 2 alias applied: Colosseum €18", colosseum["price_adult"] == 18 and colosseum["price_status"] == "ok")
check("records without a draft entry stay all-null + needs_check", all(
    r["price_adult"] is None for _, r in records if r["price_status"] == "needs_check" and r["price_official_url"] is None))

# --- Free-text field kept in the data ---------------------------------------------
malta = next(r for rel, r in records if rel == "data/attractions_malta.json")
check("the free-text 'מחיר/הערת מחיר' field is kept", "מחיר/הערת מחיר" in malta and malta["מחיר/הערת מחיר"])
import travel_agents  # noqa: E402
match_keys = set(travel_agents._travel_matches({"destinations": ["קרואטיה"], "vacation_styles": []}, limit=1)[0])
check("travel_agents output keys unchanged (no price_* fields exposed)",
      match_keys == {"name", "country", "region", "city", "type", "score", "reasons", "duration", "difficulty",
                     "accessibility", "price", "official_url", "booking_url", "notes"})
src = open(os.path.join(ROOT, "itinerary_cards.py"), encoding="utf-8").read()
# Updated 22.10 (the display task, Din's conditions - tools/qa_attraction_price_display.py): the card
# now carries the structured fields and the free-text price is no longer shown.
check("itinerary card carries the structured price fields, not the free-text price",
      '"price_info"' in src and '"מחיר/הערת מחיר"' not in src)

# --- Malta airport --------------------------------------------------------------------------------
with open(os.path.join(ROOT, "static", "airports.json"), encoding="utf-8") as fh:
    airports = json.load(fh)
check("airports.json: every country is a 2-letter code", all(re.fullmatch(r"[A-Z]{2}", str(a.get("country") or "")) for a in airports))
check("airports.json: Malta is MT", next(a for a in airports if a["code"] == "MLA")["country"] == "MT")
import ariella_chat_clean  # noqa: E402
check("a member from Malta (MT) gets MLA offered", ariella_chat_clean._country_airports("MT") == ["MLA"])

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
