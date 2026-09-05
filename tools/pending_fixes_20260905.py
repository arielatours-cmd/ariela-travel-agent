from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _save(path, before, after):
    if before != after:
        path.write_text(after, encoding="utf-8")


def _once(text, old, new):
    if new in text or old not in text:
        return text
    return text.replace(old, new, 1)


def _patch_deals_template():
    path = ROOT / "templates" / "deals.html"
    before = path.read_text(encoding="utf-8")
    text = before

    old_icon = '<span class="deal-alert-whatsapp-icon" aria-hidden="true" style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;flex:0 0 22px;border-radius:50%;background:#25D366;color:#fff;font:700 13px Arial,sans-serif">☎</span>'
    icon = '<span class="deal-alert-whatsapp-icon" aria-hidden="true" style="display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;flex:0 0 24px;border-radius:50%;background:#25D366;color:#fff"><svg viewBox="0 0 32 32" width="17" height="17" fill="currentColor" aria-hidden="true"><path d="M19.11 17.21c-.26-.13-1.55-.76-1.79-.85-.24-.09-.41-.13-.59.13-.17.26-.67.85-.82 1.02-.15.17-.3.2-.56.07-.26-.13-1.09-.4-2.08-1.28-.77-.68-1.29-1.53-1.44-1.79-.15-.26-.02-.4.11-.53.12-.12.26-.3.39-.46.13-.15.17-.26.26-.44.09-.17.04-.33-.02-.46-.07-.13-.59-1.42-.8-1.94-.21-.51-.43-.44-.59-.45h-.5c-.17 0-.46.07-.7.33-.24.26-.91.89-.91 2.17 0 1.28.94 2.52 1.07 2.69.13.17 1.84 2.81 4.46 3.94.62.27 1.11.43 1.49.55.63.2 1.2.17 1.65.1.5-.07 1.55-.63 1.77-1.24.22-.61.22-1.13.15-1.24-.07-.11-.24-.17-.5-.3z"/><path d="M16.03 3C8.84 3 3 8.69 3 15.7c0 2.43.71 4.7 1.94 6.63L3.06 29l6.88-1.79a13.2 13.2 0 0 0 6.09 1.49C23.22 28.7 29 23.01 29 16S23.22 3 16.03 3zm0 23.52c-2.14 0-4.13-.62-5.82-1.69l-.42-.26-4.08 1.06 1.09-3.97-.27-.41a10.3 10.3 0 0 1-1.71-5.55c0-5.8 4.96-10.52 11.21-10.52 6.25 0 11.15 4.72 11.15 10.52 0 5.8-4.9 10.82-11.15 10.82z"/></svg></span>'
    if old_icon in text:
        text = text.replace(old_icon, icon)
    elif "deal-alert-whatsapp-icon" not in text:
        text = text.replace('<span class="deal-alert-copy"><strong>', icon + '<span class="deal-alert-copy"><strong>')

    text = _once(text, '<div class="deal-filters-wrap" id="dealFiltersWrap">', '''<div class="deal-filters-wrap" id="dealFiltersWrap">\n  <button class="mobile-filters-master-toggle" id="mobileFiltersMasterToggle" type="button" aria-expanded="false" aria-controls="dealFiltersMain" style="display:none">☰ {{ 'Filters' if site_lang=='en' else 'מסננים' }}</button>''')
    text = text.replace('<div class="deal-filters-main">', '<div class="deal-filters-main" id="dealFiltersMain">', 1)
    if "pending-mobile-filter-toggle-20260905" not in text:
        text = text.replace('{% block content %}', '''{% block content %}\n<style id="pending-mobile-filter-toggle-20260905">\n.mobile-filters-master-toggle{display:none}\n@media(max-width:760px){\n .deals-page .mobile-filters-master-toggle{display:flex!important;width:100%!important;min-height:44px!important;align-items:center!important;justify-content:center!important;gap:7px!important;border:1px solid #c99a3f!important;border-radius:10px!important;background:#fff!important;color:#1c2f49!important;font-weight:800!important;font-size:15px!important;margin:0!important}\n .deals-page .deal-filters-main,.deals-page .deal-filters-more{display:none!important}\n .deals-page .deal-filters-wrap.filters-open .deal-filters-main{display:grid!important}\n .deals-page .deal-filters-wrap.filters-open .deal-filters-more:not([hidden]){display:grid!important}\n}\n</style>''', 1)
    if "pending-mobile-filter-script-20260905" not in text:
        anchor = '{% endblock %}\n{% block site_disclaimer %}'
        if anchor in text:
            text = text.replace(anchor, '''<script id="pending-mobile-filter-script-20260905">\n(function(){const w=document.getElementById('dealFiltersWrap'),b=document.getElementById('mobileFiltersMasterToggle');if(!w||!b)return;b.addEventListener('click',function(){const open=!w.classList.contains('filters-open');w.classList.toggle('filters-open',open);b.setAttribute('aria-expanded',open?'true':'false');b.textContent=open?('{{ "Close filters" if site_lang=="en" else "סגירת מסננים" }}'):('{{ "Filters" if site_lang=="en" else "☰ מסננים" }}');});})();\n</script>\n{% endblock %}\n{% block site_disclaimer %}''', 1)
    _save(path, before, text)


