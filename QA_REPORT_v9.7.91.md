# Ariella QA — v9.7.95

## Critical booking-flow fix
Live QA found that an EL AL booking-request deep link could open the airline with the selected search context but no usable Continue button.

v9.7.95 changes the contract:
- Ariella no longer silently auto-submits/redirects the customer to a third-party booking form.
- `/book/<offer>` now opens an Ariella booking handoff page first.
- The page clearly repeats outbound, return, airline and price.
- It resolves the best stored/refreshed booking target for the exact booking token.
- If the supplier requires POST data, the customer explicitly submits it from the handoff page.
- When available, the Google Flights/result URL is retained as a fallback if the supplier path cannot continue.
- If no reliable target exists, Ariella says so instead of stranding the customer.

## QA passed
- Python compilation
- Jinja parsing
- booking route no longer directly redirects exact booking requests
- handoff template exists and supports GET/POST supplier targets
- fallback path is preserved
- inherited v9.7.90 airport catalogue and prior scan/test-mode fixes preserved

## Live regression required
Test EL AL first. Then test at least two additional suppliers/airlines. A booking flow passes only if the external site provides a usable next step toward purchase.
