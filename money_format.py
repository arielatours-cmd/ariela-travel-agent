"""The one place an ILS amount is formatted for the English site.

Business owner (23.10): the currency comes after the amount - "1,500 NIS".
The Hebrew site keeps its own ₪ formatting. Used by the Jinja `nis` filter
(public_site.py), the scanner's English booking-choice reasons and the
English chat messages, so the order never drifts between places.
"""


def format_nis(value) -> str:
    try:
        return f"{int(round(float(value))):,} NIS"
    except (TypeError, ValueError):
        return f"{value} NIS"
