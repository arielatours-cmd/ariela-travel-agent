# Ariella QA — v9.7.104 / BOOKER

## BOOKER introduced
BOOKER is now a supplier-aware booking orchestrator.

### Behavior
- No Ariella intermediary page.
- Uses exact stored booking_request when the supplier is considered actionable.
- Refreshes the exact booking token when necessary.
- Does not prefer a supplier flow already proven by live QA to strand the user.
- EL AL direct booking_request is currently classified as unreliable because live testing showed route/date context but no usable continuation after flight selection.
- If an actionable exact supplier option exists, BOOKER sends the customer there.
- Otherwise BOOKER falls back to the stored Google Flights/result context instead of pretending the airline flow is exact.
- BOOKER never purchases or submits payment.

### Important limitation
A public/stable EL AL deep link that preselects the exact outbound and return flights was not found in the current booking flow. Therefore v9.7.104 does not claim to automate EL AL flight selection when the airline itself does not expose an actionable handoff.

### QA
- Python compilation passed
- Jinja templates passed
- BOOKER module import/route wiring passed
- Known-broken EL AL direct flow is excluded from preferred targets
- No extra Ariella handoff page remains
