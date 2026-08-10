import os
from pathlib import Path

APP_VERSION = "9.4.9-header-auth-final"
ISRAEL_TZ = "Asia/Jerusalem"

BASE_DIR = Path(__file__).resolve().parent

# Persistent database:
# - Render production: DB_PATH is set to /var/data/ariella.db by render.yaml.
# - Local development: falls back to ./data/ariella.db.
_default_db_path = BASE_DIR / "data" / "ariella.db"
DB_PATH = Path(os.getenv("DB_PATH", str(_default_db_path))).expanduser()
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


# WhatsApp Cloud API — store real values only in Render Environment Variables.
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
WHATSAPP_RECIPIENT = os.getenv("WHATSAPP_RECIPIENT", "").strip()
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v23.0").strip()

# Public website sessions. Set a long random value in Render.
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "change-this-before-production")


# Feedback form email delivery.
# For Gmail, MAIL_APP_PASSWORD must be a Google App Password, not the regular password.
FEEDBACK_TO_EMAIL = os.getenv("FEEDBACK_TO_EMAIL", "arielatours@gmail.com").strip()
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "").strip()
MAIL_APP_PASSWORD = os.getenv("MAIL_APP_PASSWORD", "").strip()
MAIL_SMTP_HOST = os.getenv("MAIL_SMTP_HOST", "smtp.gmail.com").strip()
MAIL_SMTP_PORT = int(os.getenv("MAIL_SMTP_PORT", "465"))
