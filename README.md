# Ariella Tours v3

New:
- Hebrew weekday beside dates
- Consolidated deal list at /deals
- Fee = 10% of flight price minus 5 ILS
- Fee cap = half of estimated savings
- Booking links expire after 30 minutes
- Placeholder payment page

Required Render variables:
- SERPAPI_API_KEY
- BOOKING_LINK_SECRET

Test:
- /health
- /search?departure=TLV&arrival=ATH&outbound=2026-09-10&return_date=2026-09-15
- /scan
- /deals

Payment and WhatsApp are not connected yet.
