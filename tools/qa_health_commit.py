"""QA for task 008a - /health gains "commit" (first 7 chars of
RENDER_GIT_COMMIT, or null) and "deployed_at" (process start time, UTC),
so ops (Eran) can tell from /health alone whether the latest commit on main
actually made it to the live deploy, instead of relying on the
hand-edited APP_VERSION constant.

_DEPLOYED_COMMIT/_STARTED_AT in app.py are computed once at import time, so
testing RENDER_GIT_COMMIT requires a fresh process per case (importing
app.py twice in one process would just reuse the first import's values).

Run: python3 tools/qa_health_commit.py
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SNIPPET = """
import sys, os
sys.path.insert(0, {root!r})
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
import app as app_module
client = app_module.app.test_client()
r1 = client.get("/health")
r2 = client.get("/health")
import json
print(json.dumps({{"first": r1.get_json(), "second": r2.get_json()}}))
"""


def _run_health_in_fresh_process(render_git_commit: str | None) -> dict:
    env = dict(os.environ)
    if render_git_commit is None:
        env.pop("RENDER_GIT_COMMIT", None)
    else:
        env["RENDER_GIT_COMMIT"] = render_git_commit
    proc = subprocess.run(
        [sys.executable, "-c", _SNIPPET.format(root=ROOT)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"subprocess failed:\n{proc.stdout}\n{proc.stderr}"
    # app.py logs INFO lines to stdout too (apscheduler) - the JSON is the last line.
    last_line = [line for line in proc.stdout.splitlines() if line.strip()][-1]
    return json.loads(last_line)


# --- 1. RENDER_GIT_COMMIT set -> commit is its first 7 characters ---
result = _run_health_in_fresh_process("abcdef1234567890")
assert result["first"]["commit"] == "abcdef1", result["first"]["commit"]
print("PASS: RENDER_GIT_COMMIT=abcdef1234567890 -> commit:'abcdef1'")

# --- 2. RENDER_GIT_COMMIT unset (local dev) -> commit is null ---
result = _run_health_in_fresh_process(None)
assert result["first"]["commit"] is None, result["first"]["commit"]
print("PASS: no RENDER_GIT_COMMIT -> commit:null")

# --- 3. deployed_at is an ISO UTC timestamp, identical across two calls in the same process ---
assert result["first"]["deployed_at"] == result["second"]["deployed_at"], result
assert result["first"]["deployed_at"].endswith("+00:00"), result["first"]["deployed_at"]
print("PASS: deployed_at is ISO UTC and identical across requests in the same process")

# --- 4. Every pre-existing /health field is still present and unchanged in shape ---
expected_keys = {
    "status", "version", "commit", "deployed_at", "serpapi_configured",
    "scheduler_enabled", "database_ok", "database_error", "database_path",
    "database_persistent_path", "minimum_score", "maximum_daily_deals",
    "admin_protected", "whatsapp",
}
assert expected_keys.issubset(result["first"].keys()), set(expected_keys) - result["first"].keys()
print("PASS: all pre-existing /health fields are still present")

print("\nALL HEALTH COMMIT (008a) TESTS PASSED")
