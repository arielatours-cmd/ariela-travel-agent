# Dry run 5 = the run-13 scenario set (qa/live/scenarios/run13_cases.sh) against the integration branch.
# Run: DRY_RUN_COST_APPROVED=1 ARIELLA_MODEL=claude-sonnet-5 qa/dry_run_local.sh <ref> qa/live/scenarios/dryrun5_typos.sh
P=dr5; PH=05000998
source "$(dirname "${BASH_SOURCE[0]}")/run13_cases.sh"
