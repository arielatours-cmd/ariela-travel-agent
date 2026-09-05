from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _write_if_changed(path: Path, text: str, original: str) -> None:
    if text != original:
        path.write_text(text, encoding="utf-8")


def _replace_once(text: str, old: str, new: str) -> str:
    if new in text:
        return text
    if old not in text:
        return text
    return text.replace(old, new, 1)


def _patch_deals_template() -> None:
    path = ROOT / "templates" / "deals.html"
    original = path.read_text(encoding="utf-8")
    text = original

    # Make the WhatsApp purpose unmistakable on desktop and mobile.
    icon = '<span class="deal-alert-whatsapp-icon" aria-hidden="true" style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;flex:0 0 22px;border-radius:50%;background:#25D366;color:#fff;font:700 13px Arial,sans-serif">☎</span>'
    needle = '<span class="deal-alert-copy"><strong>'
    if "deal-alert-whatsapp-icon" not in text:
        text = text.replace(needle, icon + needle)

    # Mobile-only master Filters button. Filters remain closed until the customer asks for them.
    wrap = '<div class="deal-filters-wrap" id="dealFiltersWrap">'
    toggle = '''<div class="deal-filters-wrap" id="dealFiltersWrap">\n  <button class="mobile-filters-master-toggle" id="mobileFiltersMasterToggle" type="button" aria-expanded="false" aria-controls="dealFiltersMain" style="display:none">☰ {{ 'Filters' if site_lang=='en' else 'מסננים' }}</button>'''
    text = _replace_once(text, wrap, toggle)
    text = text.replace('<div class="deal-filters-main">', '<div class="deal-filters-main" id="dealFiltersMain">', 1)

    if "pending-mobile-filter-toggle-20260905" not in text:
        marker = '{% block content %}'
        css = '''{% block content %}\n<style id="pending-mobile-filter-toggle-20260905">\n.mobile-filters-master-toggle{display:none}\n@media(max-width:760px){\n .deals-page .mobile-filters-master-toggle{display:flex!important;width:100%!important;min-height:44px!important;align-items:center!important;justify-content:center!important;gap:7px!important;border:1px solid #c99a3f!important;border-radius:10px!important;background:#fff!important;color:#1c2f49!important;font-weight:800!important;font-size:15px!important;margin:0!important}\n .deals-page .deal-filters-main{display:none!important}\n .deals-page .deal-filters-more{display:none!important}\n .deals-page .deal-filters-wrap.filters-open .deal-filters-main{display:grid!important}\n .deals-page .deal-filters-wrap.filters-open .deal-filters-more:not([hidden]){display:grid!important}\n}\n</style>'''
        text = text.replace(marker, css, 1)

    if "mobileFiltersMasterToggle" in text and "pending-mobile-filter-script-20260905" not in text:
        anchor = '{% endblock %}\n{% block site_disclaimer %}'
        script = '''<script id="pending-mobile-filter-script-20260905">\n(function(){\n const wrap=document.getElementById('dealFiltersWrap'),btn=document.getElementById('mobileFiltersMasterToggle');\n if(!wrap||!btn)return;\n btn.addEventListener('click',function(){\n   const open=!wrap.classList.contains('filters-open');\n   wrap.classList.toggle('filters-open',open);\n   btn.setAttribute('aria-expanded',open?'true':'false');\n   btn.textContent=open ? ('{{ "Close filters" if site_lang=="en" else "סגירת מסננים" }}') : ('{{ "Filters" if site_lang=="en" else "☰ מסננים" }}');\n });\n})();\n</script>\n{% endblock %}\n{% block site_disclaimer %}'''
        text = text.replace(anchor, script, 1)

    _write_if_changed(path, text, original)


def _patch_trip_form() -> None:
    path = ROOT / "templates" / "trip_form.html"
    original = path.read_text(encoding="utf-8")
    text = original
    if "mobile-questionnaire-no-hero-20260905" not in text:
        marker = '{% block content %}'
        style = '''{% block content %}\n<style id="mobile-questionnaire-no-hero-20260905">\n@media(max-width:760px){\n  .trip-questionnaire-hero{display:none!important}\n  .trip-back-bar{padding-top:6px!important;padding-bottom:4px!important;margin-bottom:0!important}\n  .trip-wizard{margin-top:6px!important}\n}\n</style>'''
        text = text.replace(marker, style, 1)
    _write_if_changed(path, text, original)


def _patch_deal_card() -> None:
    path = ROOT / "templates" / "_deal_card.html"
    original = path.read_text(encoding="utf-8")
    text = original
    if "deal-stale-warning" not in text:
        old = '<div class="deal-footer"><span>{{ \'Last updated:\' if lang==\'en\' else \'עודכן לאחרונה:\' }} {{ offer.updated_ago_en if lang==\'en\' else offer.updated_ago_he }}</span></div>'
        new = old + '''\n {% if offer.is_stale_48h %}<div class="deal-stale-warning" style="margin:8px 14px 12px;padding:9px 12px;border:1px solid #d7b46a;border-radius:8px;background:#fff9ec;color:#72531c;font-size:13px;font-weight:700;text-align:center">{{ 'This deal was found more than 48 hours ago. Price and availability may have changed; Ariella will recheck availability when you continue to booking.' if lang=='en' else 'הדיל נמצא לפני יותר מ־48 שעות. המחיר והזמינות עשויים להשתנות; במעבר להזמנה אריאלה תבדוק מחדש את זמינות הדיל.' }}</div>{% endif %}'''
        text = text.replace(old, new, 1)
    _write_if_changed(path, text, original)


