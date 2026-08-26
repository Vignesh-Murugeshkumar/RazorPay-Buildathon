import pytest


# Configure pytest-asyncio to auto-detect async test functions
# so we don't need @pytest.mark.asyncio on every test.
# "auto" mode: asyncio is the default event loop for all async tests.
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async (handled by pytest-asyncio)"
    )
