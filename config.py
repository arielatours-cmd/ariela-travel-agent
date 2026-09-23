import os
from pathlib import Path

APP_VERSION = "9.7.143-connected-trip"
ISRAEL_TZ = "Asia/Jerusalem"

BASE_DIR = Path(__file__).resolve().parent
_default_db_path = BASE_DIR / "data" / "ariella.db"
DB_PATH = Path(os.getenv("DB_PATH", str(_default_db_path))).expanduser()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "").strip()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
SCANNER_ENABLED = os.getenv("SCANNER_ENABLED", "true").lower() == "true"
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"
MAX_SEARCHES_PER_SCAN = int(os.getenv("MAX_SEARCHES_PER_SCAN", "8"))
CUSTOMER_SCAN_MAX_API_REQUESTS = int(os.getenv("CUSTOMER_SCAN_MAX_API_REQUESTS", "120"))
MONTHLY_SCAN_REUSE_HOURS = int(os.getenv("MONTHLY_SCAN_REUSE_HOURS", "12"))
MIN_DEAL_SCORE = max(80, int(os.getenv("MIN_DEAL_SCORE", "80")))
MAX_DAILY_DEALS = int(os.getenv("MAX_DAILY_DEALS", "5"))
DAILY_SEND_HOUR = int(os.getenv("DAILY_SEND_HOUR", "17"))
DAILY_SEND_MINUTE = int(os.getenv("DAILY_SEND_MINUTE", "0"))
WIDE_SCAN_HOUR = int(os.getenv("WIDE_SCAN_HOUR", "6"))
WIDE_SCAN_MINUTE = int(os.getenv("WIDE_SCAN_MINUTE", "15"))
WIDE_SCAN_DESTINATION_LIMIT = int(os.getenv("WIDE_SCAN_DESTINATION_LIMIT", "30"))

# Personal-vacation paid daily tracking (after the free first scan). One-time
# payment per period, never an auto-renewing subscription - no card details
# are stored. "update" piggybacks on the existing general deals scan; "scan"
# adds a dedicated daily search just for that customer's request at noon.
PERSONAL_SEARCH_DAILY_SCAN_HOUR = int(os.getenv("PERSONAL_SEARCH_DAILY_SCAN_HOUR", "12"))
PERSONAL_SEARCH_DAILY_SCAN_MINUTE = int(os.getenv("PERSONAL_SEARCH_DAILY_SCAN_MINUTE", "0"))
# The one-time free scan may explore a whole flexible-date window (up to
# CUSTOMER_SCAN_MAX_API_REQUESTS). The recurring PAID daily re-scan must not:
# it already knows the best dates from that first scan, so it only needs to
# refresh a couple of jobs a day, not re-explore the flex window every day at
# exploratory cost - see the SerpAPI-cost math behind the 19/39 ILS pricing.
PERSONAL_SEARCH_DAILY_SCAN_MAX_API_REQUESTS = int(os.getenv("PERSONAL_SEARCH_DAILY_SCAN_MAX_API_REQUESTS", "3"))

# Booking.com affiliate program, via CJ Affiliate (not the Demand API - that
# path is invite-only direct-with-Booking.com and confirmed unavailable to
# this account). CJ's own deep-link generator does not work for Booking.com's
# URL structure, so the destination URL is wrapped manually behind the
# "Evergreen" tracking link CJ issues per publisher (Links -> search
# "evergreen" in the CJ dashboard). Leave blank until that link is in hand -
# lodging search then just links straight to Booking.com, uncredited.
CJ_BOOKING_EVERGREEN_LINK = os.getenv("CJ_BOOKING_EVERGREEN_LINK", "").strip()
# Sold to the customer as "a month" (never shown as a raw day count) but kept
# internally at 30 real service days + the 4-day RENEWAL_REMINDER_DAYS_BEFORE
# buffer, so a customer who reacts slowly to the reminder email still gets
# the full month they paid for even in a 31-day calendar month. Do not
# "round" this back to 30 or 31.
SEARCH_PERIOD_DAYS = int(os.getenv("SEARCH_PERIOD_DAYS", "34"))
RENEWAL_REMINDER_DAYS_BEFORE = int(os.getenv("RENEWAL_REMINDER_DAYS_BEFORE", "4"))
PERSONAL_SEARCH_PLANS = {
    "update": {
        "price_ils": 19,
        "label_he": "עדכון יומי",
        "label_en": "Daily update",
        "desc_he": "עדכון פעם ביום אם נמצא דיל שמתאים ליעד, לתאריכים, לתקציב ולכבודה שביקשתם - מתוך הסריקה הכללית היומית.",
        "desc_en": "One update a day if a deal matching your destination, dates, budget and baggage turns up in the regular daily scan.",
    },
    "scan": {
        "price_ils": 39,
        "label_he": "סריקה יומית נוספת",
        "label_en": "Extra daily search",
        "desc_he": "סריקה ייעודית נוספת במיוחד בשבילכם כל יום בצהריים, בנוסף לעדכון הכללי בערב - פעמיים ביום.",
        "desc_en": "One extra dedicated search just for your trip every noon, on top of the evening update - twice a day.",
    },
}

