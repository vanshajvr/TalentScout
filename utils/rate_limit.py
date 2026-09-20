from datetime import datetime, timedelta

from fastapi import HTTPException

# In-memory, resets on restart — an acceptable tradeoff here, unlike the candidate
# conversation-state problem flagged elsewhere. A restart briefly clearing counters
# gives an attacker at most a momentary reprieve, not an actual security hole, since
# they'd need to sustain the attack precisely across an unpredictable restart to
# benefit. This is basic abuse prevention on unauthenticated endpoints, not a hard
# security boundary — a real distributed deployment would want this backed by Redis
# or the DB instead.
_request_log: dict[str, list[datetime]] = {}


def check_rate_limit(key: str, max_requests: int, window_minutes: int) -> None:
    """Raises 429 if `key` (e.g. an IP address) has made >= max_requests within the
    last window_minutes."""
    now = datetime.utcnow()
    window_start = now - timedelta(minutes=window_minutes)
    recent = [t for t in _request_log.get(key, []) if t >= window_start]

    if len(recent) >= max_requests:
        _request_log[key] = recent
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    recent.append(now)
    _request_log[key] = recent

    # Lightweight, non-blocking cleanup so this dict doesn't grow unboundedly over a
    # long-running process with many distinct keys — only bother once it's actually
    # grown large, to avoid constant overhead in the common case.
    if len(_request_log) > 1000:
        stale = [k for k, v in _request_log.items() if not any(t >= window_start for t in v)]
        for k in stale:
            del _request_log[k]