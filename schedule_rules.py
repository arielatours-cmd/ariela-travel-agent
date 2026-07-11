from datetime import datetime
from zoneinfo import ZoneInfo
ISRAEL_TZ=ZoneInfo('Asia/Jerusalem')
def delivery_status(now=None):
    now=now or datetime.now(ISRAEL_TZ)
    return {'timezone':'Asia/Jerusalem','current_time':now.isoformat(),'daily_send_hour':17,'maximum_deals':5,'friday_rule':'Send at 17:00 only when it is before candle-lighting.','shabbat_rule':'Do not send between candle-lighting and havdalah.','saturday_night_rule':'Send 30 minutes after havdalah after rechecking prices.','ready_for_live_scheduling':False,'missing_dependency':'Jewish calendar source for exact candle-lighting and havdalah times.'}
