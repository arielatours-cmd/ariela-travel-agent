from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "scanner.py"
s = p.read_text(encoding="utf-8")
old = 'params = _roundtrip_params(departure, arrival, outbound_date, return_date, adults=adults, children=children)'
new = 'params = _roundtrip_params(departure, arrival, outbound_date, return_date)'
if old not in s:
    raise RuntimeError("scanner adults/children pattern not found")
p.write_text(s.replace(old, new, 1), encoding="utf-8")
print("scanner adults/children bug patched")
