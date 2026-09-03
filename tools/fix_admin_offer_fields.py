from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Admin: estimated airline-policy baggage prices are not actual offer facts.
# Show them as unknown instead of presenting a fixed fallback (e.g. 360x2 = 720)
# as if it came from the live booking option.
p = ROOT / "admin.py"
s = p.read_text(encoding="utf-8")
old_bag = '''      טרולי: {{'✓' if co.included is true else ('₪' ~ (co.roundtrip_price_ils|round|int) if co.roundtrip_price_ils is number else 'לא ידוע')}}<br>\n      מזוודה: {{'✓' if cb.included is true else ('₪' ~ (cb.roundtrip_price_ils|round|int) if cb.roundtrip_price_ils is number else 'לא ידוע')}}'''
new_bag = '''      טרולי: {{'✓' if co.included is true else ('₪' ~ (co.roundtrip_price_ils|round|int) if co.roundtrip_price_ils is number and not co.price_estimated and not co.estimated else 'לא ידוע')}}<br>\n      מזוודה: {{'✓' if cb.included is true else ('₪' ~ (cb.roundtrip_price_ils|round|int) if cb.roundtrip_price_ils is number and not cb.price_estimated and not cb.estimated else 'לא ידוע')}}'''
if old_bag not in s and new_bag not in s:
    raise RuntimeError("admin baggage template pattern not found")
if old_bag in s:
    s = s.replace(old_bag, new_bag, 1)

# Feedback page must have the same three fixed-width tabs as the other admin pages.
old_feedback_css = '.admin-nav{display:grid;grid-template-columns:1fr 1fr;gap:0;margin:24px 0 24px;border-bottom:2px solid #d8c49a}'
new_feedback_css = '.admin-nav{display:grid;grid-template-columns:repeat(3,1fr);gap:0;margin:24px 0 24px;border-bottom:2px solid #d8c49a}'
if old_feedback_css in s:
    s = s.replace(old_feedback_css, new_feedback_css, 1)
old_feedback_nav = '''<div class="admin-nav"><a href="/admin{% if token %}?token={{ token }}{% endif %}">✦ סריקות ודילים</a><a class="active" href="/admin/feedback{% if token %}?token={{ token }}{% endif %}">✦ הערות והצעות</a></div>'''
new_feedback_nav = '''<div class="admin-nav"><a href="/admin{% if token %}?token={{ token }}{% endif %}">✦ סריקות ודילים</a><a href="/admin/analytics{% if token %}?token={{ token }}{% endif %}">✦ משתמשים ונתונים</a><a class="active" href="/admin/feedback{% if token %}?token={{ token }}{% endif %}">✦ הערות והצעות</a></div>'''
if old_feedback_nav in s:
    s = s.replace(old_feedback_nav, new_feedback_nav, 1)
p.write_text(s, encoding="utf-8")

# Database/admin normalization: old offers can contain a price reason/reference but
# lack the price component in deal_score.components. Reconstruct only the missing
# display component from the same scoring thresholds, without changing stored DB data.
p = ROOT / "database.py"
s = p.read_text(encoding="utf-8")
helper_marker = '\ndef utc_now_iso() -> str:\n'
helper = '''\ndef _admin_price_component(components, analysis):\n    existing = (components or {}).get("price")\n    discount = (analysis or {}).get("best_discount_percent")\n    source = (analysis or {}).get("price_reference_source")\n    # A positive, supported reference must receive the same price points used by scoring.py.\n    if isinstance(discount, (int, float)) and discount > 0:\n        if discount >= 30: points = 40\n        elif discount >= 25: points = 36\n        elif discount >= 20: points = 32\n        elif discount >= 15: points = 27\n        elif discount >= 10: points = 20\n        elif discount >= 5: points = 12\n        else: points = 6\n        if source == "search_distribution":\n            points = min(points, 20)\n        # Prefer a valid positive recomputation over legacy zero/missing components.\n        if existing is None or (isinstance(existing, (int, float)) and existing == 0):\n            return points\n    if existing is not None:\n        return existing\n    if (analysis or {}).get("price_level") == "low":\n        return 30\n    return 0\n\n'''
if '_admin_price_component' not in s:
    if helper_marker not in s:
        raise RuntimeError("database helper insertion marker not found")
    s = s.replace(helper_marker, helper + helper_marker, 1)
old_cost = '            "cost_score": components.get("price"),'
new_cost = '            "cost_score": _admin_price_component(components, analysis),'
if old_cost in s:
    s = s.replace(old_cost, new_cost, 1)
elif new_cost not in s:
    raise RuntimeError("database cost_score pattern not found")
p.write_text(s, encoding="utf-8")

print("admin offer fields patched: baggage facts, price score, nav")
