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
    """Admin dashboard summary: totals, and breakdowns by day/source/member/conversation."""
    with connection() as conn:
        test_clause = "" if include_test else "AND is_test=0"
        since = f"datetime('now','-{int(days)} days')"
        rows = conn.execute(
            f"SELECT * FROM ai_usage WHERE created_at >= {since} {test_clause} ORDER BY created_at DESC"
        ).fetchall()
        rows = [_row_to_dict(r) for r in rows]

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
        }


def usage_rows(days: int = 30, include_test: bool = False) -> list:
    """Row-by-row export (CSV) - every ai_usage column plus estimated cost."""
    with connection() as conn:
        test_clause = "" if include_test else "AND is_test=0"
        since = f"datetime('now','-{int(days)} days')"
        rows = conn.execute(
            f"SELECT * FROM ai_usage WHERE created_at >= {since} {test_clause} ORDER BY created_at DESC"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def usage_for_conversation(conversation_id: int) -> list:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_usage WHERE conversation_id=? ORDER BY created_at ASC", (conversation_id,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def record_ai_usage(source: str, model: str, usage=None, error=None):
    """Writes one ai_usage row. Never raises - a failure here (locked DB,
    bad data) must never be allowed to fail the chat turn that triggered it."""
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
                    is_test, error, channel
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    utc_now_iso(), str(source or "other"), ctx.get("member_id"), ctx.get("trip_id"),
                    ctx.get("conversation_id"), str(model or ""), input_tokens, output_tokens,
                    cache_read, cache_write, 1 if ctx.get("is_test") else 0,
                    str(error) if error else None, ctx.get("channel"),
                ),
            )
    except Exception:
        log.exception("failed to record AI usage (source=%s, model=%s)", source, model)
