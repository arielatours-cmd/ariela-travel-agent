import os
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

TOKEN_MAX_AGE_SECONDS = 1800

def _serializer():
    secret = os.getenv("BOOKING_LINK_SECRET", "temporary-development-secret")
    return URLSafeTimedSerializer(secret, salt="ariella-booking-link")

def calculate_service_fee(flight_price, savings):
    if not isinstance(flight_price, (int, float)) or flight_price <= 0:
        return 0
    regular_fee = max(0, flight_price * 0.10 - 5)
    if isinstance(savings, (int, float)) and savings > 0:
        regular_fee = min(regular_fee, savings / 2)
    return round(regular_fee, 2)

def create_booking_token(data):
    return _serializer().dumps(data)

def verify_booking_token(token):
    try:
        return _serializer().loads(token, max_age=TOKEN_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
