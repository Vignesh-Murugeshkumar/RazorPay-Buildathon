import os
import sys

# Ensure root directory is on sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.main import app as _app

# Explicit top-level assignments required by Vercel AST detector
app = _app
handler = app
application = app

__all__ = ["app", "handler", "application"]
