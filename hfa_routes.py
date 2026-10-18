"""Destinations served from Haifa (HFA) by Air Haifa - task 011a.

data/hfa_routes.json is the source of truth (refreshed by hand). Ariella uses
it to check a "flight from Haifa to X" request before searching:
  served      - a confirmed route; continue as usual
  maybe       - a route still marked to_verify (often seasonal); continue,
                but tell the customer availability will be checked
  not_served  - no direct route from Haifa; offer Ben Gurion instead and
                never search from HFA
It is a match check only - never a promise that a flight exists.
"""
from __future__ import annotations

import json
import os
import re

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "hfa_routes.json")
_HEBREW_PREFIXES = ("ל", "ב", "מ", "ה", "ו")


def load_routes() -> list[dict]:
    try:
        with open(_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    routes = data.get("routes") if isinstance(data, dict) else None
    return [r for r in (routes or []) if isinstance(r, dict) and r.get("iata")]


def _tokens(text: str) -> set[str]:
    out = set()
    for token in re.findall(r"[\w'\"״׳-]+", text.lower()):
        out.add(token)
        if token[:1] in _HEBREW_PREFIXES and len(token) > 3:
            out.add(token[1:])
    return out


def _names(route: dict) -> set[str]:
    names = {str(route.get("iata") or "").lower(), str(route.get("city_en") or "").lower()}
    names.add(re.sub(r"\s*\(.*\)\s*", "", str(route.get("city_he") or "")).strip().lower())
    names.update(str(s).strip().lower() for s in (route.get("synonyms_he") or []))
    return {n for n in names if n}


def matching_routes(dest) -> list[dict]:
    """Routes whose IATA code, city or synonym (incl. country, e.g. כרתים,
    קפריסין, יוון) appears in dest - a string or a list of strings/codes."""
    values = dest if isinstance(dest, (list, tuple, set)) else [dest]
    found: list[dict] = []
    for value in values:
        text = str(value or "").strip().lower()
        if not text:
            continue
        tokens = _tokens(text)
        for route in load_routes():
            if route in found:
                continue
            for name in _names(route):
                if (" " in name and name in text) or name in tokens or name == text:
                    found.append(route)
                    break
    return found


def hfa_route_check(dest) -> str:
    """served / maybe / not_served for a destination requested from Haifa.
    dest may be a code, a Hebrew/English place name, or a list of them;
    the best status among the matching routes wins."""
    statuses = {str(r.get("status") or "") for r in matching_routes(dest)}
    if "confirmed" in statuses:
        return "served"
    if "to_verify" in statuses:
        return "maybe"
    return "not_served"
