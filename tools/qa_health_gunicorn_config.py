"""QA for the /health gunicorn_timeout/gunicorn_threads fields, approved
by Shlomo (17.10.2026) following the stage-2 run-4 502 investigation: a
502 during Paris itinerary building came back after exactly gunicorn's
documented DEFAULT timeout (30s), not the 120s render.yaml configures
for this exact scenario (a day-by-day route reply running close to its
max output length) - strong evidence that file isn't even the one
actually applied to the live service (its own service name,
"ariela-travel-agent-v6", doesn't match the live service,
"ariela-travel-agent").

FIRST version (PR #69, d106aba) scanned /proc/*/cmdline for the gunicorn
master process. Shaked rejected it after actually running the exact
command render.yaml specifies and testing against it:
(1) gunicorn is itself a Python script, so a process's cmdline[0] is the
    INTERPRETER path ("/usr/bin/python3"), not "gunicorn" - the old
    check ("gunicorn" not in cmdline[0]) always skipped the real master
    process. The first version's own test mocked cmdline data starting
    directly with "gunicorn" (unrealistic), which hid exactly this bug -
    this file now tests against a REAL gunicorn process instead, not a
    mocked /proc.
(2) even with (1) fixed, a value set via GUNICORN_CMD_ARGS, a short
    "-t"/"-w" flag, or a gunicorn.conf.py setting never appears as a
    literal "--timeout"/"--threads" substring in the command line at
    all - the function would have silently reported the code's own
    hardcoded fallback (30/1) as if it were the real value, exactly
    backwards on the question the field exists to answer.

FIXED (this version): gunicorn.conf.py's post_worker_init(worker) hook
runs in the worker process right after gunicorn has already resolved
the real timeout/threads from WHATEVER source actually set them (CLI
flag, env var, or config file) - worker.cfg.timeout/worker.cfg.threads
is gunicorn's own authoritative answer. The hook stashes them into that
same worker process's own environment (ARIELLA_GUNICORN_TIMEOUT/
ARIELLA_GUNICORN_THREADS), where /health (served by that same process)
reads them straight back - no re-derivation, no guessing. Requires
gunicorn to actually be invoked with --config gunicorn.conf.py (or -c)
for the hook to run; confirmed via git history that it already is - a
previous post_fork hook in this same file (removed in 3cde202) was
demonstrably executing in production ("re-running them after every
worker fork can reject a valid newer code shape and prevent the service
from booting").

Run: python3 tools/qa_health_gunicorn_config.py
"""
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import app as app_module

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# === Unit-level: the env vars the hook is expected to set ===

for var in ("ARIELLA_GUNICORN_TIMEOUT", "ARIELLA_GUNICORN_THREADS"):
    os.environ.pop(var, None)

check("no hook has run yet (e.g. the Flask dev server, or gunicorn "
      "invoked without --config gunicorn.conf.py) -> (None, None), "
      "never a guessed value",
      app_module._detect_gunicorn_config() == (None, None))

os.environ["ARIELLA_GUNICORN_TIMEOUT"] = "120"
os.environ["ARIELLA_GUNICORN_THREADS"] = "4"
check("the hook's exact env var names are read back correctly",
      app_module._detect_gunicorn_config() == (120, 4))

os.environ["ARIELLA_GUNICORN_TIMEOUT"] = "not-a-number"
check("a corrupted/unexpected env var value never raises - reports "
      "None for that field instead",
      app_module._detect_gunicorn_config() == (None, 4))

for var in ("ARIELLA_GUNICORN_TIMEOUT", "ARIELLA_GUNICORN_THREADS"):
    os.environ.pop(var, None)

# === /health itself: fields present, never crashes ===

client = app_module.app.test_client()
r = client.get("/health")
check("/health returns 200 with null fields when the hook never ran "
      "(Shlomo's condition (1): a missing value must never fail /health)",
      r.status_code == 200
      and r.get_json().get("gunicorn_timeout") is None
      and r.get_json().get("gunicorn_threads") is None)

os.environ["ARIELLA_GUNICORN_TIMEOUT"] = "120"
os.environ["ARIELLA_GUNICORN_THREADS"] = "4"
r2 = client.get("/health")
data2 = r2.get_json()
check("/health returns 200 and includes the two integer fields once "
      "the hook has run",
      r2.status_code == 200 and data2.get("gunicorn_timeout") == 120
      and data2.get("gunicorn_threads") == 4)
check("Shlomo's condition (3): /health never exposes a raw command "
      "line, a file path, or any other environment variable - only the "
      "two parsed integers",
      "cmdline" not in data2 and "ARIELLA_GUNICORN_TIMEOUT" not in str(data2)
      and all(not isinstance(v, str) or "/" not in v for k, v in data2.items()
              if k in ("gunicorn_timeout", "gunicorn_threads")))

for var in ("ARIELLA_GUNICORN_TIMEOUT", "ARIELLA_GUNICORN_THREADS"):
    os.environ.pop(var, None)


# === The real repro: Shaked's exact live gunicorn run ===

def _gunicorn_available():
    try:
        subprocess.run(
            [sys.executable, "-c", "import gunicorn"],
            check=True, capture_output=True, timeout=10,
        )
        return True
    except Exception:
        return False


def _run_real_gunicorn_and_fetch_health(extra_args, port):
    """Launches a REAL gunicorn subprocess (not a mocked /proc) against
    this repo's actual app.py and gunicorn.conf.py, and returns /health's
    raw response body once the server is up."""
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    for var in ("ARIELLA_GUNICORN_TIMEOUT", "ARIELLA_GUNICORN_THREADS"):
        env.pop(var, None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "gunicorn", *extra_args, "-b", f"127.0.0.1:{port}", "app:app"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        body = None
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
                    body = resp.read()
                break
            except (urllib.error.URLError, ConnectionRefusedError):
                time.sleep(0.5)
        return body
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


if not _gunicorn_available():
    print("[SKIP] gunicorn not installed in this environment - the "
          "real-process repros below cannot run here, but are the "
          "authoritative check: run them manually with gunicorn "
          "installed before trusting this fix")
else:
    body = _run_real_gunicorn_and_fetch_health(
        ["--workers", "1", "--threads", "4", "--timeout", "120"], 8766,
    )
    check("Shaked's exact live repro: 'gunicorn --workers 1 --threads "
          "4 --timeout 120 -b 127.0.0.1:8766 app:app' - a REAL gunicorn "
          "process, not a mocked /proc - reports the real values via "
          "/health, not null/null",
          body is not None and b'"gunicorn_timeout":120' in body
          and b'"gunicorn_threads":4' in body)

    body2 = _run_real_gunicorn_and_fetch_health([], 8767)
    check("Shlomo's exact concern: the BARE Start Command 'gunicorn "
          "app:app' (no --workers/--threads/--timeout, no -c/--config "
          "flag at all) still loads gunicorn.conf.py and runs the hook - "
          "gunicorn auto-discovers gunicorn.conf.py in the working "
          "directory with no flag needed. Reports gunicorn's own real "
          "resolved defaults (timeout=30, threads=1), never null/null",
          body2 is not None and b'"gunicorn_timeout":30' in body2
          and b'"gunicorn_threads":1' in body2)


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL HEALTH-GUNICORN-CONFIG TESTS PASSED")
