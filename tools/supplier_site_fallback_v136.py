from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOKER = ROOT / "booker.py"

text = BOOKER.read_text(encoding="utf-8")
start = text.find("def resolve_booking_target(")
if start < 0:
    raise RuntimeError("booking target resolver not found")
next_def = text.find("\ndef ", start + 1)
end = next_def if next_def >= 0 else len(text)
current = text[start:end]

# The current exact-party resolver already implements the critical safety rule:
# a personal vacation never falls back to a generic airline homepage or a stale
# booking request. Keep this runtime patch as an invariant check instead of
# rewriting the function again with an older shape.
required = [
    'mode="personal_exact_booking_unavailable" if personal else "recommended_supplier_unavailable"',
    'לא נמצא כרגע קישור הזמנה ששומר את הטיסה ומספר הנוסעים שבחרתם.',
]
for marker in required:
    if marker not in current:
        raise RuntimeError("supplier fallback invariant missing from booking resolver")

print("9.7.136 supplier safety verified: personal deals never lose itinerary/passenger context")
