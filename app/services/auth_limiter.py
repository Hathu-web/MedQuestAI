"""Giới hạn nhỏ trong RAM cho bản local một tiến trình; không dùng IP từ header."""
from collections import OrderedDict, deque
import math
from threading import Lock
import time


class AuthLimiter:
    def __init__(self, max_keys=1024):
        self.windows = OrderedDict()
        self.lock = Lock()
        self.max_keys = max_keys

    def consume(self, key, limit, window_seconds):
        now = time.monotonic()
        with self.lock:
            events = self.windows.setdefault(key, deque())
            self.windows.move_to_end(key)
            while events and events[0] <= now - window_seconds:
                events.popleft()
            while len(self.windows) > self.max_keys:
                self.windows.popitem(last=False)
            if len(events) >= limit:
                return max(1, math.ceil(events[0] + window_seconds - now))
            events.append(now)
            return 0
