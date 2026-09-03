from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEALS = ROOT / "templates" / "deals.html"
PUBLIC = ROOT / "public_site.py"

text = DEALS.read_text(encoding="utf-8")
old = '''      <form method="post" action="{{ url_for('site.whatsapp_opt_in') }}" class="deal-alert-form">
        <input type="hidden" name="enabled" value="{{ '0' if member.whatsapp_opt_in else '1' }}">'''
new = '''      <form method="post" action="{{ url_for('site.whatsapp_opt_in') }}" class="deal-alert-form">
        <input type="hidden" name="enabled" value="{{ '0' if member.whatsapp_opt_in else '1' }}">
        {% if not member.whatsapp_opt_in %}<input type="hidden" name="paid_product" value="whatsapp_deals_9">{% endif %}'''
text = text.replace(old, new)
old_copy = "<span class=\"deal-alert-copy\"><strong>{{ 'Deals before everyone' if site_lang=='en' else 'הדילים לפני כולם' }}</strong><small>{{ 'WhatsApp alerts' if site_lang=='en' else 'התראות ב־WhatsApp' }}</small></span>"
new_copy = "<span class=\"deal-alert-copy\"><strong>{{ 'Deals before everyone' if site_lang=='en' else 'הדילים לפני כולם' }}</strong><small>{% if member.whatsapp_opt_in %}{{ 'WhatsApp alerts active' if site_lang=='en' else 'התראות WhatsApp פעילות' }}{% else %}{{ 'One-time payment · ₪9' if site_lang=='en' else 'תשלום חד־פעמי · 9 ₪' }}{% endif %}</small></span>"
text = text.replace(old_copy, new_copy)
DEALS.write_text(text, encoding="utf-8")

# Until a payment provider callback exists, never mark the 9-ILS product as paid
# merely because the customer pressed the switch. The route records intent and
# keeps WhatsApp disabled; card details are never collected by Ariella.
p = PUBLIC.read_text(encoding="utf-8")
needle = '''    enabled = request.form.get("enabled", "1") == "1"
    with _db() as conn:
        conn.execute("UPDATE members SET whatsapp_opt_in=?, whatsapp_opt_in_at=? WHERE id=?",
                     (1 if enabled else 0, utc_now_iso() if enabled else None, member["id"]))
        conn.commit()
    return redirect(url_for("site.deals"))'''
replacement = '''    enabled = request.form.get("enabled", "1") == "1"
    if enabled and request.form.get("paid_product") == "whatsapp_deals_9":
        flash(_msg("הצטרפות לדילים ב־WhatsApp היא בתשלום חד־פעמי של 9 ₪. ההפעלה תושלם רק לאחר אישור תשלום מאובטח.", "WhatsApp deals require a one-time ₪9 payment. Activation completes only after secure payment confirmation."), "info")
        return redirect(url_for("site.deals"))
    with _db() as conn:
        conn.execute("UPDATE members SET whatsapp_opt_in=?, whatsapp_opt_in_at=? WHERE id=?",
                     (1 if enabled else 0, utc_now_iso() if enabled else None, member["id"]))
        conn.commit()
    return redirect(url_for("site.deals"))'''
if needle in p:
    p = p.replace(needle, replacement, 1)
PUBLIC.write_text(p, encoding="utf-8")
print("9.7.136 WhatsApp 9 ILS one-time payment gate active")
