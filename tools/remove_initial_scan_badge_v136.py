from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = ROOT / "templates" / "account.html"

text = ACCOUNT.read_text(encoding="utf-8")
old = "          <span class=\"search-status {{ 'is-active' if paid_active else 'is-ended' }}\">{% if paid_active %}{{ 'Active' if site_lang == 'en' else 'פעיל' }}{% elif paid_before %}{{ 'Ended' if site_lang == 'en' else 'הסתיים' }}{% else %}{{ 'Initial scan' if site_lang == 'en' else 'סריקה ראשונית' }}{% endif %}</span>"
new = "          {% if paid_before %}<span class=\"search-status {{ 'is-active' if paid_active else 'is-ended' }}\">{{ ('Active' if site_lang == 'en' else 'פעיל') if paid_active else ('Ended' if site_lang == 'en' else 'הסתיים') }}</span>{% endif %}"
if old in text:
    text = text.replace(old, new, 1)
ACCOUNT.write_text(text, encoding="utf-8")
print("9.7.136 customer initial-scan badge removed")
