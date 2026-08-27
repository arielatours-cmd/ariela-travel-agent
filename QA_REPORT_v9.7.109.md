# Ariella QA — v9.7.109-ariela-final

## Scope
Final closeout of the pending Ariella-only fixes before returning to the owner for final visual testing. Nova/WhatsApp development is not part of this build.

## Verified fixes
- PASS — Regular vacation questionnaire has separate departure and return month fields.
- PASS — Backend rejects a return month earlier than the departure month.
- PASS — Destination picker enlarged for laptop readability in both specific and several-destination modes.
- PASS — Destination/place name enlarged on found-deal cards.
- PASS — Baggage icons use the gentle gold visual language.
- PASS — Destination-led searches (`specific` / `several`) use a dedicated fit ranking where route quality, usable time and baggage outweigh bargain/rarity signals.
- PASS — Destination-led personal inventory is not discarded solely because its global deal score is below the general discovery threshold.
- PASS — Open discovery still uses the global deal score and the public threshold remains 70.

## Automated QA
- Python compilation: PASS
- Jinja parsing: PASS (24 templates)
- Destination-led ranking behavioral test: PASS
  - high-fit selected-destination test offer: 87.5
  - bargain/low-fit selected-destination test offer: 46.75
  - open search preserved raw global scores: PASS
- Version marker: PASS (`9.7.109-ariela-final`)
- Flask runtime smoke test in this workspace: NOT RUN — the workspace does not have Flask installed and outbound package installation is unavailable. This is an environment limitation, not a code failure.

## Deployment/final owner check
After Render deploy, owner should do a short visual regression on laptop/mobile: regular questionnaire destination field, separate months, a found deal card destination title, and baggage icon appearance. Live SerpAPI flight retrieval cannot be exercised in this offline QA environment without production credentials.
