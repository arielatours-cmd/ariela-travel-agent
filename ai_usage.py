"""Claude API usage/cost logging - task 005a.

Records every `_post_claude` call (tokens + which conversation/member it
belongs to) so actual AI spend can be measured, instead of only estimated
from traffic. Writing a row must never be able to break a chat turn - every
public function here swallows its own exceptions and logs instead of
raising.
"""
import contextvars
import json
import logging
import os
from database import connection, utc_now_iso

log = logging.getLogger(__name__)

_context: contextvars.ContextVar[dict] = contextvars.ContextVar("ai_usage_context", default={})

# Diagnostic-only `source` values recorded via record_diagnostic_event below
# (never a real Claude API call - empty model, zero tokens) - excluded from
# every cost/token total in usage_summary/usage_rows, exactly like the
# pre-existing 'turn_total' source, and read back out via diagnostic_rows.
DIAGNOSTIC_EVENT_SOURCES = (
    "restart_signal", "guided_redirect", "dates_change", "destination_change",
    "customer_scan_worker_error", "trip_type_ski_claim",
)
_NON_USAGE_SOURCES = ("turn_total",) + DIAGNOSTIC_EVENT_SOURCES

# Official Anthropic API pricing (USD per 1M tokens), filled in from the
# published pricing page for the model this project actually runs
# (ARIELLA_MODEL, default claude-sonnet-5) - not guessed. Cache writes use
# the standard ephemeral (5-minute) rate. A model missing from this table
# (and from AI_PRICING_JSON below) simply has no cost estimate - never a
# guessed number.
DEFAULT_PRICING_USD_PER_MTOK = {
    "claude-sonnet-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
}


def _pricing_table() -> dict:
    table = dict(DEFAULT_PRICING_USD_PER_MTOK)
    raw = os.getenv("AI_PRICING_JSON", "").strip()
    if raw:
        try:
            override = json.loads(raw)
            if isinstance(override, dict):
                table.update(override)
        except Exception:
            log.exception("AI_PRICING_JSON is not valid JSON - ignoring it")
    return table


def set_ai_usage_context(member_id=None, trip_id=None, conversation_id=None, is_test=None, channel=None):
    """Called once at the entry point of a chat request, before any
    _post_claude call for that request. Every record_ai_usage call during
    the same request (same thread/async task) picks this up automatically -
    callers deep inside the chat/extraction pipeline never need to thread
    member_id through every function signature just to log usage.

    channel (task 006a): None for an ordinary website chat-clean call;
    'whatsapp' when ariella_chat_clean.chat_clean() is invoked from
    whatsapp_bridge.ariella_turn (see that function's session flag)."""
    _context.set({
        "member_id": member_id, "trip_id": trip_id,
        "conversation_id": conversation_id, "is_test": bool(is_test), "channel": channel,
    })


def clear_ai_usage_context():
    _context.set({})


def estimate_cost_usd(row: dict):
    """row: dict with model, input_tokens, output_tokens,
    cache_read_input_tokens, cache_creation_input_tokens. Returns a float
    USD estimate, or None when the model has no known pricing."""
    pricing = _pricing_table().get(str(row.get("model") or ""))
    if not pricing:
        return None
    try:
        return (
            float(row.get("input_tokens") or 0) * pricing.get("input", 0)
            + float(row.get("output_tokens") or 0) * pricing.get("output", 0)
            + float(row.get("cache_read_input_tokens") or 0) * pricing.get("cache_read", 0)
            + float(row.get("cache_creation_input_tokens") or 0) * pricing.get("cache_write", 0)
        ) / 1_000_000
    except Exception:
        log.exception("failed to estimate AI usage cost")
        return None


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["estimated_cost_usd"] = estimate_cost_usd(d)
    return d


