"""Gunicorn configuration.

Historical source-rewrite hooks were removed because the corrections are now
part of the repository. Re-running them after every worker fork can reject a
valid newer code shape and prevent the service from booting.
"""
import os


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
