from datetime import datetime
from zoneinfo import ZoneInfo
from config import ISRAEL_TZ

TZ = ZoneInfo(ISRAEL_TZ)


def delivery_status(now=None):
    now = now or datetime.now(TZ)
    weekday = now.weekday()  # Monday=0, Friday=4, Saturday=5
    summer_time = bool(now.dst())

    if weekday == 4 and not summer_time:
        return {"allowed": False, "reason": "בחורף לא שולחים ביום שישי", "current_time": now.isoformat()}
    if weekday == 5 and summer_time:
        return {"allowed": False, "reason": "בקיץ לא שולחים בשבת", "current_time": now.isoformat()}
    if weekday == 4 and summer_time and now.hour >= 16:
        return {"allowed": False, "reason": "בקיץ משלוח שישי נעצר לפני כניסת שבת; השעה המדויקת תוגדר בהמשך", "current_time": now.isoformat()}
    if weekday == 5 and not summer_time and now.hour < 19:
        return {"allowed": False, "reason": "בחורף משלוח שבת ממתין למוצאי שבת", "current_time": now.isoformat()}
    return {"allowed": True, "reason": "מותר לשלוח לפי כללי ה-MVP", "current_time": now.isoformat()}
