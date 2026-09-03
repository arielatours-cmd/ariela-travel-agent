from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public_site.py"
ACCOUNT = ROOT / "templates" / "account.html"
SCANNER = ROOT / "scanner.py"


def patch_public():
    text = PUBLIC.read_text(encoding="utf-8")
    marker = '        trip["over_budget_offers"] = []\n        trip["budget_fallback"] = False\n'
    replacement = '''        # Budget priority is absolute for personal results: exact-budget deals first,
        # then only the agreed <=10% over-budget options as a clearly separated group.
        trip["over_budget_offers"] = []
        trip["budget_fallback"] = False
        answers_for_budget = trip.get("answers") or {}
        if answers_for_budget.get("budget_mode") == "per_person" and answers_for_budget.get("budget_amount"):
            try:
                budget = float(answers_for_budget.get("budget_amount"))
            except (TypeError, ValueError):
                budget = 0.0
            if budget > 0:
                within, slight_over = [], []
                seen = set()
                for offer in list(trip.get("offers") or []) + list(trip.get("alternative_offers") or []):
                    oid = offer.get("offer_id") or offer.get("id") or id(offer)
                    if oid in seen:
                        continue
                    seen.add(oid)
                    try:
                        price = float(offer.get("price_ils") or offer.get("price") or 0)
                    except (TypeError, ValueError):
                        price = 0
                    if price and price <= budget:
                        within.append(offer)
                    elif price and price <= budget * 1.10:
                        copy = dict(offer)
                        copy["budget_overage_percent"] = round((price / budget - 1) * 100, 1)
                        slight_over.append(copy)
                trip["offers"] = within
                trip["alternative_offers"] = []
                trip["over_budget_offers"] = slight_over
                trip["budget_fallback"] = bool(slight_over and not within)
'''
    if marker in text and 'Budget priority is absolute for personal results' not in text:
        text = text.replace(marker, replacement, 1)

    # Expose real lifecycle dates to the customer card; never manufacture an expiry.
    anchor = '        answers = trip.get("answers") or {}\n        try:\n            destination_codes = sorted(_trip_destination_codes(trip))\n'
    dates = '''        answers = trip.get("answers") or {}
        trip["search_opened_at"] = str(trip.get("created_at") or "")[:10]
        trip["search_valid_until"] = str(trip.get("search_period_ends_at") or "")[:10]
        try:
            destination_codes = sorted(_trip_destination_codes(trip))
'''
    if anchor in text and 'trip["search_opened_at"]' not in text:
        text = text.replace(anchor, dates, 1)
    PUBLIC.write_text(text, encoding="utf-8")


