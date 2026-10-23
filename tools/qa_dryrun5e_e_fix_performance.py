"""QA for the dry-run 5e E fix's performance regression (Shaked, static
review of ff6ed3b4, 23.10.2026): the message-wide token-window catalog
scan was logically correct but measured 3.2s (14-word message) to 9.5s
(41-word opening message) of pure CPU time whenever the message had a
typo (no exact match anywhere) - every genuine-ambiguity-check scenario,
exactly the case this whole mechanism exists for. On Render's single
worker this also blocked every other customer's request meanwhile.

Root cause: _catalog_near_neighbor_cities built a full O(len*len) DP
Levenshtein table for every one of ~1,400 catalog entries, for every one
of up to ~4 x (message word count) candidate windows, re-deriving and
re-normalizing city_he from the catalog dicts on every single call.

Fixed (three changes, all correctness-neutral - verified by re-running
every existing destination-ambiguity regression suite unchanged):
  1. _levenshtein_distance accepts an optional max_distance and returns
     early (skipping the DP table) when the two strings' length
     difference alone already exceeds it.
  2. _catalog_near_neighbor_entries() pre-extracts and pre-normalizes
     both catalogs' (city_he, code, match_exact_only) once per process,
     instead of re-deriving them from the raw dicts on every call.
  3. _catalog_multiword_first_words() caches which words can plausibly
     start a real multi-word catalog name - _reresolve_ambiguous_fresh_
     destination only generates a 2-4-word window at a message position
     when that position's word could plausibly start one, instead of
     generating one at every position regardless.

Run: python3 tools/qa_dryrun5e_e_fix_performance.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import ariella_chat_clean as chat  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


# Warm the module-level caches once, outside the timed region - exactly
# what happens in the real server process (built once, reused for the
# rest of the process's life).
chat._catalog_near_neighbor_entries()
chat._catalog_multiword_first_words()

PRIOR_STATE = {"destination_airports": []}
UPDATE = {"destination_airports": ["XXX"], "destination": {"places": ["זדאק"], "mode": "specific", "status": "known"}}

# Shaked's own exact measured repro cases (23.10.2026) - a typo
# ("לזדאק") with no exact catalog match anywhere, forcing the near-match
# scan to run against every single word-window - the worst case this
# mechanism ever hits, and the exact shape that measured 3.2s/9.5s
# before this fix.
MSG_14_WORDS = "אני ושתי חברות שלי רוצות לטוס ביחד לזדאק בחודש הבא ביולי"
MSG_41_WORDS = " ".join([
    "אני", "ואשתי", "רוצים", "לטוס", "לזדאק", "בחודש", "הבא", "עם", "שני", "הילדים",
    "שלנו", "ולבדוק", "גם", "אפשרות", "של", "טיסה", "ישירה", "בלי", "קונקשן", "אם",
    "אפשר", "ולדעת", "מה", "המחיר", "המשוער", "לאדם", "וגם", "אם", "יש", "מבצעים",
    "טובים", "באותה", "תקופה", "כי", "אנחנו", "גמישים", "בתאריכים", "ורוצים", "למצוא", "דיל", "טוב",
])
check("sanity: the 41-word message really has 41 words",
      len(MSG_41_WORDS.split()) == 41)


def timed_runs(message, n=5):
    times = []
    for _ in range(n):
        t0 = time.time()
        chat._reresolve_ambiguous_fresh_destination(PRIOR_STATE, dict(UPDATE), None, message)
        times.append(time.time() - t0)
    return times


times_14 = timed_runs(MSG_14_WORDS)
times_41 = timed_runs(MSG_41_WORDS)
print(f"14-word message times: {[round(t, 4) for t in times_14]}")
print(f"41-word message times: {[round(t, 4) for t in times_41]}")

# Generous thresholds (well above the ~0.07s/0.25s actually measured when
# this fix was built) - this guards against a future regression back
# toward multi-second territory, not a tight performance SLA.
check("PERF FIX: a 14-word message with a typo resolves in well under 1s "
      f"(max {max(times_14):.3f}s, was 3.2s before this fix)",
      max(times_14) < 1.0)
check("PERF FIX: a 41-word message with a typo resolves in well under 1s "
      f"(max {max(times_41):.3f}s, was 9.5s before this fix)",
      max(times_41) < 1.0)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5E-E-FIX-PERFORMANCE TESTS PASSED")
