"""Merge Ofek's attraction-price drafts into data/attractions*.json
(product/attraction-prices.md on the ofek branch, 22.10.2026).

Adds structured price fields to the EXISTING attraction records - one source
of truth, no new store. Nothing displays them yet (the itinerary card and
travel_agents read only their own named fields), so customers see no change.
Every record gets every field: an attraction without a draft entry gets
nulls and price_status="needs_check". The free-text "מחיר/הערת מחיר" is kept.

Stage-2 entries that are NOT already in the data (existing_in_db=false) are
reported and skipped: adding new attractions would change what the
itinerary shows, which waits for the end of testing.

Run: python3 tools/apply_attraction_prices.py STAGE1.json [STAGE2.json]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ["data/attractions.json", "data/attractions_global30.json",
         "data/attractions_global30_extra.json", "data/attractions_malta.json"]
PRICE_FIELDS = {
    "price_adult": None, "price_child": None, "child_age_range": None, "free_under_age": None,
    "currency": None, "free_entry": None, "advance_booking": None, "price_official_url": None,
    "price_source": None, "price_checked_at": None, "price_status": "needs_check",
    "price_status_reason": None,
}
# draft field -> record field
MAP = {
    "adult_price": "price_adult", "child_price": "price_child", "child_age_range": "child_age_range",
    "free_under_age": "free_under_age", "currency": "currency", "free_entry": "free_entry",
    "advance_booking": "advance_booking", "official_url": "price_official_url",
    "price_source": "price_source", "checked_at": "price_checked_at", "status": "price_status",
    "status_reason_he": "price_status_reason",
}


# Stage-2 names (existing_in_db=true) that differ from the record's name.
STAGE2_ALIASES = {
    "Paphos Archaeological Park (Kato Pafos)": "Paphos Archaeological Park",
    "Paphos Castle": "Paphos Harbour and Castle",
    "Kourion Archaeological Site": "Kourion Archaeological Site & Ancient Theatre",
    "Limassol Castle – Cyprus Medieval Museum": "Limassol Castle & Medieval Museum",
    "Colosseum, Roman Forum & Palatine (24h)": "Colosseum",
    "Prague Castle – Main Circuit": "Prague Castle",
}


def _key(name):
    return str(name or "").strip().casefold()


def _apply(record, entry):
    for src, dst in MAP.items():
        if src in entry:
            record[dst] = entry[src]
    if record.get("price_status") not in ("ok", "needs_check"):
        record["price_status"] = "needs_check"


def main(stage1_path, stage2_path=None):
    data, trailing_newline = {}, {}
    for rel in FILES:
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            raw = fh.read()
        data[rel] = json.loads(raw)
        trailing_newline[rel] = raw.endswith("\n")  # keep each file's own ending
    for payload in data.values():
        for record in payload["attractions"]:
            for field, default in PRICE_FIELDS.items():
                record.setdefault(field, default)

    by_file_name = {(rel, _key(r.get("שם האטרקציה"))): r for rel, p in data.items() for r in p["attractions"]}
    by_name = {}
    for rel, p in data.items():
        for r in p["attractions"]:
            by_name.setdefault(_key(r.get("שם האטרקציה")), []).append(r)

    report = {"stage1_applied": 0, "stage1_missing": [], "stage2_applied": 0, "stage2_missing": [], "stage2_new_skipped": []}
    with open(stage1_path, encoding="utf-8") as fh:
        for entry in json.load(fh):
            record = by_file_name.get((entry.get("source_file"), _key(entry.get("name"))))
            if record is None:
                report["stage1_missing"].append(entry.get("name"))
                continue
            _apply(record, entry)
            report["stage1_applied"] += 1
    if stage2_path:
        with open(stage2_path, encoding="utf-8") as fh:
            for entry in json.load(fh):
                if not entry.get("existing_in_db"):
                    report["stage2_new_skipped"].append(entry.get("name"))
                    continue
                name = STAGE2_ALIASES.get(entry.get("name"), entry.get("name"))
                records = by_name.get(_key(name)) or []
                if not records:
                    report["stage2_missing"].append(entry.get("name"))
                    continue
                for record in records:  # stage 2 is newer than stage 1
                    _apply(record, entry)
                report["stage2_applied"] += 1

    for rel, payload in data.items():
        with open(os.path.join(ROOT, rel), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            if trailing_newline[rel]:
                fh.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
