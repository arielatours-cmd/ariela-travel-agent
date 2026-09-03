from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "trip_form.html"

text = TEMPLATE.read_text(encoding="utf-8")
old = "    gate.hidden=true; origin.hidden=false; progressWrap.hidden=false; counter.hidden=false;\n"
new = "    gate.hidden=true; origin.hidden=(current !== 0); progressWrap.hidden=false; counter.hidden=false;\n"

if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise RuntimeError("Ariella 9.7.136: trip wizard origin-panel hook not found")

TEMPLATE.write_text(text, encoding="utf-8")
print("9.7.136 trip wizard origin picker limited to question 1")
