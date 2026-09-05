"""
Unit tests proving Fail-Closed Database behavior in Production.

Validates that:
1. In production, missing or invalid PostgreSQL strictly raises RuntimeError.
2. Silent downgrade from PostgreSQL to SQLite is strictly prohibited in production.
3. Development and testing environments safely use SQLite.
4. Database health checks accurately report backend engine.
"""

import os
import pytest
from unittest.mock import patch
from app.core.db import DatabaseManager, sanitize_postgres_url


def test_production_fails_closed_when_url_missing():
    """Production must strictly fail closed if DATABASE_URL is missing."""
    mgr = DatabaseManager.__new__(DatabaseManager)
    mgr._is_pg_actual = False
    mgr._initialized = False

    with patch.dict(os.environ, {"ENVIRONMENT": "production", "DATABASE_URL": "", "SUPABASE_DATABASE_URL": "", "TEST_MODE": "0"}, clear=False):
        with pytest.raises(RuntimeError, match="strictly required in PRODUCTION environment"):
            mgr._init_db()


def test_production_fails_closed_when_connection_fails():
    """Production must raise RuntimeError on connection failure rather than silently downgrading to SQLite."""
    mgr = DatabaseManager.__new__(DatabaseManager)
    mgr._is_pg_actual = False
    mgr._initialized = False

    with patch.dict(os.environ, {
        "ENVIRONMENT": "production",
        "DATABASE_URL": "postgresql://invalid_user:invalid_pass@127.0.0.1:54329/invalid_db",
        "TEST_MODE": "0"
    }, clear=False):
        with pytest.raises(RuntimeError, match="Production PostgreSQL required but connection failed"):
            mgr._ensure_initialized()


def test_test_environment_uses_sqlite():
    """Testing environment must cleanly initialize SQLite without crashing."""
    mgr = DatabaseManager.__new__(DatabaseManager)
    mgr._is_pg_actual = False
    mgr._initialized = False

    with patch.dict(os.environ, {"ENVIRONMENT": "test", "TEST_MODE": "1"}, clear=False):
        mgr._ensure_initialized()
        assert mgr._is_postgres is False
        assert mgr.ping()["healthy"] is True
        assert mgr.ping()["engine"] == "sqlite"


def test_sanitize_postgres_url_encodes_special_characters():
    """URL sanitizer must properly encode complex passwords without breaking connection strings."""
    url = "postgresql://postgres.proj:MySecret@Pass#123@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
    sanitized = sanitize_postgres_url(url)
    assert sanitized is not None
    assert "MySecret%40Pass%23123" in sanitized
    assert "sslmode=require" in sanitized