DESTINATIONS = [
    {"code": "ATH", "name": "אתונה", "country_flag": "🇬🇷"}, {"code": "LCA", "name": "לרנקה", "country_flag": "🇨🇾"}, {"code": "PFO", "name": "פאפוס", "country_flag": "🇨🇾"},
    {"code": "BUD", "name": "בודפשט", "country_flag": "🇭🇺"}, {"code": "VIE", "name": "וינה", "country_flag": "🇦🇹"},
    {"code": "SOF", "name": "סופיה", "country_flag": "🇧🇬"}, {"code": "PRG", "name": "פראג", "country_flag": "🇨🇿"},
    {"code": "FCO", "name": "רומא", "country_flag": "🇮🇹"}, {"code": "MXP", "name": "מילאנו", "country_flag": "🇮🇹"},
    {"code": "CDG", "name": "פריז", "country_flag": "🇫🇷"}, {"code": "AMS", "name": "אמסטרדם", "country_flag": "🇳🇱"},
    {"code": "BCN", "name": "ברצלונה", "country_flag": "🇪🇸"}, {"code": "MAD", "name": "מדריד", "country_flag": "🇪🇸"},
    {"code": "LIS", "name": "ליסבון", "country_flag": "🇵🇹"}, {"code": "LHR", "name": "לונדון", "country_flag": "🇬🇧"},
    {"code": "BER", "name": "ברלין", "country_flag": "🇩🇪"}, {"code": "MUC", "name": "מינכן", "country_flag": "🇩🇪"},
    {"code": "ZRH", "name": "ציריך", "country_flag": "🇨🇭"}, {"code": "BRU", "name": "בריסל", "country_flag": "🇧🇪"},
    {"code": "OTP", "name": "בוקרשט", "country_flag": "🇷🇴"}, {"code": "KRK", "name": "קרקוב", "country_flag": "🇵🇱"},
    {"code": "WAW", "name": "ורשה", "country_flag": "🇵🇱"}, {"code": "TBS", "name": "טביליסי", "country_flag": "🇬🇪"},
    {"code": "EVN", "name": "ירוואן", "country_flag": "🇦🇲"}, {"code": "BEG", "name": "בלגרד", "country_flag": "🇷🇸"},
    {"code": "SKP", "name": "סקופיה", "country_flag": "🇲🇰"}, {"code": "TGD", "name": "פודגוריצה", "country_flag": "🇲🇪"},
    {"code": "ZAG", "name": "זאגרב", "country_flag": "🇭🇷"}, {"code": "LJU", "name": "לובליאנה", "country_flag": "🇸🇮"},
    {"code": "BKK", "name": "בנגקוק", "country_flag": "🇹🇭"}, {"code": "JFK", "name": "ניו יורק", "country_flag": "🇺🇸"},
    {"code": "TIA", "name": "טירנה", "country_flag": "🇦🇱"}, {"code": "DXB", "name": "דובאי", "country_flag": "🇦🇪"},
    {"code": "GYD", "name": "באקו", "country_flag": "🇦🇿"}, {"code": "RMO", "name": "קישינב", "country_flag": "🇲🇩"},
]

# The automatic/wide-search default is Ben Gurion. Haifa remains available
# when a customer explicitly selects it, but is not searched implicitly.
DEPARTURE_AIRPORTS = ["TLV"]
DEPARTURE_OFFSETS_DAYS = [21, 35, 45, 60, 90, 120, 150, 180]
TRIP_LENGTHS_DAYS = [4, 5, 7]

AIRPORT_NAMES = {
    "TLV": "נתב״ג", "HFA": "חיפה", "ATH": "אתונה", "LCA": "לרנקה", "PFO": "פאפוס", "BUD": "בודפשט", "VIE": "וינה",
    "SOF": "סופיה", "PRG": "פראג", "FCO": "רומא", "MXP": "מילאנו", "CDG": "פריז", "AMS": "אמסטרדם",
    "BCN": "ברצלונה", "MAD": "מדריד", "LIS": "ליסבון", "LHR": "לונדון", "BER": "ברלין", "MUC": "מינכן",
    "ZRH": "ציריך", "BRU": "בריסל", "OTP": "בוקרשט", "KRK": "קרקוב", "WAW": "ורשה", "TBS": "טביליסי",
    "EVN": "ירוואן", "BEG": "בלגרד", "SKP": "סקופיה", "TGD": "פודגוריצה", "ZAG": "זאגרב", "LJU": "לובליאנה",
    "BKK": "בנגקוק", "JFK": "ניו יורק", "TIA": "טירנה", "DXB": "דובאי", "GYD": "באקו", "RMO": "קישינב",
}

WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
WHATSAPP_RECIPIENT = os.getenv("WHATSAPP_RECIPIENT", "").strip()
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v23.0").strip()
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "change-this-before-production")
FEEDBACK_TO_EMAIL = os.getenv("FEEDBACK_TO_EMAIL", "arielatours@gmail.com").strip()
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "").strip()
MAIL_APP_PASSWORD = os.getenv("MAIL_APP_PASSWORD", "").strip()
MAIL_SMTP_HOST = os.getenv("MAIL_SMTP_HOST", "smtp.gmail.com").strip()
MAIL_SMTP_PORT = int(os.getenv("MAIL_SMTP_PORT", "465"))

# Deployment helpers materialize source changes during the build. Importing those
# mutation scripts at application startup made a second process try to patch the
# same files again and could prevent the Deals page/app from starting.
