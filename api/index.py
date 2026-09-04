import os
import sys

# Ensure the project root is on sys.path so `app` package is importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


# ── Step 1: define fallback ASGI app at TRUE module top-level ──────────────────
# Vercel's static AST scanner requires a bare top-level assignment of
# `app`, `handler`, or `application` to recognise this as a Python function.
# The scanner does NOT execute code, so assignments inside try/except are
# invisible to it.  We define a safe fallback here, then override below.
async def app(scope, receive, send):
    """Fallback ASGI app shown only when the real FastAPI app fails to import."""
    if scope["type"] == "http":
        body = b"SentinelDispute: failed to start - check Vercel function logs for traceback."
        await send({
            "type": "http.response.start",
            "status": 503,
            "headers": [
                [b"content-type", b"text/plain"],
                [b"content-length", str(len(body)).encode()],
            ],
        })
        await send({"type": "http.response.body", "body": body})


# Vercel also accepts these aliases
handler = app
application = app


# ── Step 2: attempt to load the real FastAPI application ──────────────────────
# If import succeeds the module-level `app`, `handler`, `application` names
# are rebound to the real FastAPI instance at runtime.
try:
    from app.main import app as _fastapi_app   # noqa: E402
    app = _fastapi_app          # rebind at runtime (scanner already satisfied above)
    handler = _fastapi_app
    application = _fastapi_app
except Exception as _err:
    import traceback as _tb_mod
    _traceback = _tb_mod.format_exc()

    # Override fallback with a version that shows the actual error
    async def app(scope, receive, send):  # type: ignore[misc]  # noqa: F811
        if scope["type"] == "http":
            body = (
                f"SentinelDispute failed to start.\n\n"
                f"Error: {_err}\n\n"
                f"Traceback:\n{_traceback}"
            ).encode()
            await send({
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    [b"content-type", b"text/plain"],
                    [b"content-length", str(len(body)).encode()],
                ],
            })
            await send({"type": "http.response.body", "body": body})

    handler = app
    application = app


__all__ = ["app", "handler", "application"]
