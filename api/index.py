import sys
import os

# Ensure the root directory is on the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app

# Vercel serverless function export
__all__ = ["app"]
