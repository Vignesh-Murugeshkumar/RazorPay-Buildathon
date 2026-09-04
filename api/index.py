import sys
import os
import traceback

# Ensure the root directory is on the Python path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from app.main import app
except Exception as e:
    tb = traceback.format_exc()
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="SentinelDispute Startup Diagnostic")

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def startup_error_handler(full_path: str):
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
                <head>
                    <title>SentinelDispute Startup Diagnostic</title>
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <style>
                        body {{ background: #0b0f19; color: #f8fafc; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; padding: 30px; margin: 0; }}
                        .container {{ max-width: 900px; margin: 0 auto; background: #1e293b; border: 1px solid #ef4444; border-radius: 12px; padding: 24px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
                        h2 {{ color: #ef4444; margin-top: 0; display: flex; align-items: center; gap: 10px; }}
                        p {{ color: #94a3b8; font-size: 14px; line-height: 1.5; }}
                        pre {{ background: #0f172a; border: 1px solid #334155; padding: 16px; border-radius: 8px; overflow-x: auto; color: #fca5a5; font-size: 13px; line-height: 1.4; }}
                        .tip {{ background: #1e1b4b; border: 1px solid #6366f1; padding: 12px 16px; border-radius: 8px; color: #c7d2fe; font-size: 13px; margin-top: 16px; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h2>⚠️ SentinelDispute Startup Error</h2>
                        <p>The application encountered an exception during serverless cold-start initialization:</p>
                        <pre>{tb}</pre>
                        <div class="tip">
                            <strong>💡 Diagnostic Tip:</strong> Check your Vercel Environment Variables (such as <code>DATABASE_URL</code> and <code>RAZORPAY_WEBHOOK_SECRET</code>) in the Vercel Dashboard.
                        </div>
                    </div>
                </body>
            </html>
            """,
            status_code=500
        )

# Vercel serverless function export
__all__ = ["app"]

