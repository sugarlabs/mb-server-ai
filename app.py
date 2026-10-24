"""The server behind the AI widgets in Music Blocks: Reflection and the AI debugger.

Run: uvicorn app:app --port 8000
Environment: BEDROCK_API_KEY, and optionally ALLOWED_ORIGINS, BEDROCK_MODEL,
BEDROCK_REASONING, DAILY_REQUEST_LIMIT, DAILY_VISITOR_LIMIT, PER_MINUTE_LIMIT.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from limits import DAILY_REQUEST_LIMIT, limiter
from widgets import ALLOWED_ORIGINS, router

app = FastAPI(title="Music Blocks AI")
# Music Blocks is served from another address, so the browser asks first
# whether its page may call this server.
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["POST"], allow_headers=["Content-Type"])
app.include_router(router)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "requests_today": limiter.today, "daily_limit": DAILY_REQUEST_LIMIT}
