import os
from flask import Flask, jsonify, request, redirect, abort
from scanner import search_flights, scan_configured_routes
from deals import create_booking_token, verify_booking_token, calculate_service_fee
from scoring import calculate_deal_score
from formatter import build_daily_message
from schedule_rules import delivery_status

app = Flask(__name__)

@app.get('/')
def home():
    return jsonify({'name':'Ariella Tours','version':'5.0','status':'online','endpoints':{'health':'/health','deals':'/deals','message_preview':'/message-preview','delivery_status':'/delivery-status'}})

@app.get('/health')
def health():
    return jsonify({'status':'ok','serpapi_configured':bool(os.getenv('SERPAPI_API_KEY')),'booking_secret_configured':bool(os.getenv('BOOKING_LINK_SECRET'))})

@app.get('/delivery-status')
def delivery_status_route():
    return jsonify(delivery_status())

@app.get('/search')
def search():
    departure=request.args.get('departure','TLV').upper(); arrival=request.args.get('arrival','').upper(); outbound=request.args.get('outbound',''); return_date=request.args.get('return_date','')
    if not arrival or not outbound: return jsonify({'status':'error','message':'Missing arrival or outbound'}),400
    try:
        return jsonify(search_flights(departure,arrival,outbound,return_date or None,request.args.get('adults','1'),request.args.get('children','0'),request.args.get('carry_on_bags','0')))
    except Exception as exc: return jsonify({'status':'error','message':str(exc)}),500

def _build_deals():
    scan_result=scan_configured_routes(); output=[]
    for result in scan_result.get('all_results',[]):
        if result.get('status')!='success': continue
        cheapest=(result.get('cheapest_flights') or [{}])[0]; price=cheapest.get('price'); typical_low=result.get('deal_analysis',{}).get('typical_price_low')
        savings=max(0,typical_low-price) if isinstance(price,(int,float)) and isinstance(typical_low,(int,float)) else None
        score=calculate_deal_score(result.get('deal_analysis',{}),cheapest)
        if not score['send_alert']: continue
        fee=calculate_service_fee(price,savings)
        token=create_booking_token({'route':result.get('route'),'flight_price':price,'service_fee':fee,'booking_url':result.get('google_flights_url')})
        output.append({**result,'deal_score':score,'service_fee_ils':fee,'estimated_savings_ils':savings,'booking_link_expires_in_minutes':30,'payment_placeholder_url':f'/pay/{token}'})
    output.sort(key=lambda d:d['deal_score']['score'],reverse=True)
    return scan_result, output[:5]

@app.get('/scan')
def scan():
    try: return jsonify(scan_configured_routes())
    except Exception as exc: return jsonify({'status':'error','message':str(exc)}),500

@app.get('/deals')
def deals():
    try:
        scan_result, output=_build_deals(); return jsonify({'status':'success','count':len(output),'maximum_daily_deals':5,'minimum_score_to_send':70,'searches_used':scan_result.get('searches_used'),'deals':output})
    except Exception as exc: return jsonify({'status':'error','message':str(exc)}),500

@app.get('/message-preview')
def message_preview():
    try:
        scan_result, output=_build_deals(); message=build_daily_message(output,scan_result.get('searches_used',0),scan_result.get('scan_dates',{}).get('outbound',{}).get('display_he'))
        return jsonify({'status':'success','message':message,'deal_count':len(output)})
    except Exception as exc: return jsonify({'status':'error','message':str(exc)}),500

@app.get('/pay/<token>')
def pay_placeholder(token):
    data=verify_booking_token(token)
    if not data: abort(410,description='This booking link expired or is invalid.')
    return jsonify({'status':'payment_required','service_fee_ils':data.get('service_fee'),'flight_price_ils':data.get('flight_price'),'route':data.get('route'),'message':'Payment provider is not connected yet.'})

@app.get('/book/<token>')
def book(token):
    data=verify_booking_token(token)
    if not data: abort(410,description='This booking link expired or is invalid.')
    url=data.get('booking_url')
    if not url: return jsonify({'status':'error','message':'No booking URL'}),400
    return redirect(url,code=302)

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))