def _patch_public_site() -> None:
    path = ROOT / "public_site.py"
    original = path.read_text(encoding="utf-8")
    text = original

    old_public = '''def _public_best_available(limit=30):\n    \"\"\"Live public feed: fresh, bookable deals at the approved 70+ threshold.\"\"\"\n    recent = [\n        _localize_offer_airports(o)\n        for o in recent_offers(limit=500, minimum_score=MIN_DEAL_SCORE)\n        if _offer_is_publicly_bookable(o) and _offer_is_recent(o, 48)\n        and int(o.get(\"score\") or 0) >= MIN_DEAL_SCORE\n    ]\n    floor = datetime.min.replace(tzinfo=timezone.utc)\n    recent.sort(key=lambda o: (_offer_seen_at(o) or floor, int(o.get(\"score\") or 0), -float(o.get(\"price_ils\") or 10**9)), reverse=True)\n    return recent[:limit]\n'''
    new_public = '''def _public_best_available(limit=30):\n    \"\"\"Published public deals stay visible; age changes the warning, not visibility.\"\"\"\n    recent = [\n        _localize_offer_airports(o)\n        for o in recent_offers(limit=2000, minimum_score=MIN_DEAL_SCORE)\n        if _offer_is_publicly_bookable(o)\n        and int(o.get(\"score\") or 0) >= MIN_DEAL_SCORE\n    ]\n    for offer in recent:\n        offer[\"is_stale_48h\"] = not _offer_is_recent(offer, 48)\n    floor = datetime.min.replace(tzinfo=timezone.utc)\n    recent.sort(key=lambda o: (_offer_seen_at(o) or floor, int(o.get(\"score\") or 0), -float(o.get(\"price_ils\") or 10**9)), reverse=True)\n    return recent[:limit]\n'''
    text = _replace_once(text, old_public, new_public)
    text = text.replace('candidates = _public_best_available(limit=120)', 'candidates = _public_best_available(limit=2000)', 1)
    text = text.replace('''    previous_offers = [\n        o for o in all_qualified\n        if _offer_is_publicly_bookable(o) and o not in offers\n    ][:30]''', '''    previous_offers = [\n        o for o in all_qualified\n        if _offer_is_publicly_bookable(o) and o not in offers\n    ]''', 1)

    old_resolved = '''def _resolved_trip_offers(all_offers, trip, limit=5):\n    \"\"\"Always resolve through the current customer-condition ranking.\n\n    Saved IDs and trip-produced offers must never bypass the latest request\n    conditions; otherwise stale QA/customer selections can outrank valid deals.\n    \"\"\"\n    return _customer_deal_choices(all_offers, trip, limit=limit)\n'''
    new_resolved = '''def _resolved_trip_offers(all_offers, trip, limit=5):\n    \"\"\"Show fresh matches plus deals already published to this vacation.\n\n    A published customer deal never disappears only because 48 hours passed.\n    Fresh inventory still drives new-search decisions; pinned historical deals are\n    display history and are revalidated only when the customer clicks booking.\n    \"\"\"\n    fresh = _customer_deal_choices(all_offers, trip, limit=limit)\n    saved_ids = _saved_match_offer_ids(trip)\n    if not saved_ids:\n        return fresh\n    try:\n        stored = [_localize_offer_airports(o) for o in recent_offers(limit=2000, minimum_score=None, offer_ids=saved_ids)]\n    except Exception:\n        stored = []\n    merged, seen = [], set()\n    for offer in fresh + stored:\n        oid = int(offer.get(\"id\") or offer.get(\"offer_id\") or 0)\n        sig = oid or _offer_signature(offer)\n        if sig in seen:\n            continue\n        seen.add(sig)\n        copy = _decorate_availability_note(offer, trip)\n        copy[\"is_stale_48h\"] = not _offer_is_recent(copy, 48)\n        copy[\"booking_trip_id\"] = trip.get(\"id\")\n        merged.append(copy)\n    return merged[:max(limit, len(stored))]\n'''
    text = _replace_once(text, old_resolved, new_resolved)

    old_target = '    target = resolve_booking_target(offer)\n'
    new_target = '''    stale_offer = not _offer_is_recent(offer, 48)\n    target = resolve_booking_target(offer, force_refresh=stale_offer)\n    if stale_offer and not target.url:\n        flash(_msg(\n            \"הדיל נשמר אצלך, אבל לא הצלחנו לאמת כרגע שהמחיר והזמינות המקוריים עדיין קיימים. נסו שוב מאוחר יותר או בדקו דילים עדכניים.\",\n            \"The deal is still saved, but Ariella could not verify that the original price and availability are still active. Please try again later or view current deals.\"\n        ), \"info\")\n        return redirect(url_for(\"site.account\") if session.get(\"member_id\") else url_for(\"site.deals\"))\n'''
    text = _replace_once(text, old_target, new_target)

    _write_if_changed(path, text, original)


def prepare() -> None:
    _patch_deals_template()
    _patch_trip_form()
    _patch_deal_card()
    _patch_public_site()
