# QA — Ariella Connected Trip — 2026-09-14

## Code-level checks completed

- [x] Initial service selector supports: flights, lodging, attractions, itinerary, rental car.
- [x] Service-specific question routing exists in `travel_agents.py`.
- [x] Flight flow retains destination/dates/travelers/budget/origin/direct-vs-connection/baggage fields.
- [x] Lodging flow includes property type, hotel room count or apartment/villa bedrooms + bathrooms, lodging budget, location priorities and amenities.
- [x] Rental-car flow includes pickup/drop-off, driver age, vehicle type, transmission, budget and required features.
- [x] Attraction loader merges the original attraction DB with `data/attractions_global30.json`.
- [x] Attraction coverage seed now spans 30 countries.
- [x] Scanner universe expanded with TIA, DXB, GYD and RMO so the configured destination universe covers 30 countries.
- [x] Duplicate legacy greeting is suppressed in the Ariella chat runtime and duplicate stored greetings are collapsed.
- [x] User messages are saved before the AI request returns, so refresh during a request does not lose the latest user message.
- [x] Legacy automatic `location.reload()` polling is neutralized for `#vacation-<id>` pages to stop repeated page refreshes.
- [x] Cache version bumped for the new chat runtime.

## Data/schema status

- `data/attractions.json` — existing Croatia/Thailand seed.
- `data/attractions_global30.json` — first attraction coverage row for each of 30 scanner countries, with official/official-tourism links where available. This is coverage seed, not final depth.
- `data/lodging_preferences.json` — production search/filter schema ready. Live property inventory provider is not connected yet.
- `data/car_preferences.json` — production search/filter schema ready. Live rental inventory provider is not connected yet.

## Open QA / blockers

- [ ] Live Render E2E must verify the new service picker and all branch transitions after deployment.
- [ ] Ariella/Tinkerbell chat still needs a production-safe trigger into the existing `run_customer_trip_search` flow plus result retrieval back into chat. Do not claim a flight search has started until the scanner job is actually queued.
- [ ] Lodging and rental-car result inventory requires a provider/API connection. Schema alone must not generate invented properties or cars.
- [ ] Conversation history is still primarily browser-local; per-user/per-trip database persistence is required for cross-device memory and historical travel context.
- [ ] Attraction depth must continue beyond the first coverage row per country; Croatia/Thailand are deeper than the newly added countries.

## Decisions for morning meeting

1. Approve preferred live inventory provider for lodging + rental car. Candidate to evaluate first: Booking.com Demand API, because one integration can cover accommodation and cars; credentials/partner access are required before E2E inventory QA.
2. Decide whether Ariella should default-select flights in the service picker or require the customer to explicitly select every service. Current implementation requires explicit selection.
3. Decide minimum attraction depth per country for launch (recommend at least 15–20 curated entries per high-volume country, then expand by traffic).
4. Prioritize DB-backed conversation memory before launch so Ariella can reuse prior trip context without assuming the next trip is identical.

## Payment / account actions

- OpenAI API: initial $5 credit already funded for testing.
- Lodging/car provider: no fixed public API payment amount has been validated in code QA. Partner/API onboarding and commercial terms must be confirmed before any payment is approved.
