# Ariella QA Master — v9.7.108

## Regular vacation

| # | Test | Status before 108 | 108 action | Live status |
|---|---|---:|---|---:|
| 0.1 | Regular route opens | ✅ | Regression only | ⬜ RETEST |
| 1.1 | One destination | ✅ | Regression only | ⬜ RETEST |
| 1.2 | Several destinations display all choices | ✅ | Regression only | ⬜ RETEST |
| 1.3 | Several destinations finds one DB match | ✅ | Regression only | ⬜ RETEST |
| 1.4A | Several destinations, no DB match detected | ✅ | Regression only | ⬜ RETEST |
| 1.4B | Same dates -> another destination | ✅ | New closest-DB fallback added after no full match | ⬜ RETEST |
| 1.4C | Same destinations -> other dates | ❌ | Fix: any IATA + DB->scan + state flow | ⬜ RETEST |
| 1.5 | Ariella chooses from 48h DB | ✅ | Regression only | ⬜ RETEST |
| 2.1 | Exact dates only | ✅ | Regression only | ⬜ RETEST |
| 2.2 | One destination -> other dates | ✅ | Original dates now restored after scan | ⬜ RETEST |
| 2.3 | Same dates -> another destination | ✅ | Regression + closest fallback | ⬜ RETEST |
| 2.4 | Outbound / return in different months | ✅ | Regression only | ⬜ RETEST |
| 2.5 | Ariella chooses when | ✅ | Regression only | ⬜ RETEST |
| 3A | Family composition saved/displayed | ✅ | Regression only | ⬜ RETEST |
| 3B | Enough live seats for full party | ⬜ | Future supplier/API validation | ⬜ FUTURE |
| 4.1 | Direct flight rejects connection | ✅ | Regression only | ⬜ RETEST |
| 4.2 | Baggage with trolley passes | ✅ | Regression only | ⬜ RETEST |
| 4.3 | No trolley rejected when baggage selected | ⬜ | QA fixture still required | ⬜ |
| 4.4 | Convenient hours | 🗑️ | Removed | — |
| 4.5 | Maximize trip | 🔧 | New preference: arrival <=10, return dep >=20 | ⬜ TEST |
| 4.6 | Best price Q04 | 🗑️ | Removed for selected destination | — |
| 4.7 | Best balance Q04 | 🗑️ | Removed for selected destination | — |
| 5.1 | Per-person budget +10% | ✅ | Regression only | ⬜ RETEST |
| 5.2 | Over-budget alternatives displayed | ✅ | Regression only | ⬜ RETEST |
| 5.3 | No arithmetic vs budget shown | ✅ | Regression only | ⬜ RETEST |
| 5.4 | Continue searching within budget opens paid plans | ✅ | Regression only | ⬜ RETEST |
| 5.5 | Unlimited budget | ✅ | Regression only | ⬜ RETEST |
| 6 | Special needs | ⬜ | Not changed | ⬜ |
| 7 | Multiple selected conditions together | 🟡 | Final regular-route test after individual filters | ⬜ |
| 8 | Fallback hierarchy | 🔧 | Updated in 108 | ⬜ TEST |
| 9 | Zurich/Krakow/Larnaca images | ❌ | Image mappings + fallback | ⬜ RETEST |

## Business flight

| # | Test | Expected | Status |
|---|---|---|---:|
| B0 | Business card | Opens business questionnaire immediately | ⬜ |
| B1 | One destination | Saves destination | ⬜ |
| B1b | Multiple destinations / airports | Multiple selections saved | ⬜ |
| B2 | Fixed dates | Searches fixed dates | ⬜ |
| B2a | Flex ±1/2/3 | Time question hides; search expands only selected number of days | ⬜ |
| B2b | No flex + arrival deadline | Arrival condition is scored; previous-day departure may be considered | ⬜ |
| B2c | Return-after time | Condition is scored, not hard filtered | ⬜ |
| B3 | Traveler count | Saved/displayed correctly | ⬜ |
| B4 | Cabin class | Selected class becomes a scoring condition when supplier data exists | ⬜ |
| B5 | Each selected condition | +1 when met, 0 when not met; no offer hidden | ⬜ |
| B5b | Deal reasons | Show only conditions the offer meets | ⬜ |
| B5c | Sorting | Highest points first; duration then price break ties | ⬜ |
| B6 | Budget | Budget is another scoring condition, not hard filter | ⬜ |

## Ski
Testing remains deferred until the regular vacation route is green.