def _patch_trip_form():
    path = ROOT / "templates" / "trip_form.html"
    before = path.read_text(encoding="utf-8")
    text = before
    if "mobile-questionnaire-no-hero-20260905" not in text:
        text = text.replace('{% block content %}', '''{% block content %}\n<style id="mobile-questionnaire-no-hero-20260905">\n@media(max-width:760px){.trip-questionnaire-hero{display:none!important}.trip-back-bar{padding-top:6px!important;padding-bottom:4px!important;margin-bottom:0!important}.trip-wizard{margin-top:6px!important}}\n</style>''', 1)
    _save(path, before, text)


def _patch_deal_card():
    path = ROOT / "templates" / "_deal_card.html"
    before = path.read_text(encoding="utf-8")
    text = before
    if "deal-stale-warning" not in text:
        old = '<div class="deal-footer"><span>{{ \'Last updated:\' if lang==\'en\' else \'עודכן לאחרונה:\' }} {{ offer.updated_ago_en if lang==\'en\' else offer.updated_ago_he }}</span></div>'
        warning = '''\n {% if offer.is_stale_48h %}<div class="deal-stale-warning" style="margin:8px 14px 12px;padding:9px 12px;border:1px solid #d7b46a;border-radius:8px;background:#fff9ec;color:#72531c;font-size:13px;font-weight:700;text-align:center">{{ 'This deal was found more than 48 hours ago. Price and availability may have changed; Ariella will recheck availability when you continue to booking.' if lang=='en' else 'הדיל נמצא לפני יותר מ־48 שעות. המחיר והזמינות עשויים להשתנות; במעבר להזמנה אריאלה תבדוק מחדש את זמינות הדיל.' }}</div>{% endif %}'''
        text = text.replace(old, old + warning, 1)
    _save(path, before, text)


def _patch_public_site():
    path = ROOT / "public_site.py"
    before = path.read_text(encoding="utf-8")
    text = before
    old_public = '''def _public_best_available(limit=30):\n    \"\"\"Live public feed: fresh, bookable deals at the approved 70+ threshold.\"\"\"\n    recent = [\n        _localize_offer_airports(o)\n        for o in recent_offers(limit=500, minimum_score=MIN_DEAL_SCORE)\n        if _offer_is_publicly_bookable(o) and _offer_is_recent(o, 48)\n        and int(o.get(\"score\") or 0) >= MIN_DEAL_SCORE\n    ]\n    floor = datetime.min.replace(tzinfo=timezone.utc)\n    recent.sort(key=lambda o: (_offer_seen_at(o) or floor, int(o.get(\"score\") or 0), -float(o.get(\"price_ils\") or 10**9)), reverse=True)\n    return recent[:limit]\n'''
    new_public = '''def _public_best_available(limit=30):\n    \"\"\"Published public deals stay visible; age changes the warning, not visibility.\"\"\"\n    recent = [\n        _localize_offer_airports(o)\n        for o in recent_offers(limit=2000, minimum_score=MIN_DEAL_SCORE)\n        if _offer_is_publicly_bookable(o)\n        and int(o.get(\"score\") or 0) >= MIN_DEAL_SCORE\n    ]\n    for offer in recent:\n        offer[\"is_stale_48h\"] = not _offer_is_recent(offer, 48)\n    floor = datetime.min.replace(tzinfo=timezone.utc)\n    recent.sort(key=lambda o: (_offer_seen_at(o) or floor, int(o.get(\"score\") or 0), -float(o.get(\"price_ils\") or 10**9)), reverse=True)\n    return recent[:limit]\n'''
    text = _once(text, old_public, new_public)
    text = text.replace('candidates = _public_best_available(limit=120)', 'candidates = _public_best_available(limit=2000)', 1)
    text = text.replace('''    previous_offers = [\n        o for o in all_qualified\n        if _offer_is_publicly_bookable(o) and o not in offers\n    ][:30]''', '''    previous_offers = [\n        o for o in all_qualified\n        if _offer_is_publicly_bookable(o) and o not in offers\n    ]''', 1)
    old_resolved = '''def _resolved_trip_offers(all_offers, trip, limit=5):\n    \"\"\"Always resolve through the current customer-condition ranking.\n\n    Saved IDs and trip-produced offers must never bypass the latest request\n    conditions; otherwise stale QA/customer selections can outrank valid deals.\n    \"\"\"\n    return _customer_deal_choices(all_offers, trip, limit=limit)\n'''
    new_resolved = '''def _resolved_trip_offers(all_offers, trip, limit=5):\n    \"\"\"Show fresh matches plus every deal already published to this vacation.\"\"\"\n    fresh = _customer_deal_choices(all_offers, trip, limit=limit)\n    saved_ids = _saved_match_offer_ids(trip)\n    try:\n        trip_id = int(trip.get(\"id\") or 0)\n    except (TypeError, ValueError):\n        trip_id = 0\n    trip_owned = [o for o in all_offers if trip_id and int(o.get(\"trip_id\") or 0) == trip_id]\n    try:\n        pinned = [_localize_offer_airports(o) for o in recent_offers(limit=2000, minimum_score=None, offer_ids=saved_ids)] if saved_ids else []\n    except Exception:\n        pinned = []\n    historical = pinned + trip_owned\n    merged, seen = [], set()\n    for offer in fresh + historical:\n        oid = int(offer.get(\"id\") or offer.get(\"offer_id\") or 0)\n        sig = (\"id\", oid) if oid else (\"sig\", _offer_signature(offer))\n        if sig in seen:\n            continue\n        seen.add(sig)\n        copy = _decorate_availability_note(offer, trip)\n        copy[\"is_stale_48h\"] = not _offer_is_recent(copy, 48)\n        copy[\"booking_trip_id\"] = trip_id or None\n        merged.append(copy)\n    return merged[:limit + len(historical)]\n'''
    text = _once(text, old_resolved, new_resolved)
    old_target = '    target = resolve_booking_target(offer)\n'
    new_target = '''    stale_offer = not _offer_is_recent(offer, 48)\n    target = resolve_booking_target(offer, force_refresh=stale_offer)\n    if stale_offer and not target.url:\n        flash(_msg(\n            \"הדיל נשמר אצלך, אבל לא הצלחנו לאמת כרגע שהמחיר והזמינות המקוריים עדיין קיימים. נסו שוב מאוחר יותר או בדקו דילים עדכניים.\",\n            \"The deal is still saved, but Ariella could not verify that the original price and availability are still active. Please try again later or view current deals.\"\n        ), \"info\")\n        return redirect(url_for(\"site.account\") if session.get(\"member_id\") else url_for(\"site.deals\"))\n'''
    text = _once(text, old_target, new_target)
    _save(path, before, text)


