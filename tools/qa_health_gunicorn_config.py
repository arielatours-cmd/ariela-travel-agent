"""QA for the /health gunicorn_timeout/gunicorn_threads fields, approved
by Shlomo (17.10.2026) following the stage-2 run-4 502 investigation: a
502 during Paris itinerary building came back after exactly gunicorn's
documented DEFAULT timeout (30s), not the 120s render.yaml configures
for this exact scenario (a day-by-day route reply running close to its
max output length) - strong evidence that file isn't even the one
actually applied to the live service (its own service name,
"ariela-travel-agent-v6", doesn't match the live service,
"ariela-travel-agent"). Exposing the real, in-effect values at
/health directly answers that, without depending on manually checking
Render's dashboard.

_detect_gunicorn_config() reads the gunicorn MASTER process's own
cmdline via /proc/*/cmdline - readable because a gunicorn worker is
forked from the master, not exec'd - and parses --timeout/--threads with
a regex, falling back to gunicorn's own documented defaults (30/1) when
a gunicorn process is found but neither flag is explicit. Cached after
the first successful detection (the running command line never changes
without a restart, so a bare integer answer is enough - no real-time
monitoring need justifies re-scanning all of /proc on every single
/health call).

Approved under three explicit conditions (Shlomo): (1) any read failure
returns null, never fails /health itself; (2) answers are cached in
memory, no significant added latency per request; (3) only the two
parsed integers are ever exposed - never the raw command line, a file
path, or an environment variable.

Run: python3 tools/qa_health_gunicorn_config.py
"""
import os
import sys
from unittest.mock import patch, mock_open

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import app as app_module

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


def _detect_with_fake_proc(listdir_result, cmdline_bytes, listdir_side_effect=None):
    app_module._GUNICORN_CONFIG_CACHE = None
    with patch.object(os, "listdir", return_value=listdir_result, side_effect=listdir_side_effect):
        with patch("builtins.open", mock_open(read_data=cmdline_bytes)):
            return app_module._detect_gunicorn_config()


# --- explicit --timeout/--threads are parsed correctly ---
check("explicit '--timeout 120 --threads 4' (render.yaml's own intended "
      "values) is parsed correctly",
      _detect_with_fake_proc(
          ["123"],
          b"gunicorn\x00--workers\x001\x00--threads\x004\x00--timeout\x00120\x00app:app\x00",
      ) == (120, 4))

check("Shaked/Shlomo's live finding: a gunicorn process found with NO "
      "explicit --timeout/--threads reports gunicorn's own documented "
      "defaults (30s, 1 thread) - exactly what explains a 502 at almost "
      "precisely 30.1 seconds when the live service's actual start "
      "command turns out not to carry render.yaml's intended flags",
      _detect_with_fake_proc(["123"], b"gunicorn\x00app:app\x00") == (30, 1))

check("--timeout alone (no --threads) reports the explicit timeout and "
      "gunicorn's own default thread count",
      _detect_with_fake_proc(
          ["123"], b"gunicorn\x00--timeout\x0060\x00app:app\x00",
      ) == (60, 1))

check("no gunicorn process found at all (e.g. local dev under the Flask "
      "dev server) reports (None, None), never a guessed value",
      _detect_with_fake_proc(["123"], b"python3\x00app.py\x00") == (None, None))

check("a /proc read failure (OSError, e.g. permission denied or /proc "
      "unavailable) never propagates - reports (None, None), condition "
      "(1) of Shlomo's approval",
      _detect_with_fake_proc([], b"", listdir_side_effect=OSError("no /proc")) == (None, None))

# --- caching: the second call must never re-scan /proc, condition (2) ---
app_module._GUNICORN_CONFIG_CACHE = None
with patch.object(os, "listdir", return_value=["123"]):
    with patch("builtins.open", mock_open(read_data=b"gunicorn\x00--timeout\x00120\x00--threads\x004\x00app:app\x00")):
        first = app_module._detect_gunicorn_config()
with patch.object(os, "listdir", side_effect=AssertionError("must not re-scan /proc - cached answer required")):
    second = app_module._detect_gunicorn_config()
check("Shlomo's condition (2): the second call reuses the cached answer "
      "and never re-scans /proc",
      first == second == (120, 4))

# --- /health itself: fields present, never crashes even when detection fails ---
app_module._GUNICORN_CONFIG_CACHE = None
client = app_module.app.test_client()
with patch.object(os, "listdir", return_value=["123"]):
    with patch("builtins.open", mock_open(read_data=b"gunicorn\x00--timeout\x00120\x00--threads\x004\x00app:app\x00")):
        r = client.get("/health")
data = r.get_json()
check("/health returns 200 and includes the two new integer fields",
      r.status_code == 200 and data.get("gunicorn_timeout") == 120 and data.get("gunicorn_threads") == 4)
check("Shlomo's condition (3): /health never exposes the raw command "
      "line, a file path, or an environment variable - only the two "
      "parsed integers",
      "cmdline" not in data and "proc" not in str(data).lower()
      and all(not isinstance(v, str) or "/" not in v for k, v in data.items()
              if k in ("gunicorn_timeout", "gunicorn_threads")))

app_module._GUNICORN_CONFIG_CACHE = None
with patch.object(os, "listdir", side_effect=OSError("no /proc")):
    r2 = client.get("/health")
check("Shlomo's condition (1): /health still returns 200 with null "
      "fields even when gunicorn detection fails entirely",
      r2.status_code == 200
      and r2.get_json().get("gunicorn_timeout") is None
      and r2.get_json().get("gunicorn_threads") is None)

app_module._GUNICORN_CONFIG_CACHE = None  # leave global state clean for any other test run

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL HEALTH-GUNICORN-CONFIG TESTS PASSED")
