from datetime import datetime
def _hour(value):
    if not value:return None
    try:return datetime.strptime(value,'%Y-%m-%d %H:%M').hour
    except ValueError:return None
def calculate_deal_score(deal_analysis,flight):
    score=0; reasons=[]; discount=deal_analysis.get('below_typical_low_percent')
    if isinstance(discount,(int,float)):
        points=min(50,max(0,round(discount*2))); score+=points; reasons.append(f'מחיר נמוך מהטווח הרגיל: +{points}')
    elif deal_analysis.get('price_level')=='low': score+=35; reasons.append('Google מסמן את המחיר כנמוך: +35')
    stops=flight.get('stops',0)
    if stops==0: score+=20; reasons.append('טיסה ישירה: +20')
    elif stops==1: score+=8; reasons.append('קונקשן אחד: +8')
    duration=flight.get('total_duration_minutes')
    if isinstance(duration,(int,float)):
        if duration<=180: score+=10
        elif duration<=300: score+=6
        elif duration<=480: score+=3
    dh=_hour(flight.get('departure_time')); ah=_hour(flight.get('arrival_time'))
    if dh is not None and 6<=dh<=21: score+=5
    if ah is not None and 6<=ah<=23: score+=5
    score=min(100,score); label='דיל חריג במיוחד' if score>=85 else 'דיל מצוין' if score>=70 else 'דיל טוב' if score>=55 else 'לא לשלוח'
    return {'score':score,'label':label,'send_alert':score>=70,'reasons':reasons}
