import json
import os
from datetime import date
from flask import Blueprint, jsonify, request
from ariella_chat_clean import chat_clean
from travel_agents import (_member_context,_persist_gender,_normalize_services,_travel_matches,_flight_handoff,_load_json,_LODGING_SCHEMA_FILE,_CAR_SCHEMA_FILE,_openai_json,_conversation)
from lodging_providers import lodging_inventory_status

ariella_chat_v2=Blueprint('ariella_chat_v2',__name__)
ENGINE_VERSION='contextual-chat-v15'
SYSTEM='''את אריאלה, סוכנת נסיעות אישית. הגיבי בשיחה טבעית ובהקשר. אל תשאלי שוב מידע שכבר נאמר. החזירי JSON עם profile_patch, reply, intent, unclear.'''

def _clean_patch(value): return {k:v for k,v in value.items() if v is not None} if isinstance(value,dict) else {}
def _has_destination(p): return bool(p.get('destinations')) or p.get('destination_mode') in {'open','ariella','flexible'}
def _has_dates(p): return bool((p.get('departure_date') and p.get('return_date')) or p.get('outbound_month'))
def _has_travelers(p):
    try:return int(p.get('adults') or 0)>0
    except (TypeError,ValueError):return False
def _has_budget(p): return bool(p.get('budget_mode') or p.get('budget_amount') not in (None,''))
def _stage(p):
    if not p.get('vacation_type'):return 'purpose'
    if not _has_destination(p):return 'destination'
    if not _has_dates(p):return 'dates'
    if not _has_travelers(p):return 'travelers'
    if not p.get('flight_preference') or not p.get('baggage'):return 'flight_preferences'
    if not _has_budget(p):return 'budget'
    return 'confirm'
def _single_pass(message,history,profile):
    key=os.getenv('OPENAI_API_KEY','').strip()
    if not key:raise RuntimeError('OPENAI_API_KEY is not configured')
    model=os.getenv('ARIELLA_MODEL','gpt-5.6-luna').strip()
    context={'current_date':date.today().isoformat(),'known_trip_context':profile}
    result=_openai_json(key,model,SYSTEM+'\n'+json.dumps(context,ensure_ascii=False),_conversation((history or [])[-6:],message),max_output_tokens=280)
    if not isinstance(result,dict):result={}
    result['profile_patch']=_clean_patch(result.get('profile_patch'))
    return result

# NEW EXPERIMENT: the live URL bypasses the legacy intake engine completely.
@ariella_chat_v2.post('/api/ariella/chat')
def ariella_chat_clean_live():
    return chat_clean()

@ariella_chat_v2.post('/api/ariella/chat-clean')
def ariella_chat_clean_direct():
    return chat_clean()

# OLD ENGINE IS PRESERVED HERE FOR COMPARISON/ROLLBACK. It is no longer used by the UI.
@ariella_chat_v2.post('/api/ariella/chat-legacy')
def ariella_chat_legacy():
    body=request.get_json(silent=True) or {}
    message=str(body.get('message') or '').strip()
    if not message:return jsonify({'status':'error','message':'message is required'}),400
    profile=dict(body.get('profile') if isinstance(body.get('profile'),dict) else {})
    history=body.get('history') if isinstance(body.get('history'),list) else []
    if 'known_companions' not in profile or 'member_context_loaded' not in profile:
        member=_member_context()
        if member:
            if member.get('gender') and not profile.get('customer_gender'):profile['customer_gender']=member.get('gender')
            profile['known_companions']=member.get('companions') or []
            if profile.get('customer_gender'):_persist_gender(member['id'],profile.get('customer_gender'))
        else:profile.setdefault('known_companions',[])
        profile['member_context_loaded']=True
    if not profile.get('departure_airports'):profile['departure_airports']=['TLV']
    try:result=_single_pass(message,history,profile)
    except Exception as exc:return jsonify({'status':'error','message':'אריאלה לא זמינה כרגע.','detail':str(exc),'engine_version':ENGINE_VERSION}),503
    merged=dict(profile);merged.update(result.get('profile_patch') or {});merged['services']=_normalize_services(merged.get('services'))
    if merged.get('vacation_type'):
        if not merged['services']:merged['services']=['flight']
        elif 'flight' not in merged['services']:merged['services'].insert(0,'flight')
    stage=_stage(merged);complete=stage=='confirm';services=merged.get('services') or [];reply=str(result.get('reply') or '').strip() or 'ספרי לי עוד 😊'
    travel=_travel_matches(merged) if complete and ('attractions' in services or 'route' in services) else []
    lodging_status=lodging_inventory_status() if complete and 'lodging' in services else {'providers':[],'live_provider_count':0,'live_inventory_available':False}
    return jsonify({'status':'success','agent':'Ariella','engine_version':ENGINE_VERSION,'reply':reply,'profile':merged,'intent':result.get('intent') or 'conversation','missing_question':'','stage':stage,'services':services,'ready_for_flights':complete and 'flight' in services,'flight_search_started':False,'ready_for_lodging':complete and 'lodging' in services,'ready_for_car':complete and 'car' in services,'ready_for_travel':bool(travel),'intake_complete':complete,'requires_confirmation':complete,'tinkerbell_handoff':_flight_handoff(merged),'travel_agent':{'attractions':travel},'lodging_schema':_load_json(_LODGING_SCHEMA_FILE,{}) if complete and 'lodging' in services else {},'car_schema':_load_json(_CAR_SCHEMA_FILE,{}) if complete and 'car' in services else {},'inventory_status':{'lodging':lodging_status,'car':'provider_pending'}})
