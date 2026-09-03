from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "templates" / "_deal_card.html"

text = CARD.read_text(encoding="utf-8")
old = "  <small>{{ '(additional charge)' if lang=='en' else '(בתוספת תשלום)' }}</small>\n"
if old in text:
    text = text.replace(old, "", 1)
CARD.write_text(text, encoding="utf-8")
print("9.7.136 deal-card baggage subtitle removed")
