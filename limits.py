"""Request caps, so a busy day or a script cannot run up the bill or use up
the day for every child. The widgets run inside Music Blocks and cannot show a
bot check, so these caps are what stands between a script and the model."""

import os
import time
from collections import defaultdict, deque
from datetime import date

from fastapi import HTTPException, Request

DAILY_REQUEST_LIMIT = int(os.environ.get("DAILY_REQUEST_LIMIT", "500"))
PER_MINUTE_LIMIT = int(os.environ.get("PER_MINUTE_LIMIT", "10"))
# Without a cap per visitor, one script at the per-minute limit used up the
# whole day's requests for everyone in under an hour (22 Oct 2026 review).
DAILY_VISITOR_LIMIT = int(os.environ.get("DAILY_VISITOR_LIMIT", "100"))


class Limiter:
    """Caps model calls per visitor per minute and per day, and for everyone
    per day. Counts are kept in memory, so they reset on restart."""

    def __init__(self):
        self.recent: dict[str, deque] = defaultdict(deque)
        self.visitor_today: dict[str, int] = defaultdict(int)
        self.day = date.today()
        self.today = 0

    def check(self, request: Request) -> None:
        address = visitor(request)
        now = time.monotonic()
        if date.today() != self.day:
            self.day, self.today = date.today(), 0
            self.visitor_today.clear()
        if self.today >= DAILY_REQUEST_LIMIT:
            raise HTTPException(429, "The AI has answered all it can for today. Please try tomorrow.")
        if self.visitor_today[address] >= DAILY_VISITOR_LIMIT:
            raise HTTPException(429, "You have used the AI a lot today. Please come back tomorrow.")
        calls = self.recent[address]
        while calls and now - calls[0] > 60:
            calls.popleft()
        if len(calls) >= PER_MINUTE_LIMIT:
            raise HTTPException(429, "That is a lot of requests in one minute. Please wait a little.")
        calls.append(now)
        self.visitor_today[address] += 1
        self.today += 1


def visitor(request: Request) -> str:
    """The visitor's address. Each proxy adds the address it was called from
    to the end of X-Forwarded-For, so only the last entry, added by our own
    proxy, can be trusted. The first entry is whatever the caller wrote, and
    on 22 Oct 2026 a made-up one got past the per-minute cap on every request."""
    forwarded = [address.strip() for address in request.headers.get("x-forwarded-for", "").split(",")]
    return forwarded[-1] or (request.client.host if request.client else "unknown")


limiter = Limiter()
