import os
import sys

# Ensure the project root is on sys.path so `app` package is importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from app.main import app
    handler = app
    application = app
except Exception as _import_error:
    # If the app fails to import (e.g. missing env vars, bad import), surface the
    # exact error as a minimal ASGI app so Vercel logs show a useful message.
    import traceback
    _tb = traceback.format_exc()

    async def app(scope, receive, send):
        if scope["type"] == "http":
            body = (
                f"SentinelDispute failed to start.\n\n"
                f"Error: {_import_error}\n\n"
                f"Traceback:\n{_tb}"
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
