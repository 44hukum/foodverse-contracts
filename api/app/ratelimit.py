"""In-memory fixed-window rate limiter.

Sufficient for a single-process v1 deployment; a shared store would be needed
for several API replicas. Keys are opaque strings (an IP, a token hash).
"""

from __future__ import annotations

import math
import time
from collections import deque


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str, limit: int, window_seconds: float = 60.0) -> int | None:
        """Record a hit. Return None when allowed, else seconds until a retry may succeed."""
        now = time.monotonic()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return max(1, math.ceil(hits[0] + window_seconds - now))
        hits.append(now)
        return None

    def reset(self) -> None:
        self._hits.clear()
