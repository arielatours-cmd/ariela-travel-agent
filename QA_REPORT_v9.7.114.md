# QA Report — Ariella v9.7.114

## Change
Added seasonal destination fit to open-destination vacation ranking.

The algorithm now combines:
- customer's vacation-style preferences;
- requested month/date when supplied;
- destination seasonality for beach, pleasant-weather, hiking/nature use cases;
- existing deal quality, budget and other ranking signals.

Seasonality is a soft ranking signal, not a hard filter, so Ariella can still show the best available alternatives.

## Important mapping correction
- ATH now carries a beach tag for Greece-oriented open-destination recommendations.
- BKK now carries beach/relax tags for Thailand-oriented recommendations.

## Regression checks
- Python compileall: PASS.
- Jinja templates: PASS.
- March + beach: Bangkok ranks above Athens: PASS.
- July + beach: Athens ranks above Bangkok: PASS.
- Athens beach fit in July ranks above Athens beach fit in March: PASS.
- Existing one-month primary date-window logic retained.
- Existing preference-ranking logic retained; seasonal score is additive.

## Manual Live QA after deploy
1. Ariella chooses destination + beach + March -> Mediterranean summer-beach destinations should be demoted; warm-season destinations should rise.
2. Ariella chooses destination + beach + July -> Mediterranean beach destinations should rise.
3. Ariella chooses destination + nature/hiking + requested month -> verify sensible seasonal ordering.
4. Verify exact/month date requests remain within the existing ±1 month primary alternative rule.
