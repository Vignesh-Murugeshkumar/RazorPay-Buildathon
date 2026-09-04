import os
import sys

# Ensure the project root is on sys.path so `app` package is importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# ── Load FastAPI Application ──────────────────────────────────────────────────
# In Vercel's Python runtime, do NOT define or export `handler` or `application`.
# Exporting `handler` forces Vercel to treat this file as a BaseHTTPRequestHandler,
# which causes INTERNAL_FUNCTION_INVOCATION_FAILED for ASGI/FastAPI applications.
try:
    from app.main import app
except Exception as _err:
    import traceback
    _traceback_str = traceback.format_exc()
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse

    app = FastAPI(title="SentinelDispute Startup Failure")

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
    async def _startup_error_fallback(path: str):
        return PlainTextResponse(
            f"SentinelDispute failed to start on Vercel.\n\nError: {_err}\n\nTraceback:\n{_traceback_str}",
            status_code=500
        )

__all__ = ["app"]

