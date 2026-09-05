import os
import sys

# Ensure the project root is on sys.path so `app` package is importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Module-level variables for capturing any startup failures
STARTUP_ERROR: str | None = None
STARTUP_TRACEBACK: str | None = None

from starlette.types import ASGIApp, Scope, Receive, Send


class VercelPathPreservingMiddleware:
    """
    ASGI middleware ensuring that the original request path is preserved
    when running on Vercel's serverless infrastructure.

    When Vercel rewrites incoming requests to an entrypoint (e.g. /(.*) -> /api/index.py),
    the ASGI scope['path'] is rewritten to '/api/index.py' (or loses the '/api' prefix),
    causing FastAPI route matching to fail with 404 {"detail": "Not Found"}.

    This middleware extracts the original requested path from Vercel's edge headers
    (x-matched-path, x-forwarded-uri, x-original-uri, x-invoke-path, x-real-path) and
    restores scope['path'] and scope['raw_path'] so FastAPI matches the correct route.
    """
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            matched = (
                headers.get(b"x-matched-path")
                or headers.get(b"x-forwarded-uri")
                or headers.get(b"x-original-uri")
                or headers.get(b"x-invoke-path")
                or headers.get(b"x-real-path")
            )
            if matched:
                original_path = matched.decode("latin1").split("?")[0]
                current_path = scope.get("path", "")
                if current_path in ("/api/index.py", "/api/index", "/api", "") or (
                    original_path.startswith("/api") and not current_path.startswith("/api")
                ):
                    scope["path"] = original_path
                    scope["raw_path"] = original_path.encode("latin1")

        await self.app(scope, receive, send)


# ── Load FastAPI Application ──────────────────────────────────────────────────
# In Vercel's Python runtime, do NOT define or export `handler` or `application`.
# Exporting `handler` forces Vercel to treat this file as a BaseHTTPRequestHandler,
# which causes INTERNAL_FUNCTION_INVOCATION_FAILED for ASGI/FastAPI applications.
try:
    from app.main import app
    app.add_middleware(VercelPathPreservingMiddleware)
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