def usage_summary(days: int = 30, include_test: bool = False) -> dict:
    """Admin dashboard summary: totals, and breakdowns by day/source/member/conversation.

    source='turn_total' rows (added for per-turn duration logging - see
    ariella_chat_clean.py's chat_clean() wrapper) are diagnostic-only: an
    empty model and zero tokens, recorded once per chat turn regardless of
    how many real Claude calls happened inside it. Seen live (Yosef, right
    after #57 shipped): mixing them into this same summary made the admin
    page permanently show "unknown pricing" (empty model string matches no
    pricing table entry) and inflated the "calls" count with one extra,
    non-API row per turn. Excluded from every total/breakdown below; their
    own durations are reported separately via turn_durations.

    record_diagnostic_event's own sources (DIAGNOSTIC_EVENT_SOURCES - e.g.
    'restart_signal', 'guided_redirect') are the same shape of row (empty
    model, zero tokens) for the same reason, and are excluded here too -
    read back out via diagnostic_rows() instead."""
    with connection() as conn:
        test_clause = "" if include_test else "AND is_test=0"
        since = f"datetime('now','-{int(days)} days')"
        excluded = ",".join("?" for _ in _NON_USAGE_SOURCES)
        rows = conn.execute(
            f"SELECT * FROM ai_usage WHERE created_at >= {since} {test_clause} "
            f"AND source NOT IN ({excluded}) ORDER BY created_at DESC",
            _NON_USAGE_SOURCES,
        ).fetchall()
        rows = [_row_to_dict(r) for r in rows]
        turn_rows = conn.execute(
            f"SELECT call_duration_ms FROM ai_usage WHERE created_at >= {since} {test_clause} "
            f"AND source = 'turn_total' AND call_duration_ms IS NOT NULL"
        ).fetchall()
        turn_durations_ms = [int(r["call_duration_ms"]) for r in turn_rows]

        total_input = sum(r["input_tokens"] for r in rows)
        total_output = sum(r["output_tokens"] for r in rows)
        total_cache_read = sum(r["cache_read_input_tokens"] for r in rows)
        total_cache_write = sum(r["cache_creation_input_tokens"] for r in rows)
        total_cost = sum(r["estimated_cost_usd"] for r in rows if r["estimated_cost_usd"] is not None)
        has_unknown_pricing = any(r["estimated_cost_usd"] is None for r in rows)

        def group_by(key_fn):
            buckets: dict = {}
            for r in rows:
                k = key_fn(r)
                b = buckets.setdefault(k, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
                b["calls"] += 1
                b["input_tokens"] += r["input_tokens"]
                b["output_tokens"] += r["output_tokens"]
                b["cost_usd"] += r["estimated_cost_usd"] or 0
            return buckets

        by_day = group_by(lambda r: str(r["created_at"])[:10])
        by_source = group_by(lambda r: r["source"])
        by_member = group_by(lambda r: r["member_id"])
        by_conversation = group_by(lambda r: r["conversation_id"])

        top_members = sorted(
            ({"member_id": k, **v} for k, v in by_member.items() if k is not None),
            key=lambda x: x["cost_usd"], reverse=True,
        )[:20]
        top_conversations = sorted(
            ({"conversation_id": k, **v} for k, v in by_conversation.items() if k is not None),
            key=lambda x: x["cost_usd"], reverse=True,
        )[:20]

        cacheable_input = total_input + total_cache_read + total_cache_write
        cache_hit_rate = (total_cache_read / cacheable_input) if cacheable_input else 0.0

        # Reported separately from the API-call totals above - see this
        # function's own docstring for why turn_total rows are excluded
        # from everything else here.
        turn_durations = {
            "count": len(turn_durations_ms),
            "avg_ms": round(sum(turn_durations_ms) / len(turn_durations_ms)) if turn_durations_ms else 0,
            "max_ms": max(turn_durations_ms) if turn_durations_ms else 0,
            "min_ms": min(turn_durations_ms) if turn_durations_ms else 0,
        }

        return {
            "days": days, "include_test": include_test, "calls": len(rows),
            "total_input_tokens": total_input, "total_output_tokens": total_output,
            "total_cache_read_input_tokens": total_cache_read,
            "total_cache_creation_input_tokens": total_cache_write,
            "total_estimated_cost_usd": round(total_cost, 4),
            "has_unknown_pricing": has_unknown_pricing,
            "cache_hit_rate": round(cache_hit_rate, 4),
            "by_day": {k: {**v, "cost_usd": round(v["cost_usd"], 4)} for k, v in sorted(by_day.items())},
            "by_source": {k: {**v, "cost_usd": round(v["cost_usd"], 4)} for k, v in by_source.items()},
            "top_members": [{**m, "cost_usd": round(m["cost_usd"], 4)} for m in top_members],
            "top_conversations": [{**c, "cost_usd": round(c["cost_usd"], 4)} for c in top_conversations],
            "turn_durations": turn_durations,
        }


def usage_rows(days: int = 30, include_test: bool = False) -> list:
    """Row-by-row export (CSV) - every ai_usage column plus estimated cost.

    Excludes source='turn_total' and record_diagnostic_event's own sources
    (same reason as usage_summary's own docstring: diagnostic-only, no
    model/tokens/cost of their own) - see turn_duration_rows()/
    diagnostic_rows() for those, reported separately."""
    with connection() as conn:
        test_clause = "" if include_test else "AND is_test=0"
        since = f"datetime('now','-{int(days)} days')"
        excluded = ",".join("?" for _ in _NON_USAGE_SOURCES)
        rows = conn.execute(
            f"SELECT * FROM ai_usage WHERE created_at >= {since} {test_clause} "
            f"AND source NOT IN ({excluded}) ORDER BY created_at DESC",
            _NON_USAGE_SOURCES,
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def turn_duration_rows(days: int = 30, include_test: bool = False) -> list:
    """Row-by-row export of source='turn_total' rows only - the per-turn
    total-duration diagnostic (ariella_chat_clean.py's chat_clean()
    wrapper), kept separate from usage_rows()'s real API-call rows."""
    with connection() as conn:
        test_clause = "" if include_test else "AND is_test=0"
        since = f"datetime('now','-{int(days)} days')"
        rows = conn.execute(
            f"SELECT * FROM ai_usage WHERE created_at >= {since} {test_clause} "
            f"AND source = 'turn_total' ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def usage_for_conversation(conversation_id: int) -> list:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_usage WHERE conversation_id=? ORDER BY created_at ASC", (conversation_id,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def record_ai_usage(source: str, model: str, usage=None, error=None, thread_id=None, call_started_at=None, call_duration_ms=None, details=None):
    """Writes one ai_usage row. Never raises - a failure here (locked DB,
    bad data) must never be allowed to fail the chat turn that triggered it.

    thread_id/call_started_at/call_duration_ms (2026-10-12, Shaked's
    concurrency investigation): optional - only _post_claude's own calls
    pass them, timing the actual client.messages.create() network call
    specifically. Lets /admin/ai-usage.csv answer directly whether
    different threads' Claude calls genuinely overlap in time.

    details (18.10, Shlomo's follow-up on qa/reports/2026-10-18-stage3-
    run4.md): optional short string for a diagnostic-only row - see
    record_diagnostic_event below, which is what actually calls this with
    it set. Plain _post_claude usage calls never pass it."""
    try:
        ctx = _context.get() or {}
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage is not None else 0
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage is not None else 0
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0) if usage is not None else 0
        cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0) if usage is not None else 0
        with connection() as conn:
            conn.execute(
                """INSERT INTO ai_usage(
                    created_at, source, member_id, trip_id, conversation_id, model,
                    input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens,
                    is_test, error, channel, thread_id, call_started_at, call_duration_ms, details
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    utc_now_iso(), str(source or "other"), ctx.get("member_id"), ctx.get("trip_id"),
                    ctx.get("conversation_id"), str(model or ""), input_tokens, output_tokens,
                    cache_read, cache_write, 1 if ctx.get("is_test") else 0,
                    str(error) if error else None, ctx.get("channel"),
                    thread_id, call_started_at, call_duration_ms, details,
                ),
            )
    except Exception:
        log.exception("failed to record AI usage (source=%s, model=%s)", source, model)



def record_diagnostic_event(event: str, details: dict):
    """Per Shlomo's follow-up (18.10, qa/reports/2026-10-18-stage3-run4.md):
    a plain logging.info call for a live-site diagnostic has no value on
    this infrastructure - no agent has access to Render's own log stream.
    Writes one diagnostic-only ai_usage row instead (source=event, model/
    tokens all empty/zero, details=compact JSON of the given dict - never
    the customer's own message text, by construction of every caller),
    so the business owner can export it via /admin/ai-usage.csv and Shaked
    can analyze it. event must be one of DIAGNOSTIC_EVENT_SOURCES. Never
    raises - same guarantee as record_ai_usage."""
    if event not in DIAGNOSTIC_EVENT_SOURCES:
        log.warning("record_diagnostic_event: unknown event %r - not recorded", event)
        return
    try:
        payload = json.dumps(details, ensure_ascii=False, default=str)
    except Exception:
        log.exception("record_diagnostic_event: details not JSON-serializable for event %r", event)
        return
    record_ai_usage(event, "", usage=None, details=payload)


def diagnostic_rows(event: str, days: int = 30, include_test: bool = False) -> list:
    """Row-by-row export of record_diagnostic_event's own rows for one
    event (source) - kept separate from usage_rows()'s real API-call rows,
    same reasoning as turn_duration_rows()."""
    if event not in DIAGNOSTIC_EVENT_SOURCES:
        return []
    with connection() as conn:
        test_clause = "" if include_test else "AND is_test=0"
        since = f"datetime('now','-{int(days)} days')"
        rows = conn.execute(
            f"SELECT id, created_at, member_id, conversation_id, details FROM ai_usage "
            f"WHERE created_at >= {since} {test_clause} AND source = ? ORDER BY created_at DESC",
            (event,),
        ).fetchall()
        return [dict(r) for r in rows]
