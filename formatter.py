def _minutes_to_hhmm(minutes):
    if not isinstance(minutes,(int,float)):return 'לא ידוע'
    return f"{int(minutes)//60}:{int(minutes)%60:02d}"
def _extract_time(value): return value[-5:] if value else 'לא ידוע'
def _baggage_line(label,item):
    if item.get('included'):return f'✅ {label}'
    price=item.get('price_each_way')
    if isinstance(price,(int,float)):
        estimated='מחיר משוער: ' if item.get('estimated') else ''
        return f'❌ {label} — {estimated}{price:.0f} ₪ לאדם לכל כיוון'
    return f'❌ {label} — מחיר משוער יופיע לפני המעבר להזמנה'
def _reason_for_deal(deal,flight):
    stops=flight.get('stops',0)
    if stops==0:return 'הדיל הזה נבחר כי הוא משלב טיסה ישירה עם מחיר נמוך במיוחד.'
    if stops==1:return 'הדיל הזה נבחר כי המחיר נמוך במיוחד למרות קונקשן אחד.'
    return 'הדיל הזה נבחר כי החיסכון במחיר משמעותי גם לאחר שקלול שני הקונקשנים.'
def _route_color(stops): return '🟢' if stops==0 else '🟡' if stops==1 else '🔴'
def _format_connections(flight):
    stops=flight.get('stops',0)
    if stops==0:return f"🟢 טיסה ישירה
⏱️ משך הטיסה: {_minutes_to_hhmm(flight.get('total_duration_minutes'))} שעות"
    con=flight.get('connections') or []
    if stops==1:
        place=con[0].get('airport') if con else 'שדה ביניים'; wait=_minutes_to_hhmm(con[0].get('duration_minutes')) if con else 'לא ידוע'
        return f"🟡 קונקשן אחד – {place}
✈️ זמן טיסה: {_minutes_to_hhmm(flight.get('actual_flight_duration_minutes'))} │ ⏳ המתנה: {wait} │ 🕒 הגעה כוללת: {_minutes_to_hhmm(flight.get('total_duration_minutes'))}"
    places=' │ '.join([f"📍 {x.get('airport','שדה ביניים')}: {_minutes_to_hhmm(x.get('duration_minutes'))}" for x in con])
    return f"🔴 {stops} קונקשנים
{places}
✈️ זמן טיסה: {_minutes_to_hhmm(flight.get('actual_flight_duration_minutes'))} │ 🕒 הגעה כוללת: {_minutes_to_hhmm(flight.get('total_duration_minutes'))}"
def format_deal(deal):
    flight=(deal.get('cheapest_flights') or [{}])[0]; stops=flight.get('stops',0); color=_route_color(stops); flag=deal.get('country_flag',''); origin_name=deal.get('departure_airport_name') or 'מוצא'; dest_name=deal.get('arrival_airport_name') or deal.get('destination_name') or 'יעד'; origin_code=flight.get('departure_airport') or deal.get('route','').split('-')[0]; dest_code=flight.get('arrival_airport') or deal.get('route','').split('-')[-1]; outbound=deal.get('outbound') or {}; ret=deal.get('return') or {}; regular=deal.get('deal_analysis',{}).get('typical_price_low'); current=flight.get('price')
    price_line=f'**{current:.0f} ₪ לאדם**' if isinstance(current,(int,float)) else '**מחיר לא זמין**'
    if isinstance(regular,(int,float)) and isinstance(current,(int,float)): price_line=f'~~{regular:.0f} ₪~~ → **{current:.0f} ₪ לאדם**'
    baggage=flight.get('baggage') or {}
    inclusion='כולל מזוודה עד 23 ק״ג' if baggage.get('checked_bag_23kg',{}).get('included') else 'כולל טרולי' if baggage.get('carry_on_8kg',{}).get('included') else 'ללא כבודה'
    lines=[f'{color} {flag} **{origin_name} ({origin_code}) ✈ {dest_name} ({dest_code})**','', '🛫 **יציאה**',outbound.get('display_he',''),f"**{_extract_time(flight.get('departure_time'))} המראה** │ **{_extract_time(flight.get('arrival_time'))} נחיתה**",'', '🛬 **חזרה**',ret.get('display_he',''),'שעות החזרה יישלפו מתוצאת החזור המלאה בגרסה הבאה.','',f"✈️ **{flight.get('airline') or 'חברת תעופה'}**",'',_format_connections(flight),'',f'{price_line} ({inclusion})','', '🧳 **כבודה**',_baggage_line('תיק יד',baggage.get('personal_item',{})),_baggage_line('טרולי 8 ק״ג',baggage.get('carry_on_8kg',{})),_baggage_line('מזוודה עד 23 ק״ג',baggage.get('checked_bag_23kg',{})),'','✨ **דמי טיפול**',f"**{deal.get('service_fee_ils',0):.0f} ₪ לאדם**",'',f"⭐ {_reason_for_deal(deal,flight)}",'','⏳ קישור ההזמנה תקף ל־30 דקות.']
    return '
'.join(lines)
def build_daily_message(deals,scanned_options,date_label=None):
    if not deals:return ''
    header=['✈️ **הדילים של אריאלה**',date_label or '','',f'נסרקו היום **{scanned_options}** אפשרויות טיסה.',f'רק **{len(deals)} דילים** עברו את מנגנון האיכות של אריאלה.','']; body=[]
    for i,deal in enumerate(deals):
        if i:body.append('━━━━━━━━━━━━━━━━━━')
        body.append(format_deal(deal))
    return '
'.join(header+body)
