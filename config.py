import os
from pathlib import Path

APP_VERSION = "7.1"
ISRAEL_TZ = "Asia/Jerusalem"

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "data" / "ariella.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "").strip()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
SCANNER_ENABLED = os.getenv("SCANNER_ENABLED", "true").lower() == "true"
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"
MAX_SEARCHES_PER_SCAN = int(os.getenv("MAX_SEARCHES_PER_SCAN", "8"))
MIN_DEAL_SCORE = int(os.getenv("MIN_DEAL_SCORE", "70"))
MAX_DAILY_DEALS = int(os.getenv("MAX_DAILY_DEALS", "5"))
DAILY_SEND_HOUR = int(os.getenv("DAILY_SEND_HOUR", "17"))
DAILY_SEND_MINUTE = int(os.getenv("DAILY_SEND_MINUTE", "0"))

DESTINATIONS = [
    {"code": "ATH", "name": "אתונה", "country_flag": "🇬🇷"},
    {"code": "LCA", "name": "לרנקה", "country_flag": "🇨🇾"},
    {"code": "BUD", "name": "בודפשט", "country_flag": "🇭🇺"},
    {"code": "VIE", "name": "וינה", "country_flag": "🇦🇹"},
    {"code": "SOF", "name": "סופיה", "country_flag": "🇧🇬"},
    {"code": "PRG", "name": "פראג", "country_flag": "🇨🇿"},
    {"code": "FCO", "name": "רומא", "country_flag": "🇮🇹"},
    {"code": "MXP", "name": "מילאנו", "country_flag": "🇮🇹"},
]

DEPARTURE_AIRPORTS = ["TLV", "HFA"]
DEPARTURE_OFFSETS_DAYS = [21, 35, 45, 60, 90, 120, 150, 180]
TRIP_LENGTHS_DAYS = [4, 5, 7]

AIRPORT_NAMES = {
    "TLV": "נתב״ג", "HFA": "חיפה", "ATH": "אתונה", "LCA": "לרנקה",
    "BUD": "בודפשט", "VIE": "וינה", "SOF": "סופיה", "PRG": "פראג",
    "FCO": "רומא", "MXP": "מילאנו",
}
