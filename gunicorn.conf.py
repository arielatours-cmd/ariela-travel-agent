"""Gunicorn configuration.

Historical source-rewrite hooks were removed because the corrections are now
part of the repository. Re-running them after every worker fork can reject a
valid newer code shape and prevent the service from booting.
"""
