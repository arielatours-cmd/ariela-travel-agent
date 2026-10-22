#!/usr/bin/env bash
# Local "dry run" of live-style QA conversations against a local copy of the site.
#
# Usage:  qa/dry_run_local.sh GIT_REF SCENARIO_FILE [OUT_DIR]
#   GIT_REF        commit/branch/PR ref to test (e.g. origin/main, pr/141 after
#                  `git fetch origin refs/pull/141/head:refs/remotes/pr/141`)
#   SCENARIO_FILE  bash file sourced after the server is up; uses the helpers
#                  below: reg SC PHONE GENDER / drive SC LABEL FIRST JSON / say SC MSG...
#                  (example: qa/live/scenarios/example.sh)
#
# Safety (fixed, not configurable here):
#   - temp DB, SCHEDULER_ENABLED=false, SCANNER_ENABLED=false
#   - no SERPAPI / WhatsApp / CJ keys in the server's environment
#   - chat_multi.py additionally aborts every scan/search/payment request in the browser
#
# The model is called ONLY when DRY_RUN_COST_APPROVED=1 (the business owner's
# approval of the token cost). Then ANTHROPIC_API_KEY is a placeholder
# ("via-proxy") that the environment's network secret replaces with the real
# key - the real key is never read, written or printed by this script.
# Without approval the server runs with no key (plumbing smoke test only:
# registration, login, chat round-trip, logging).
#
# ARIELLA_MODEL must match the production value (Render) - pass it in the
# environment; the script refuses to call the model without it.
set -euo pipefail

REF="${1:?usage: qa/dry_run_local.sh GIT_REF SCENARIO_FILE [OUT_DIR]}"
SCEN="$(realpath "${2:?usage: qa/dry_run_local.sh GIT_REF SCENARIO_FILE [OUT_DIR]}")"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT="$(realpath -m "${3:-${TMPDIR:-/tmp}/ariela-dryrun-$STAMP}")"
PORT="${DRY_RUN_PORT:-8765}"
LIVE_DIR="$REPO/qa/live"
mkdir -p "$OUT"

WT="$(mktemp -d "${TMPDIR:-/tmp}/ariela-dryrun-wt-XXXXXX")"
SERVER_PID=""
cleanup() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true
  git -C "$REPO" worktree remove --force "$WT" 2>/dev/null || true
}
trap cleanup EXIT

git -C "$REPO" worktree add -q --detach "$WT" "$REF"
SHA="$(git -C "$WT" rev-parse --short HEAD)"
echo "dry run: ref=$REF sha=$SHA out=$OUT"

SERVER_ENV=(
  "PATH=$PATH" "HOME=$HOME"
  "DB_PATH=$OUT/dryrun.db" "SCHEDULER_ENABLED=false" "SCANNER_ENABLED=false"
  "ADMIN_TOKEN=dryrun-$STAMP" "FLASK_SECRET_KEY=dryrun-$STAMP" "PUBLIC_BASE_URL=http://127.0.0.1:$PORT"
)
# The environment's proxy settings, so the placeholder key reaches the proxy.
for v in HTTPS_PROXY HTTP_PROXY NO_PROXY https_proxy http_proxy no_proxy SSL_CERT_FILE REQUESTS_CA_BUNDLE; do
  [ -n "${!v:-}" ] && SERVER_ENV+=("$v=${!v}")
done
if [ "${DRY_RUN_COST_APPROVED:-0}" = "1" ]; then
  : "${ARIELLA_MODEL:?set ARIELLA_MODEL to the production value before calling the model}"
  SERVER_ENV+=("ANTHROPIC_API_KEY=via-proxy" "ARIELLA_MODEL=$ARIELLA_MODEL")
  echo "model: ON ($ARIELLA_MODEL, key via proxy)"
else
  echo "model: OFF (no DRY_RUN_COST_APPROVED=1) - plumbing smoke test only"
fi

( cd "$WT" && env -i "${SERVER_ENV[@]}" gunicorn --workers 1 --threads 4 --timeout 120 \
    --bind "127.0.0.1:$PORT" app:app ) > "$OUT/server.log" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 60); do
  curl -sf "http://127.0.0.1:$PORT/health" > "$OUT/health.json" 2>/dev/null && break
  sleep 1
done
curl -sf "http://127.0.0.1:$PORT/health" > /dev/null || { echo "server did not start - see $OUT/server.log"; exit 1; }

export ARIELA_BASE="http://127.0.0.1:$PORT" ARIELA_QA_OUT="$OUT"
reg()   { python3 "$LIVE_DIR/register.py" "$@" 2>&1 | head -2; }
drive() { timeout 1700 python3 "$LIVE_DIR/autodrive.py" "$@"; }
say()   { local sc=$1; shift; for m in "$@"; do echo "[$sc] U: $m @$(date -u +%H:%M:%S)";
          timeout 300 python3 "$LIVE_DIR/chat_multi.py" "$sc" "$m" 2>&1 | sed -n '/ARIELA:/,$p' | tail -n +2; done; }

cd "$OUT"
# shellcheck source=/dev/null
source "$SCEN"
echo "done: sha=$SHA, transcripts and state in $OUT (chat_resp_*.jsonl = full trip_update per turn)"
