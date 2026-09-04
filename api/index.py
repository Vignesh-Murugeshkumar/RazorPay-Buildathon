import os
import sys
import traceback

# Ensure the root directory is on the Python path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from app.main import app
except Exception as exc:
    import logging
    error_details = traceback.format_exc()
    logging.error(f"FATAL STARTUP EXCEPTION in SentinelDispute: {error_details}")

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI(title="SentinelDispute Startup Diagnostic")

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"])
    async def startup_error_fallback(full_path: str):
        return JSONResponse(
            status_code=500,
            content={
                "error": "Startup Initialization Failure",
                "detail": str(exc),
                "traceback": error_details.splitlines()[-12:],
                "sys_path": sys.path,
                "root_dir": ROOT_DIR
            }
        )

# Export for Vercel Function runtime
__all__ = ["app"]

