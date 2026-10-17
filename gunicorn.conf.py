"""Gunicorn configuration.

Historical source-rewrite hooks were removed because the corrections are now
part of the repository. Re-running them after every worker fork can reject a
valid newer code shape and prevent the service from booting.

Per Shlomo/Eran (17.10.2026, stage-2 run-5+ 502 investigation): the live
/health endpoint (PR #69) reported gunicorn_timeout=30, gunicorn_threads=1 -
gunicorn's own bare defaults - proving the deployed Start Command does NOT
actually pass --timeout/--threads/--workers, whatever render.yaml's
startCommand says. Rather than wait on tracking down and fixing the real
Start Command (a separate, Render-dashboard-level change outside this
repo's control), these are set directly here instead: this file is already
confirmed loaded regardless of the Start Command (post_worker_init below
only ever ran because gunicorn is loading it), so they take effect no
matter what flags the Start Command does or doesn't pass.

threads is capped at 4, not higher - raising it to 12 on 2026-10-12 made
the live instance OOM-crash-loop within ~10 minutes (each thread holds a
full request's memory - conversation history, cached system prompt, an
in-flight Anthropic response - at once), confirmed in Render's own
metrics/logs ("Worker exited"/"out of memory"/"SIGKILL"). 4 is the
known-stable value; raising it again needs a plan upgrade with more memory
first. workers stays at 1 because the in-process scheduler (daily/scan
jobs) must run only once.
"""
import os

workers = 1
threads = 4
timeout = 120


def post_worker_init(worker):
    """Per Shaked's PR #69 review (stage-2 run-4 502 investigation): /health
    needs to report gunicorn's ACTUAL resolved --timeout/--threads, not a
    value re-derived from a command line - a short "-t"/"-w" flag,
    GUNICORN_CMD_ARGS, or a setting in this very file never appears as a
    literal "--timeout"/"--threads" substring anywhere, so a cmdline scan
    silently misreports those as whatever hardcoded default the scanning
    code happened to assume.

    gunicorn itself has already resolved the real value from WHATEVER
    source actually set it by the time this hook runs - worker.cfg is
    that one authoritative answer, regardless of CLI flag vs. env var vs.
    config file. Stashed into this exact worker process's own environment
    (not a file, not a shared service - os.environ in THIS process only),
    where app.py's /health (served by this same worker, since gunicorn
    runs the WSGI app directly in the forked worker process) reads it
    straight back with no further guessing."""
    os.environ["ARIELLA_GUNICORN_TIMEOUT"] = str(worker.cfg.timeout)
    os.environ["ARIELLA_GUNICORN_THREADS"] = str(worker.cfg.threads)
