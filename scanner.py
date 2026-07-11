import os
from datetime import date,timedelta,datetime
import requests
SERPAPI_URL='https://serpapi.com/search.json'
DESTINATIONS=[{'code':'ATH','name':'אתונה','country_flag':'🇬🇷'},{'code':'LCA','name':'לרנקה','country_flag':'🇨🇾'},{'code':'BUD','name':'בודפשט','country_flag':'🇭🇺'},{'code':'VIE','name':'וינה','country_flag':'🇦🇹'},{'code':'SOF','name':'סופיה','country_flag':'🇧🇬'},{'code':'PRG','name':'פראג','country_flag':'🇨🇿'},{'code':'FCO','name':'רומא','country_flag':'🇮🇹'},{'code':'MXP','name':'מילאנו','country_flag':'🇮🇹'}]
AIRPORT_NAMES={'TLV':'נתב״ג','HFA':'חיפה','ATH':'אתונה','LCA':'לרנקה','BUD':'בודפשט','VIE':'וינה','SOF':'סופיה','PRG':'פראג','FCO':'רומא','MXP':'מילאנו'}
HEBREW_WEEKDAYS={0:'יום שני',1:'יום שלישי',2:'יום רביעי',3:'יום חמישי',4:'יום שישי',5:'שבת',6:'יום ראשון'}
def _api_key():
    key=os.getenv('SERPAPI_API_KEY','').strip()
    if not key: raise RuntimeError('SERPAPI_API_KEY is missing in Render Environment.')
    return key
def _date_with_weekday(value):
    if not value:return None
    dt=datetime.strptime(value,'%Y-%m-%d'); return {'date':value,'weekday_he':HEBREW_WEEKDAYS[dt.weekday()],'display_he':f"{HEBREW_WEEKDAYS[dt.weekday()]}, {dt.strftime('%d.%m.%Y')}"}
def _sum_flight_minutes(segments):
    total=sum(s.get('duration') or 0 for s in segments); return total or None
def _summarize_flight(item):
    segments=item.get('flights') or []; first=segments[0] if segments else {}; last=segments[-1] if segments else {}; dep=first.get('departure_airport') or {}; arr=last.get('arrival_airport') or {}; layovers=item.get('layovers') or []
    connections=[{'airport':x.get('name') or x.get('id') or 'שדה ביניים','duration_minutes':x.get('duration')} for x in layovers]
    total=item.get('total_duration'); actual=_sum_flight_minutes(segments)
    if actual is None and isinstance(total,(int,float)): actual=max(0,total-sum(x.get('duration_minutes') or 0 for x in connections))
    return {'price':item.get('price'),'airline':first.get('airline'),'flight_number':first.get('flight_number'),'departure_airport':dep.get('id'),'departure_airport_name':AIRPORT_NAMES.get(dep.get('id'),dep.get('id')),'departure_time':dep.get('time'),'arrival_airport':arr.get('id'),'arrival_airport_name':AIRPORT_NAMES.get(arr.get('id'),arr.get('id')),'arrival_time':arr.get('time'),'total_duration_minutes':total,'actual_flight_duration_minutes':actual,'stops':len(layovers),'is_direct':len(layovers)==0,'connections':connections,'baggage':{'personal_item':{'included':True,'price_each_way':0,'estimated':True},'carry_on_8kg':{'included':False,'price_each_way':None,'estimated':True},'checked_bag_23kg':{'included':False,'price_each_way':None,'estimated':True}}}
def _deal_analysis(data):
    insights=data.get('price_insights') or {}; lowest=insights.get('lowest_price'); typical=insights.get('typical_price_range') or []; level=str(insights.get('price_level') or '').lower(); low=typical[0] if len(typical)>=2 else None; high=typical[1] if len(typical)>=2 else None; discount=None
    if isinstance(lowest,(int,float)) and isinstance(low,(int,float)) and low>0: discount=round((low-lowest)/low*100,1)
    return {'is_exceptional_deal':level=='low' or (discount is not None and discount>=15),'price_level':level or None,'lowest_price':lowest,'typical_price_low':low,'typical_price_high':high,'below_typical_low_percent':discount}
def search_flights(departure,arrival,outbound_date,return_date=None,adults='1',children='0',carry_on_bags='0'):
    params={'engine':'google_flights','api_key':_api_key(),'departure_id':departure,'arrival_id':arrival,'outbound_date':outbound_date,'hl':'en','gl':'il','currency':'ILS','travel_class':'1','adults':adults,'children':children,'bags':carry_on_bags,'sort_by':'2','deep_search':'true'}
    if return_date: params['type']='1'; params['return_date']=return_date
    else: params['type']='2'
    response=requests.get(SERPAPI_URL,params=params,timeout=60); response.raise_for_status(); data=response.json()
    if data.get('error'): raise RuntimeError(data['error'])
    flights=(data.get('best_flights') or [])+(data.get('other_flights') or []); flights=[f for f in flights if isinstance(f.get('price'),(int,float))]; flights.sort(key=lambda f:f['price']); metadata=data.get('search_metadata') or {}
    return {'status':'success','route':f'{departure}-{arrival}','departure_airport_name':AIRPORT_NAMES.get(departure,departure),'arrival_airport_name':AIRPORT_NAMES.get(arrival,arrival),'outbound':_date_with_weekday(outbound_date),'return':_date_with_weekday(return_date),'deal_analysis':_deal_analysis(data),'cheapest_flights':[_summarize_flight(f) for f in flights[:5]],'google_flights_url':metadata.get('google_flights_url')}
def scan_configured_routes():
    outbound=date.today()+timedelta(days=45); return_date=outbound+timedelta(days=5); results=[]
    for destination in DESTINATIONS:
        try:
            result=search_flights('TLV',destination['code'],outbound.isoformat(),return_date.isoformat(),carry_on_bags='1'); result['destination_name']=destination['name']; result['country_flag']=destination['country_flag']; results.append(result)
        except Exception as exc: results.append({'status':'error','destination':destination,'message':str(exc)})
    return {'status':'success','scan_dates':{'outbound':_date_with_weekday(outbound.isoformat()),'return':_date_with_weekday(return_date.isoformat())},'searches_used':len(DESTINATIONS),'all_results':results}
