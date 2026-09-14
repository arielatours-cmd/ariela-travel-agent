# Ariella Connected Trip Flow

## Entry
Ariella starts with one service-selection card. The customer may select any combination:

- Flights
- Lodging
- Attractions
- Itinerary building
- Rental car

Ariella is the only customer-facing agent. Internal parsers/search agents are never named to the customer.

## Shared intake
Asked once and reused by every selected service:

1. Destination / open to suggestions
2. Exact dates or preferred month
3. Travellers: adults, children, infants and relevant ages

Ariella never repeats answers already captured.

## Flights branch
Only when Flights was selected:

1. Budget per person / unlimited
2. Departure airport(s)
3. Direct flight vs connections
4. Baggage
5. Date flexibility when relevant

Completion condition: all required flight fields are present. A flight search must never be described as started until a real scanner job is queued.

## Lodging branch
Only when Lodging was selected:

1. Property type: hotel / apartment / villa / resort / hostel / any
2. Apartment/villa: bedrooms + bathrooms
3. Hotel/resort: number of hotel rooms
4. Lodging budget: per night / total / unlimited
5. Location priority: center / quiet / beach / public transport / attractions / parking / Jewish community proximity / any
6. Amenities: kitchen, pool/private pool, balcony/garden, parking, lift, washing machine, accessibility, cot/high chair, breakfast, family room, connecting rooms, 24/7 reception, spa, gym, Wi‑Fi, pets
7. Hotel-only optional filters: meal plan and star rating
8. Free cancellation if important

Live results must come from a connected inventory provider. Do not invent properties.

## Attractions branch
Only when Attractions was selected:

1. Vacation style: nature, city, beach, shopping, nightlife, extreme, mixed
2. Family/accessibility constraints already known from shared profile are reused
3. Results come from Ariella attraction DB, ranked by profile fit

## Itinerary branch
Only when Itinerary was selected:

1. Vacation styles (reused if Attractions also selected)
2. Pace: relaxed / medium / packed
3. Max daily drive / transfer tolerance when relevant
4. Build itinerary only from destination/date/traveller constraints and actual attraction data

## Rental-car branch
Only when Rental car was selected:

1. Pickup location
2. Drop-off location
3. Pickup/drop-off times (default to travel dates only if user confirms)
4. Main driver age
5. Vehicle class: mini / economy / compact / family / SUV / 7-seat / 9-seat / luxury / any
6. Passenger capacity + large bags
7. Automatic/manual/any
8. Budget per day / total / unlimited
9. Must-have features: child seat, booster, additional driver, full cover, unlimited mileage, 4x4, EV/hybrid, large boot
10. Fuel policy / one-way if important

Live results must come from a connected rental inventory provider. Do not invent vehicles or prices.

## Parallel behavior
Once the required fields for one selected service are complete, that service may start independently while Ariella continues collecting missing fields for the remaining selected services. Example: a real flight scan can run while Ariella asks lodging preferences.

## Persistence
The target architecture stores user profile, conversations and separate trip records in DB. A future trip may reuse history to ask smarter questions, but Ariella must not assume the new trip has the same travel party or preferences.
