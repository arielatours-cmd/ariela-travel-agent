# Ariella QA — v9.7.98

## BOOKER contract corrected
- BOOKER sends the customer only to Ariella's recommended supplier.
- It no longer exposes Google Flights/competing supplier options as a fallback.
- The stored booking_request for the recommended supplier is primary.
- If it must refresh booking options, it accepts only the same recommended supplier.
- For airline sites such as EL AL, success means correct route/dates and the airline's own small set of same-day flight choices/fare families. The customer controls fare selection and payment.
- If the recommended supplier handoff is unavailable, BOOKER fails closed instead of showing competing sellers.

## +1 arrival fix
- Scanner now persists arrival_date from SerpApi's timestamp.
- Return arrival_date is persisted for the selected inbound flight.
- Existing card logic therefore receives arrival_days_after / return_arrival_days_after correctly for newly scanned offers, including overnight arrivals such as 23:55 -> 00:35 (+1).

## QA
- Python compilation passed.
- Jinja parsing passed.
- No marketplace fallback remains in BOOKER.
- Recommended-supplier-only refresh is wired.