def _patch_admin_score_table():
    """Keep the internal dashboard aligned with the approved 100-point model."""
    path = ROOT / "admin.py"
    before = path.read_text(encoding="utf-8")
    text = before
    text = text.replace('<th class="score-part">עלות</th>', '<th class="score-part" title="מקסימום 45">מחיר / חיסכון<br><small>עד 45</small></th>')
    text = text.replace('<th class="score-part">מסלול</th>', '<th class="score-part" title="מקסימום 20">איכות טיסה<br><small>עד 20</small></th>')
    text = text.replace('<th class="score-part">כבודה</th>', '<th class="score-part" title="מקסימום 10">כבודה<br><small>עד 10</small></th>')
    text = text.replace('<th class="score-part">שעות</th>', '<th class="score-part" title="מקסימום 15">שעות וניצול<br><small>עד 15</small></th>')
    text = text.replace('<th class="score-part">נדירות</th>', '<th class="score-part" title="מקסימום 10">נדירות מחיר<br><small>עד 10</small></th>')
    # Seasonality and supplier reliability are not scoring components anymore.
    text = text.replace('    <th class="score-part">עונתיות</th>\n', '')
    text = text.replace('    <th class="score-part">אמינות</th>\n', '')
    season_cell = '''    <td class="score-part" title="ניקוד עונתיות">\n        {{ o.seasonality_score if o.seasonality_score is defined and o.seasonality_score is not none else\n           (o.season_score if o.season_score is defined and o.season_score is not none else '—') }}\n    </td>\n'''
    reliability_cell = '''    <td class="score-part" title="ניקוד אמינות">\n        {{ o.reliability_score if o.reliability_score is defined and o.reliability_score is not none else '—' }}\n    </td>\n'''
    text = text.replace(season_cell, '')
    text = text.replace(reliability_cell, '')
    text = text.replace('<div class="muted">גרסה {{ version }} · סף דיל: {{ minimum_score }}</div>', '<div class="muted">גרסה {{ version }} · סף דיל כללי: {{ minimum_score }} · ניקוד: מחיר 45 + איכות טיסה 20 + שעות וניצול 15 + כבודה 10 + נדירות 10 = 100</div>')
    _save(path, before, text)


def prepare():
    _patch_deals_template()
    _patch_trip_form()
    _patch_deal_card()
    _patch_public_site()
    _patch_admin_score_table()
