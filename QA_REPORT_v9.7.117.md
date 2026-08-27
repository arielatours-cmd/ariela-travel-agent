# QA Report v9.7.117

## Closed changes included
- Removed standard-questionnaire cabin class and ticket flexibility choices; these will be informational on the deal card only in the supplier-enrichment phase.
- Removed `Connections are OK / קונקשן אפשרי`; direct-flight behavior otherwise unchanged.
- Open-destination recommendation ranking is transparent: +1 per customer condition met, +1 seasonal-fit point, global deal score only breaks ties.
- Robustly hides the date-priority option when no concrete dates/months were selected.
- Selecting `Ariella chooses` destination clears previously selected destination(s) from actual form state.
- Back-navigation restores defaults: friends=2; family=2 adults + 1 child.
- Removed duplicate flexible-date summary from My Vacations.
- Added approved subtle gold ornament above the alternative-deals message.

## Automated QA
- Python compile: PASS
- Jinja parse: 24/24 templates per template tree PASS
- Standard form has no cabin/flex/connection-allowed controls: PASS
- `force-hidden` override exists for date-priority regression: PASS
