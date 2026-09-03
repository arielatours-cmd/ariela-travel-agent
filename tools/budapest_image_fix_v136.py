from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database.py"
PUBLIC = ROOT / "public_site.py"

# Verified Wikimedia Commons file page:
# Budapest, view from the Fisherman's Bastion to the Hungarian Parliament Building.jpg
BUDAPEST_IMAGE = "https://commons.wikimedia.org/wiki/Special:Redirect/file/Budapest%2C_view_from_the_Fisherman%27s_Bastion_to_the_Hungarian_Parliament_Building.jpg"

# 1) Replace the broken/obsolete Budapest image mapping used by old and new offers.
db = DATABASE.read_text(encoding="utf-8")n
old = '"BUD": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Hungarian_Parliament_Building_from_Fisherman%27s_Bastion.jpg"'
new = f'"BUD": "{BUDAPEST_IMAGE}"'
if old in db:
    db = db.replace(old, new, 1)
elif new not in db:
    raise RuntimeError("Budapest destination-image mapping anchor not found")
DATABASE.write_text(db, encoding="utf-8")

# 2) Decorate every rendered offer from the current destination mapping. This makes
# existing DB deals get the image immediately; no new scan is required.
public = PUBLIC.read_text(encoding="utf-8")
needle = '''def _localize_offer_airports(offer: dict) -> dict:\n    dep = _AIRPORT_LOCALIZATION.get(offer.get("departure_code"), {})\n    arr = _AIRPORT_LOCALIZATION.get(offer.get("arrival_code"), {})\n'''
replacement = '''def _localize_offer_airports(offer: dict) -> dict:\n    dep = _AIRPORT_LOCALIZATION.get(offer.get("departure_code"), {})\n    arr = _AIRPORT_LOCALIZATION.get(offer.get("arrival_code"), {})\n    # Destination imagery is render-time data, not scan-time data. This ensures\n    # historical offers also receive newly fixed destination photos immediately.\n    mapped_image = DESTINATION_LANDMARK_IMAGES.get(str(offer.get("arrival_code") or "").upper())\n    if mapped_image:\n        offer["destination_image_url"] = mapped_image\n'''
if replacement not in public:
    if needle not in public:
        raise RuntimeError("offer localization anchor not found")
    public = public.replace(needle, replacement, 1)
PUBLIC.write_text(public, encoding="utf-8")

print("9.7.136 Budapest image fixed for existing and future deals")