def patch_account():
    text = ACCOUNT.read_text(encoding="utf-8")
    # Remove the customer-facing initial-scan label directly in the template too.
    old_status = '''          <span class="search-status {{ 'is-active' if paid_active else 'is-ended' }}">{% if paid_active %}{{ 'Active' if site_lang == 'en' else 'פעיל' }}{% elif paid_before %}{{ 'Ended' if site_lang == 'en' else 'הסתיים' }}{% else %}{{ 'Initial scan' if site_lang == 'en' else 'סריקה ראשונית' }}{% endif %}</span>'''
    new_status = '''          {% if paid_before %}<span class="search-status {{ 'is-active' if paid_active else 'is-ended' }}">{{ ('Active' if site_lang == 'en' else 'פעיל') if paid_active else ('Ended' if site_lang == 'en' else 'הסתיים') }}</span>{% endif %}'''
    text = text.replace(old_status, new_status)

    detail_anchor = '''          <div><dt>{{ 'Budget' if site_lang == 'en' else 'תקציב' }}</dt><dd>{% if a.budget_mode == 'per_person' and a.budget_amount %}{{ 'Up to ₪' if site_lang == 'en' else 'עד ₪' }}{{ a.budget_amount }} {{ 'per person' if site_lang == 'en' else 'לאדם' }}{% else %}{{ 'No budget limit' if site_lang == 'en' else 'ללא הגבלת תקציב' }}{% endif %}</dd></div>'''
    detail_new = detail_anchor + '''
          {% if trip.search_opened_at %}<div><dt>{{ 'Search opened' if site_lang == 'en' else 'החיפוש נפתח' }}</dt><dd>{{ trip.search_opened_at }}</dd></div>{% endif %}
          {% if trip.search_valid_until %}<div><dt>{{ 'Valid until' if site_lang == 'en' else 'בתוקף עד' }}</dt><dd>{{ trip.search_valid_until }}</dd></div>{% endif %}'''
    if detail_anchor in text and 'trip.search_opened_at' not in text:
        text = text.replace(detail_anchor, detail_new, 1)

    old_plans = '''              {% for plan, he_name, en_name, he_freq, en_freq, price in [
                ('calm','רגוע','Relaxed','פעם ב־3 ימים','Every 3 days','₪4.90'),
                ('daily','יומי','Daily','פעם ביום','Once a day','₪9.90'),
                ('intensive','אינטנסיבי','Intensive','3 פעמים ביום','3 times a day','₪14.90')
              ] %}'''
    new_plans = '''              {% for plan, he_name, en_name, he_freq, en_freq, price in [
                ('shared','חיפוש אישי','Personal search','בדיקה מול מאגר הדילים המשותף','Shared deal database monitoring','₪19'),
                ('intensive','חיפוש אינטנסיבי','Intensive search','כולל סריקות חיצוניות כשצריך','Includes external scans when needed','₪39')
              ] %}'''
    text = text.replace(old_plans, new_plans)
    text = text.replace("{% if plan == 'daily' %}<em>{{ 'Recommended' if site_lang == 'en' else 'מומלץ' }}</em>{% endif %}", "{% if plan == 'shared' %}<em>{{ 'Recommended' if site_lang == 'en' else 'מומלץ' }}</em>{% endif %}")
    text = text.replace("<b>{{ price }} / {{ 'month' if site_lang == 'en' else 'חודש' }}</b>", "<b>{{ price }}</b>")

    # Slight budget overage is shown only after exact-budget matches, with explicit context.
    insertion = '''      {% if trip.offers and trip.alternative_offers %}'''
    over = '''      {% if trip.offers and trip.over_budget_offers %}
        <div class="alternative-deals-block budget-overage-block"><div class="alternative-deals-message">{{ 'We found a few more suitable deals with a small budget overage of up to 10%.' if site_lang=='en' else 'מצאנו עוד כמה דילים מתאימים עם חריגה קטנה מהתקציב — עד 10%.' }}</div><div class="ariella-deals-list">{% for offer in trip.over_budget_offers %}{{ deal_card(offer,site_lang) }}{% endfor %}</div></div>
      {% endif %}
'''
    if insertion in text and 'budget-overage-block' not in text:
        text = text.replace(insertion, over + insertion, 1)
    ACCOUNT.write_text(text, encoding="utf-8")


def patch_scanner():
    text = SCANNER.read_text(encoding="utf-8")
    origin_line = '    origins = [str(x).upper() for x in answers.get("origin_airports", []) if x] or list(DEPARTURE_AIRPORTS)\n'
    hfa = '''    origins = [str(x).upper() for x in answers.get("origin_airports", []) if x] or list(DEPARTURE_AIRPORTS)
    # HFA is a limited-route airport. Do not spend personal-scan quota on arbitrary
    # HFA destinations. This allowlist contains the practical direct-search gateways
    # Ariella supports from Haifa; TLV remains unrestricted.
    HFA_PERSONAL_DESTINATIONS = {"LCA", "ATH", "PFO", "RHO", "HER"}
    def _origin_allowed(origin, arrival):
        return origin != "HFA" or arrival in HFA_PERSONAL_DESTINATIONS
'''
    if origin_line in text and 'HFA_PERSONAL_DESTINATIONS' not in text:
        text = text.replace(origin_line, hfa, 1)
    # Filter generated jobs once, centrally, so every date mode obeys the same HFA rule.
    run_marker = '    run_id = create_scan_run(len(jobs), scan_type=f"personal_{str(answers.get(\'vacation_type\') or \'standard\')}", trip_id=trip_id)\n'
    filtered = '''    jobs = [job for job in jobs if _origin_allowed(job["departure"], job["arrival"])]
    run_id = create_scan_run(len(jobs), scan_type=f"personal_{str(answers.get('vacation_type') or 'standard')}", trip_id=trip_id)
'''
    if run_marker in text and 'jobs = [job for job in jobs if _origin_allowed' not in text:
        text = text.replace(run_marker, filtered, 1)
    SCANNER.write_text(text, encoding="utf-8")


patch_public()
patch_account()
patch_scanner()
print("9.7.136 customer rules cleanup active")
