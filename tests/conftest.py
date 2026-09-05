import os

# Ensure tests run against local SQLite and never touch or wait for remote databases
os.environ["ENVIRONMENT"] = "test"
os.environ["TEST_MODE"] = "1"
os.environ["DATABASE_URL"] = ""
os.environ["SUPABASE_DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""

import pytest


# Configure pytest-asyncio to auto-detect async test functions
# so we don't need @pytest.mark.asyncio on every test.
# "auto" mode: asyncio is the default event loop for all async tests.
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async (handled by pytest-asyncio)"
    )

