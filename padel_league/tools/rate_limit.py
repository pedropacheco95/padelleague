"""A small in-process sliding-window rate limiter.

Counters live in this process only: with several gunicorn workers each worker
counts on its own, so a limit of N allows up to N x workers. That is fine for
what it guards (password-code requests), where the point is to stop scripted
floods, not to be exact.
"""

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self):
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, key, limit, window_seconds):
        """Record one hit for `key` and say whether it is within `limit` per window."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def reset(self):
        with self._lock:
            self._hits.clear()


# Password-code requests (v1 forgot_password / generate_new_code).
code_requests = RateLimiter()
