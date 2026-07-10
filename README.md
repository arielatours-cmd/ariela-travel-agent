# Ariella Tours v2

This version connects Ariella to SerpApi Google Flights.

## Required Render variable

SERPAPI_API_KEY

## Test endpoints

/health

/search?departure=TLV&arrival=ATH&outbound=2026-09-10&return_date=2026-09-15

/scan

The configured scan checks five destinations and therefore uses five SerpApi searches.

Important: SerpApi's `bags` parameter covers carry-on bags, not checked baggage.
