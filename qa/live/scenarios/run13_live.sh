# Live stage-1 run 13 (flight only) = qa/live/scenarios/run13_cases.sh on the live site.
# Usage: bash qa/live/scenarios/run13_live.sh EXPECTED_COMMIT OUT_DIR   (~55 turns)
set -u
SC_DIR=$(cd "$(dirname "$0")" && pwd); L=$(cd "$SC_DIR/.." && pwd); OUT=${2:?out dir}; mkdir -p "$OUT"
export ARIELA_QA_OUT="$OUT"; cd "$OUT"
C=$(curl -s -m 30 https://ariela-travel-agent.onrender.com/health | grep -o '"commit":"[^"]*"'); echo "$C"
case "$C" in *"$1"*) ;; *) echo "WRONG COMMIT, abort"; exit 1;; esac
reg()   { python3 "$L/register.py" "$@" 2>&1 | head -1; }
drive() { timeout 1700 python3 "$L/autodrive.py" "$@"; }
say()   { local sc=$1; shift; for m in "$@"; do echo "[$sc] U: $m @$(date -u +%H:%M:%S)"; timeout 300 python3 "$L/chat_multi.py" "$sc" "$m" 2>&1 | sed -n '/ARIELA:/,$p' | tail -n +2; done; }
P=r13; PH=05000999
source "$SC_DIR/run13_cases.sh"
echo ALLDONE
