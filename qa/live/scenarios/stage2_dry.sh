# Stage 2 dry run = qa/live/scenarios/stage2_cases.sh against a local copy of a ref.
# Run: DRY_RUN_COST_APPROVED=1 ARIELLA_MODEL=claude-sonnet-5 qa/dry_run_local.sh <ref> qa/live/scenarios/stage2_dry.sh [OUT]
P=s2d; PH=05000997
source "$(dirname "${BASH_SOURCE[0]}")/stage2_cases.sh"
