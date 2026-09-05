import os
import sys

# Ensure the project root is on sys.path so `app` package is importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Module-level variables for capturing any startup failures
STARTUP_ERROR: str | None = None
STARTUP_TRACEBACK: str | None = None

# ── Load FastAPI Application ──────────────────────────────────────────────────
# In Vercel's Python runtime, do NOT define or export `handler` or `application`.
# Exporting `handler` forces Vercel to treat this file as a BaseHTTPRequestHandler,
# which causes INTERNAL_FUNCTION_INVOCATION_FAILED for ASGI/FastAPI applications.
try:
    from app.main import app
except Exception as exc:
    import traceback
    STARTUP_ERROR = f"{type(exc).__name__}: {exc}"
    STARTUP_TRACEBACK = traceback.format_exc()

    # Print original startup exception and traceback to Vercel runtime logs
    sys.stderr.write(f"CRITICAL: SentinelDispute failed to import app: {STARTUP_ERROR}\n")
    traceback.print_exc(file=sys.stderr)
    sys.stderr.flush()

    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse

    app = FastAPI(title="SentinelDispute Startup Failure")

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
    async def _startup_error_fallback(path: str):
        return PlainTextResponse(
            f"SentinelDispute failed to start on Vercel.\n\n"
            f"Error: {STARTUP_ERROR}\n\n"
            f"Traceback:\n{STARTUP_TRACEBACK}",
            status_code=500
        )

__all__ = ["app"]

