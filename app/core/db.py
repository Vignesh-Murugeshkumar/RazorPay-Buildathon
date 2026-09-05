import os
import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import List, Optional, Dict, Any, Tuple
from app.schemas.dispute import Dossier, RazorpayDisputeWebhook
from app.services.ledger import LedgerBlock
from app.core.logger import get_logger

logger = get_logger("db")

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DATABASE_URL") or os.getenv("POSTGRES_URL")
# Safety: never allow destructive clear on prod Postgres via test code
# Set ENVIRONMENT=test or TEST_MODE=1 to allow clear_all_data() on SQLite only
_IS_TEST_ENV = os.getenv("ENVIRONMENT", "development").lower() in ("test", "testing") or os.getenv("TEST_MODE", "0") == "1"

def sanitize_postgres_url(url: Optional[str]) -> Optional[str]:
    """Cleans up and robustly URL-encodes passwords in PostgreSQL connection URLs.
    
    Handles passwords containing special characters like '@', '#', etc.
    Works correctly with Supabase URLs of the form:
      postgresql://postgres.PROJECT_REF:PASSWORD@HOST:PORT/DB
    """
    if not url or "[YOUR-PASSWORD]" in url:
        return None
    import urllib.parse
    cleaned = url.strip()
    if cleaned.startswith("postgres://"):
        cleaned = cleaned.replace("postgres://", "postgresql://", 1)

    # Robust multi-@ password handling:
    # Find the scheme, then locate the LAST '@' before the host as the user/host boundary.
    if "://" in cleaned:
        try:
            scheme, rest = cleaned.split("://", 1)
            # The host starts after the last '@'
            last_at_idx = rest.rfind("@")
            if last_at_idx != -1:
                userinfo = rest[:last_at_idx]     # everything before last '@'
                hostpart = rest[last_at_idx + 1:]  # host:port/db
                # Split userinfo into user:password (split on FIRST ':')
                if ":" in userinfo:
                    user, raw_password = userinfo.split(":", 1)
                    # Only re-encode if password contains characters that need encoding
                    if any(c in raw_password for c in "@#%+? "):
                        encoded_password = urllib.parse.quote(raw_password, safe="")
                        cleaned = f"{scheme}://{user}:{encoded_password}@{hostpart}"
        except Exception:
            pass  # leave cleaned as-is if parsing fails

    if "supabase.com" in cleaned and "sslmode" not in cleaned:
        separator = "&" if "?" in cleaned else "?"
        cleaned = f"{cleaned}{separator}sslmode=require"
    return cleaned


# Determine optimal fallback SQLite path for local/offline dev or serverless
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH")
if not SQLITE_DB_PATH:
    if os.path.exists("/tmp"):
        # Serverless / Linux runtime: /tmp is guaranteed writable
        SQLITE_DB_PATH = "/tmp/sentinel_dispute.db"
    else:
        SQLITE_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "sentinel_dispute.db")


class DatabaseManager:
    """
    Unified Database Manager for SentinelDispute.
    - Production / Cloud: Supabase (PostgreSQL) with native JSONB, pooled connections, and ACID safety.
    - Local / Testing: Embedded SQLite fallback for zero-configuration development and fast unit testing.
    """
    _instance = None
    _lock = threading.RLock()

    @property
    def _is_postgres(self) -> bool:
        is_test = os.getenv("ENVIRONMENT", "development").lower() in ("test", "testing") or os.getenv("TEST_MODE", "0") == "1"
        if is_test:
            return False
        return getattr(self, "_is_pg_actual", False)

    @_is_postgres.setter
    def _is_postgres(self, val: bool):
        self._is_pg_actual = val

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DatabaseManager, cls).__new__(cls)
                cls._instance._is_pg_actual = False
                cls._instance._pool = None
                cls._instance._initialized = False
            return cls._instance

    def _ensure_initialized(self):
        """Thread-safe lazy initialization deferred to first actual DB operation."""
        if getattr(self, "_initialized", False):
            return
        with self._lock:
            if getattr(self, "_initialized", False):
                return
            try:
                self._init_db()
            except Exception as _e:
                logger.warning("DatabaseManager lazy initialization failed, falling back to SQLite", error=str(_e))
                self._is_postgres = False
            self._initialized = True

    def _init_db(self):
        with self._lock:
            active_db_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DATABASE_URL") or os.getenv("POSTGRES_URL") or DATABASE_URL
            is_test = os.getenv("ENVIRONMENT", "development").lower() in ("test", "testing") or os.getenv("TEST_MODE", "0") == "1"
            cleaned_url = sanitize_postgres_url(active_db_url) if not is_test else None
            if cleaned_url:
                try:
                    import psycopg
                    from psycopg.rows import dict_row
                    
                    self._pg_url = cleaned_url
                    self._is_postgres = True

                    # Initialize PostgreSQL / Supabase tables with fast fail-safe connect and 3s statement timeout
                    with psycopg.connect(
                        self._pg_url,
                        autocommit=True,
                        connect_timeout=3,
                        prepare_threshold=None,
                        options="-c statement_timeout=3000"
                    ) as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                CREATE TABLE IF NOT EXISTS dossiers (
                                    dispute_id VARCHAR PRIMARY KEY,
                                    payment_id VARCHAR,
                                    amount_inr NUMERIC,
                                    card_network VARCHAR,
                                    reason_code VARCHAR,
                                    confidence_score NUMERIC,
                                    decision VARCHAR,
                                    timestamp VARCHAR,
                                    sealed_hash VARCHAR,
                                    dossier_json JSONB NOT NULL,
                                    raw_payload_json JSONB,
                                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                                );
                                
                                CREATE TABLE IF NOT EXISTS ledger_blocks (
                                    block_index INTEGER PRIMARY KEY,
                                    previous_hash VARCHAR NOT NULL,
                                    timestamp VARCHAR NOT NULL,
                                    agent_id VARCHAR NOT NULL,
                                    state_transition VARCHAR NOT NULL,
                                    payload_hash VARCHAR NOT NULL,
                                    block_hash VARCHAR NOT NULL,
                                    payload_json JSONB
                                );
                                
                                CREATE TABLE IF NOT EXISTS processed_events (
                                    event_id VARCHAR PRIMARY KEY,
                                    signature VARCHAR,
                                    status VARCHAR(32) NOT NULL DEFAULT 'RECEIVED',
                                    result_json JSONB,
                                    error_message TEXT,
                                    received_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                                );

                                CREATE TABLE IF NOT EXISTS customer_telemetry (
                                    id UUID PRIMARY KEY,
                                    card_fingerprint VARCHAR(64) NOT NULL,
                                    customer_id VARCHAR(64) NOT NULL,
                                    ip_address VARCHAR(64) NOT NULL,
                                    device_fingerprint VARCHAR(128) NOT NULL,
                                    shipping_address_hash VARCHAR(64) NOT NULL,
                                    transaction_time TIMESTAMP WITH TIME ZONE NOT NULL,
                                    dispute_status VARCHAR(16) DEFAULT 'undisputed',
                                    amount_inr NUMERIC DEFAULT 0.0,
                                    payload_json JSONB
                                );
                                CREATE INDEX IF NOT EXISTS idx_telemetry_lookup ON customer_telemetry (card_fingerprint, transaction_time DESC);

                                CREATE TABLE IF NOT EXISTS pre_dispute_logs (
                                    inquiry_id VARCHAR PRIMARY KEY,
                                    network VARCHAR NOT NULL,
                                    card_fingerprint VARCHAR(64) NOT NULL,
                                    status VARCHAR(32) NOT NULL,
                                    evidence_type VARCHAR(32),
                                    response_time_ms NUMERIC,
                                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                                    payload_json JSONB
                                );

                                CREATE TABLE IF NOT EXISTS dispute_outcomes (
                                    dispute_id VARCHAR PRIMARY KEY,
                                    card_bin VARCHAR(8),
                                    issuing_bank VARCHAR(64),
                                    network VARCHAR(16),
                                    reason_code VARCHAR(16),
                                    outcome VARCHAR(16) NOT NULL,
                                    amount_inr NUMERIC,
                                    confidence_score NUMERIC,
                                    evidence_types_used JSONB,
                                    resolved_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                                );

                                CREATE TABLE IF NOT EXISTS dispute_timeline_events (
                                    id SERIAL PRIMARY KEY,
                                    dispute_id VARCHAR NOT NULL,
                                    event_type VARCHAR(64) NOT NULL,
                                    title VARCHAR(255) NOT NULL,
                                    description TEXT NOT NULL,
                                    metadata JSONB,
                                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                                );
                                CREATE INDEX IF NOT EXISTS idx_timeline_dispute ON dispute_timeline_events (dispute_id, timestamp ASC);
                            """)
                            
                    is_serverless = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
                    if is_serverless:
                        self._pool = None
                        logger.info("Serverless runtime detected; using direct connections to Supabase PgBouncer pooler")
                    else:
                        try:
                            from psycopg_pool import ConnectionPool
                            self._pool = ConnectionPool(
                                conninfo=self._pg_url,
                                min_size=1,
                                max_size=10,
                                timeout=5.0,
                                kwargs={"connect_timeout": 5, "prepare_threshold": None},
                                open=True
                            )
                            logger.info("Initialized PostgreSQL ConnectionPool (psycopg-pool) successfully")
                        except Exception as pool_err:
                            self._pool = None
                            logger.warning("Could not initialize psycopg-pool, using direct connections", error=str(pool_err))

                    logger.info("Connected and initialized Supabase (PostgreSQL) database successfully")
                    return
                except Exception as e:
                    logger.warning("Failed to connect to Supabase PostgreSQL, falling back to SQLite", error=str(e))
                    self._is_postgres = False

            # Fallback to Embedded SQLite
            try:
                self._is_postgres = False
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)

                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS dossiers (
                        dispute_id TEXT PRIMARY KEY,
                        payment_id TEXT,
                        amount_inr REAL,
                        card_network TEXT,
                        reason_code TEXT,
                        confidence_score REAL,
                        decision TEXT,
                        timestamp TEXT,
                        sealed_hash TEXT,
                        dossier_json TEXT NOT NULL,
                        raw_payload_json TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ledger_blocks (
                        block_index INTEGER PRIMARY KEY,
                        previous_hash TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        agent_id TEXT NOT NULL,
                        state_transition TEXT NOT NULL,
                        payload_hash TEXT NOT NULL,
                        block_hash TEXT NOT NULL,
                        payload_json TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS processed_events (
                        event_id TEXT PRIMARY KEY,
                        signature TEXT,
                        status TEXT NOT NULL DEFAULT 'RECEIVED',
                        result_json TEXT,
                        error_message TEXT,
                        received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # Migrations for existing tables
                for col_def in [
                    "status TEXT NOT NULL DEFAULT 'RECEIVED'",
                    "result_json TEXT",
                    "error_message TEXT",
                    "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ]:
                    try:
                        col_name = col_def.split()[0]
                        cur.execute(f"ALTER TABLE processed_events ADD COLUMN {col_def}")
                    except Exception:
                        pass
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS customer_telemetry (
                        id TEXT PRIMARY KEY,
                        card_fingerprint TEXT NOT NULL,
                        customer_id TEXT NOT NULL,
                        ip_address TEXT NOT NULL,
                        device_fingerprint TEXT NOT NULL,
                        shipping_address_hash TEXT NOT NULL,
                        transaction_time TEXT NOT NULL,
                        dispute_status TEXT DEFAULT 'undisputed',
                        amount_inr REAL DEFAULT 0.0,
                        payload_json TEXT
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_lookup ON customer_telemetry (card_fingerprint, transaction_time DESC)")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS pre_dispute_logs (
                        inquiry_id TEXT PRIMARY KEY,
                        network TEXT NOT NULL,
                        card_fingerprint TEXT NOT NULL,
                        status TEXT NOT NULL,
                        evidence_type TEXT,
                        response_time_ms REAL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        payload_json TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS dispute_outcomes (
                        dispute_id TEXT PRIMARY KEY,
                        card_bin TEXT,
                        issuing_bank TEXT,
                        network TEXT,
                        reason_code TEXT,
                        outcome TEXT NOT NULL,
                        amount_inr REAL,
                        confidence_score REAL,
                        evidence_types_used TEXT,
                        resolved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS dispute_timeline_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        dispute_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        metadata TEXT,
                        timestamp TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_timeline_dispute ON dispute_timeline_events (dispute_id, timestamp ASC)")
                conn.commit()
                conn.close()
                logger.info("SQLite database initialized successfully", db_path=SQLITE_DB_PATH)
            except Exception as e:
                logger.error("Failed to initialize SQLite database", error=str(e), db_path=SQLITE_DB_PATH)

    @contextmanager
    def _get_pg_conn(self, row_factory=None):
        """Yields a PostgreSQL connection from the connection pool, or creates an ad-hoc connection."""
        self._ensure_initialized()
        if hasattr(self, "_pool") and self._pool is not None:
            with self._pool.connection() as conn:
                conn.autocommit = True
                if row_factory:
                    conn.row_factory = row_factory
                yield conn
        else:
            import psycopg
            with psycopg.connect(
                self._pg_url,
                autocommit=True,
                row_factory=row_factory,
                connect_timeout=3,
                prepare_threshold=None,
                options="-c statement_timeout=3000"
            ) as conn:
                yield conn

    def ping(self) -> Dict[str, Any]:
        """Production health check ping verifying live database connectivity."""
        self._ensure_initialized()
        import time
        t0 = time.time()
        if self._is_postgres:
            try:
                with self._get_pg_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1;")
                        cur.fetchone()
                latency = round((time.time() - t0) * 1000, 2)
                return {
                    "healthy": True,
                    "engine": "postgresql",
                    "latency_ms": latency,
                    "pooled": bool(hasattr(self, "_pool") and self._pool is not None)
                }
            except Exception as e:
                return {
                    "healthy": False,
                    "engine": "postgresql",
                    "error": str(e)
                }
        else:
            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, timeout=5.0)
                cur = conn.cursor()
                cur.execute("SELECT 1;")
                cur.fetchone()
                conn.close()
                latency = round((time.time() - t0) * 1000, 2)
                return {
                    "healthy": True,
                    "engine": "sqlite",
                    "path": SQLITE_DB_PATH,
                    "latency_ms": latency
                }
            except Exception as e:
                return {
                    "healthy": False,
                    "engine": "sqlite",
                    "error": str(e)
                }

    def close(self):
        """Gracefully closes connection pools on shutdown."""
        if hasattr(self, "_pool") and self._pool:
            try:
                self._pool.close()
                logger.info("Closed PostgreSQL connection pool")
            except Exception as e:
                logger.warning("Error closing PostgreSQL connection pool", error=str(e))

    # ------------------ DOSSIERS CRUD ------------------
    def save_dossier(self, dossier: Dossier, raw_payload: Optional[RazorpayDisputeWebhook] = None):
        self._ensure_initialized()
        with self._lock:
            dossier_dict = dossier.model_dump()
            raw_dict = raw_payload.model_dump() if raw_payload else None
            
            if self._is_postgres:
                try:
                    with self._get_pg_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                INSERT INTO dossiers (
                                    dispute_id, payment_id, amount_inr, card_network, reason_code,
                                    confidence_score, decision, timestamp, sealed_hash,
                                    dossier_json, raw_payload_json, updated_at
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                                ON CONFLICT (dispute_id) DO UPDATE SET
                                    confidence_score = EXCLUDED.confidence_score,
                                    decision = EXCLUDED.decision,
                                    sealed_hash = EXCLUDED.sealed_hash,
                                    dossier_json = EXCLUDED.dossier_json,
                                    raw_payload_json = EXCLUDED.raw_payload_json,
                                    updated_at = CURRENT_TIMESTAMP;
                            """, (
                                dossier.dispute_id,
                                dossier.payment_id,
                                dossier.amount_inr,
                                dossier.card_network,
                                dossier.reason_code,
                                dossier.confidence_score,
                                dossier.decision,
                                dossier.timestamp,
                                dossier.sealed_hash,
                                json.dumps(dossier_dict),
                                json.dumps(raw_dict) if raw_dict else None
                            ))
                    return
                except Exception as e:
                    logger.error("Error saving dossier to Supabase Postgres", dispute_id=dossier.dispute_id, error=str(e))

            # SQLite fallback
            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                cur = conn.cursor()
                cur.execute("""
                    INSERT OR REPLACE INTO dossiers (
                        dispute_id, payment_id, amount_inr, card_network, reason_code,
                        confidence_score, decision, timestamp, sealed_hash,
                        dossier_json, raw_payload_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    dossier.dispute_id,
                    dossier.payment_id,
                    dossier.amount_inr,
                    dossier.card_network,
                    dossier.reason_code,
                    dossier.confidence_score,
                    dossier.decision,
                    dossier.timestamp,
                    dossier.sealed_hash,
                    json.dumps(dossier_dict),
                    json.dumps(raw_dict) if raw_dict else None
                ))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error("Error saving dossier to SQLite", dispute_id=dossier.dispute_id, error=str(e))

    def get_dossier(self, dispute_id: str) -> Optional[Dossier]:
        self._ensure_initialized()
        with self._lock:
            if self._is_postgres:
                try:
                    from psycopg.rows import dict_row
                    with self._get_pg_conn(row_factory=dict_row) as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT dossier_json FROM dossiers WHERE dispute_id = %s", (dispute_id,))
                            row = cur.fetchone()
                            if row:
                                data = row["dossier_json"]
                                if isinstance(data, str):
                                    data = json.loads(data)
                                return Dossier(**data)
                except Exception as e:
                    logger.error("Error fetching dossier from Supabase", dispute_id=dispute_id, error=str(e))

            # SQLite fallback
            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT dossier_json FROM dossiers WHERE dispute_id = ?", (dispute_id,))
                row = cur.fetchone()
                conn.close()
                if row:
                    data = json.loads(row["dossier_json"])
                    return Dossier(**data)
            except Exception as e:
                logger.error("Error fetching dossier from SQLite", dispute_id=dispute_id, error=str(e))
            return None

    def get_all_dossiers(self) -> Dict[str, Dossier]:
        self._ensure_initialized()
        with self._lock:
            result = {}
            if self._is_postgres:
                try:
                    from psycopg.rows import dict_row
                    with self._get_pg_conn(row_factory=dict_row) as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT dispute_id, dossier_json FROM dossiers ORDER BY updated_at ASC")
                            rows = cur.fetchall()
                            for r in rows:
                                try:
                                    data = r["dossier_json"]
                                    if isinstance(data, str):
                                        data = json.loads(data)
                                    result[r["dispute_id"]] = Dossier(**data)
                                except Exception:
                                    pass
                    return result
                except Exception as e:
                    logger.error("Error loading all dossiers from Supabase", error=str(e))

            # SQLite fallback
            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT dispute_id, dossier_json FROM dossiers ORDER BY updated_at ASC")
                rows = cur.fetchall()
                conn.close()
                for r in rows:
                    try:
                        data = json.loads(r["dossier_json"])
                        result[r["dispute_id"]] = Dossier(**data)
                    except Exception:
                        pass
            except Exception as e:
                logger.error("Error loading all dossiers from SQLite", error=str(e))
            return result

    def get_raw_payload(self, dispute_id: str) -> Optional[RazorpayDisputeWebhook]:
        self._ensure_initialized()
        with self._lock:
            if self._is_postgres:
                try:
                    from psycopg.rows import dict_row
                    with self._get_pg_conn(row_factory=dict_row) as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT raw_payload_json FROM dossiers WHERE dispute_id = %s", (dispute_id,))
                            row = cur.fetchone()
                            if row and row["raw_payload_json"]:
                                data = row["raw_payload_json"]
                                if isinstance(data, str):
                                    data = json.loads(data)
                                return RazorpayDisputeWebhook(**data)
                except Exception as e:
                    logger.error("Error fetching raw payload from Supabase", dispute_id=dispute_id, error=str(e))

            # SQLite fallback
            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT raw_payload_json FROM dossiers WHERE dispute_id = ?", (dispute_id,))
                row = cur.fetchone()
                conn.close()
                if row and row["raw_payload_json"]:
                    data = json.loads(row["raw_payload_json"])
                    return RazorpayDisputeWebhook(**data)
            except Exception as e:
                logger.error("Error fetching raw payload from SQLite", dispute_id=dispute_id, error=str(e))
            return None

    # ------------------ LEDGER BLOCKS CRUD ------------------
    def save_ledger_block(self, block: LedgerBlock, payload_data: Any = None):
        self._ensure_initialized()
        with self._lock:
            payload_json = json.dumps(payload_data) if payload_data else None
            
            if self._is_postgres:
                try:
                    with self._get_pg_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                INSERT INTO ledger_blocks (
                                    block_index, previous_hash, timestamp, agent_id,
                                    state_transition, payload_hash, block_hash, payload_json
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (block_index) DO NOTHING;
                            """, (
                                block.index,
                                block.previous_hash,
                                block.timestamp,
                                block.agent_id,
                                block.state_transition,
                                block.payload_hash,
                                block.block_hash,
                                payload_json
                            ))
                    return
                except Exception as e:
                    logger.error("Error saving ledger block to Supabase", index=block.index, error=str(e))

            # SQLite fallback
            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                cur = conn.cursor()
                cur.execute("""
                    INSERT OR REPLACE INTO ledger_blocks (
                        block_index, previous_hash, timestamp, agent_id,
                        state_transition, payload_hash, block_hash, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    block.index,
                    block.previous_hash,
                    block.timestamp,
                    block.agent_id,
                    block.state_transition,
                    block.payload_hash,
                    block.block_hash,
                    payload_json
                ))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error("Error persisting ledger block to SQLite", index=block.index, error=str(e))

    def load_all_ledger_blocks(self) -> List[LedgerBlock]:
        self._ensure_initialized()
        with self._lock:
            blocks = []
            if self._is_postgres:
                try:
                    from psycopg.rows import dict_row
                    with self._get_pg_conn(row_factory=dict_row) as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                SELECT block_index, previous_hash, timestamp, agent_id, state_transition, payload_hash, block_hash
                                FROM ledger_blocks
                                ORDER BY block_index ASC
                            """)
                            rows = cur.fetchall()
                            for r in rows:
                                blocks.append(
                                    LedgerBlock(
                                        index=r["block_index"],
                                        previous_hash=r["previous_hash"],
                                        timestamp=r["timestamp"],
                                        agent_id=r["agent_id"],
                                        state_transition=r["state_transition"],
                                        payload_hash=r["payload_hash"],
                                        block_hash=r["block_hash"]
                                    )
                                )
                    return blocks
                except Exception as e:
                    logger.error("Error loading ledger blocks from Supabase", error=str(e))

            # SQLite fallback
            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("""
                    SELECT block_index, previous_hash, timestamp, agent_id, state_transition, payload_hash, block_hash
                    FROM ledger_blocks
                    ORDER BY block_index ASC
                """)
                rows = cur.fetchall()
                conn.close()
                for r in rows:
                    blocks.append(
                        LedgerBlock(
                            index=r["block_index"],
                            previous_hash=r["previous_hash"],
                            timestamp=r["timestamp"],
                            agent_id=r["agent_id"],
                            state_transition=r["state_transition"],
                            payload_hash=r["payload_hash"],
                            block_hash=r["block_hash"]
                        )
                    )
            except Exception as e:
                logger.error("Error loading ledger blocks from SQLite", error=str(e))
            return blocks

    def clear_all_data(self):
        self._ensure_initialized()
        with self._lock:
            if self._is_postgres:
                if not _IS_TEST_ENV:
                    logger.warning(
                        "clear_all_data() called on Postgres but ENVIRONMENT is not 'test'. "
                        "Skipping TRUNCATE to protect production data. "
                        "Set ENVIRONMENT=test or TEST_MODE=1 to allow this in a test environment."
                    )
                else:
                    try:
                        with self._get_pg_conn() as conn:
                            with conn.cursor() as cur:
                                cur.execute("TRUNCATE TABLE dossiers, ledger_blocks, processed_events, dispute_timeline_events;")
                        logger.info("Cleared all Supabase tables (test environment)")
                    except Exception as e:
                        logger.error("Error clearing Supabase tables", error=str(e))

            # SQLite is always safe to clear — local file only
            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                cur = conn.cursor()
                cur.execute("DELETE FROM dossiers")
                cur.execute("DELETE FROM ledger_blocks")
                cur.execute("DELETE FROM processed_events")
                cur.execute("DELETE FROM dispute_timeline_events")
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error("Error clearing SQLite DB", error=str(e))


    # ------------------ REPLAY GUARD & ATOMIC EVENT LIFECYCLE ------------------
    def register_webhook_event(self, event_id: str, signature: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Atomically inspects and registers incoming webhook events in the persistence layer.
        Lifecycle states: RECEIVED -> PROCESSING -> COMPLETED | FAILED
        Returns:
            ("PROCEED", None) - Event claimed as PROCESSING; safe to execute workflow.
            ("COMPLETED", cached_result) - Event already completed; return cached 200 payload.
            ("PROCESSING", None) - Event currently executing concurrently in another worker.
        """
        with self._lock:
            if self._is_postgres:
                try:
                    from psycopg.rows import dict_row
                    with self._get_pg_conn(row_factory=dict_row) as conn:
                        with conn.cursor() as cur:
                            # 1. Attempt atomic insert to claim PROCESSING state
                            cur.execute(
                                """
                                INSERT INTO processed_events (event_id, signature, status)
                                VALUES (%s, %s, 'PROCESSING')
                                ON CONFLICT (event_id) DO NOTHING
                                RETURNING event_id;
                                """,
                                (event_id, signature)
                            )
                            claimed = cur.fetchone()
                            if claimed is not None:
                                return "PROCEED", None

                            # 2. Row exists; inspect state under row-level lock
                            cur.execute(
                                "SELECT status, result_json FROM processed_events WHERE event_id = %s FOR UPDATE",
                                (event_id,)
                            )
                            existing = cur.fetchone()
                            if not existing:
                                return "PROCEED", None

                            st = existing.get("status", "COMPLETED")
                            if st == "COMPLETED":
                                res = existing.get("result_json")
                                if isinstance(res, str):
                                    try:
                                        res = json.loads(res)
                                    except Exception:
                                        pass
                                return "COMPLETED", res if isinstance(res, dict) else {}
                            elif st == "PROCESSING":
                                return "PROCESSING", None
                            elif st == "FAILED":
                                # Safely reclaim failed event for reprocessing
                                cur.execute(
                                    """
                                    UPDATE processed_events
                                    SET status = 'PROCESSING', updated_at = CURRENT_TIMESTAMP, error_message = NULL
                                    WHERE event_id = %s AND status = 'FAILED'
                                    RETURNING event_id;
                                    """,
                                    (event_id,)
                                )
                                if cur.fetchone():
                                    return "PROCEED", None
                                return "PROCESSING", None
                            return "PROCESSING", None
                except Exception as e:
                    logger.error("Error in Supabase register_webhook_event", event_id=event_id, error=str(e))

            # SQLite fallback (thread-safe and transaction-isolated)
            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                try:
                    cur.execute("BEGIN IMMEDIATE")
                    cur.execute("SELECT status, result_json FROM processed_events WHERE event_id = ?", (event_id,))
                    existing = cur.fetchone()
                    if existing is None:
                        cur.execute(
                            "INSERT INTO processed_events (event_id, signature, status) VALUES (?, ?, 'PROCESSING')",
                            (event_id, signature)
                        )
                        conn.commit()
                        return "PROCEED", None

                    st = existing["status"]
                    if st == "COMPLETED":
                        res_raw = existing["result_json"]
                        res = json.loads(res_raw) if res_raw else {}
                        conn.commit()
                        return "COMPLETED", res
                    elif st == "PROCESSING":
                        conn.commit()
                        return "PROCESSING", None
                    elif st == "FAILED":
                        cur.execute(
                            "UPDATE processed_events SET status = 'PROCESSING', updated_at = CURRENT_TIMESTAMP, error_message = NULL WHERE event_id = ? AND status = 'FAILED'",
                            (event_id,)
                        )
                        conn.commit()
                        return "PROCEED", None
                    conn.commit()
                    return "PROCESSING", None
                finally:
                    conn.close()
            except Exception as e:
                logger.error("Error in SQLite register_webhook_event", error=str(e))
                return "PROCEED", None

    def complete_webhook_event(self, event_id: str, result_payload: Dict[str, Any]) -> bool:
        """Marks event as COMPLETED and caches result for idempotent replay."""
        with self._lock:
            payload_str = json.dumps(result_payload)
            if self._is_postgres:
                try:
                    with self._get_pg_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                UPDATE processed_events
                                SET status = 'COMPLETED', result_json = %s, updated_at = CURRENT_TIMESTAMP
                                WHERE event_id = %s
                                """,
                                (payload_str, event_id)
                            )
                            return True
                except Exception as e:
                    logger.error("Error completing Postgres webhook event", event_id=event_id, error=str(e))

            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                cur = conn.cursor()
                cur.execute(
                    "UPDATE processed_events SET status = 'COMPLETED', result_json = ?, updated_at = CURRENT_TIMESTAMP WHERE event_id = ?",
                    (payload_str, event_id)
                )
                conn.commit()
                conn.close()
                return True
            except Exception as e:
                logger.error("Error completing SQLite webhook event", event_id=event_id, error=str(e))
                return False

    def fail_webhook_event(self, event_id: str, error_message: str) -> bool:
        """Marks event as FAILED with error detail to allow safe debugging and retry."""
        with self._lock:
            if self._is_postgres:
                try:
                    with self._get_pg_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                UPDATE processed_events
                                SET status = 'FAILED', error_message = %s, updated_at = CURRENT_TIMESTAMP
                                WHERE event_id = %s
                                """,
                                (error_message[:1000], event_id)
                            )
                            return True
                except Exception as e:
                    logger.error("Error failing Postgres webhook event", event_id=event_id, error=str(e))

            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                cur = conn.cursor()
                cur.execute(
                    "UPDATE processed_events SET status = 'FAILED', error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE event_id = ?",
                    (error_message[:1000], event_id)
                )
                conn.commit()
                conn.close()
                return True
            except Exception as e:
                logger.error("Error failing SQLite webhook event", event_id=event_id, error=str(e))
                return False

    def record_and_verify_event(self, event_id: str, signature: str) -> bool:
        """
        Legacy boolean compatibility wrapper for replay detection tests.
        Returns True if fresh/new, False if duplicate/replaying.
        """
        action, _ = self.register_webhook_event(event_id, signature)
        return action == "PROCEED"


    # ------------------ TELEMETRY COLD STORAGE ------------------
    def insert_customer_telemetry(
        self,
        record_id: str,
        card_fingerprint: str,
        customer_id: str,
        ip_address: str,
        device_fingerprint: str,
        shipping_address_hash: str,
        transaction_time_iso: str,
        dispute_status: str = "undisputed",
        amount_inr: float = 0.0,
        payload: Optional[Dict[str, Any]] = None
    ) -> bool:
        with self._lock:
            payload_str = json.dumps(payload or {})
            if self._is_postgres:
                try:
                    with self._get_pg_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                INSERT INTO customer_telemetry (
                                    id, card_fingerprint, customer_id, ip_address,
                                    device_fingerprint, shipping_address_hash,
                                    transaction_time, dispute_status, amount_inr, payload_json
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (id) DO NOTHING;
                            """, (
                                record_id, card_fingerprint, customer_id, ip_address,
                                device_fingerprint, shipping_address_hash,
                                transaction_time_iso, dispute_status, amount_inr, payload_str
                            ))
                            return True
                except Exception as e:
                    logger.error("Error inserting customer telemetry into Supabase", error=str(e))

            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                cur = conn.cursor()
                cur.execute("""
                    INSERT OR IGNORE INTO customer_telemetry (
                        id, card_fingerprint, customer_id, ip_address,
                        device_fingerprint, shipping_address_hash,
                        transaction_time, dispute_status, amount_inr, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record_id, card_fingerprint, customer_id, ip_address,
                    device_fingerprint, shipping_address_hash,
                    transaction_time_iso, dispute_status, amount_inr, payload_str
                ))
                conn.commit()
                conn.close()
                return True
            except Exception as e:
                logger.error("Error inserting customer telemetry into SQLite", error=str(e))
                return False

    # ------------------ PRE-DISPUTE INTERCEPTION LOGS ------------------
    def save_pre_dispute_log(
        self,
        inquiry_id: str,
        network: str,
        card_fingerprint: str,
        status: str,
        evidence_type: Optional[str],
        response_time_ms: float,
        payload: Optional[Dict[str, Any]] = None
    ) -> bool:
        with self._lock:
            payload_str = json.dumps(payload or {})
            if self._is_postgres:
                try:
                    with self._get_pg_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                INSERT INTO pre_dispute_logs (
                                    inquiry_id, network, card_fingerprint, status,
                                    evidence_type, response_time_ms, payload_json
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (inquiry_id) DO UPDATE SET
                                    status = EXCLUDED.status,
                                    evidence_type = EXCLUDED.evidence_type,
                                    response_time_ms = EXCLUDED.response_time_ms,
                                    payload_json = EXCLUDED.payload_json;
                            """, (
                                inquiry_id, network, card_fingerprint, status,
                                evidence_type, response_time_ms, payload_str
                            ))
                            return True
                except Exception as e:
                    logger.error("Error saving pre-dispute log in Supabase", error=str(e))

            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                cur = conn.cursor()
                cur.execute("""
                    INSERT OR REPLACE INTO pre_dispute_logs (
                        inquiry_id, network, card_fingerprint, status,
                        evidence_type, response_time_ms, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    inquiry_id, network, card_fingerprint, status,
                    evidence_type, response_time_ms, payload_str
                ))
                conn.commit()
                conn.close()
                return True
            except Exception as e:
                logger.error("Error saving pre-dispute log in SQLite", error=str(e))
                return False

    # ------------------ CLOSED-LOOP DISPUTE OUTCOMES ------------------
    def save_dispute_outcome(
        self,
        dispute_id: str,
        card_bin: str,
        issuing_bank: str,
        network: str,
        reason_code: str,
        outcome: str,
        amount_inr: float,
        confidence_score: float,
        evidence_types_used: Optional[List[str]] = None
    ) -> bool:
        with self._lock:
            evidence_json = json.dumps(evidence_types_used or [])
            if self._is_postgres:
                try:
                    with self._get_pg_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                INSERT INTO dispute_outcomes (
                                    dispute_id, card_bin, issuing_bank, network,
                                    reason_code, outcome, amount_inr, confidence_score,
                                    evidence_types_used
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (dispute_id) DO UPDATE SET
                                    outcome = EXCLUDED.outcome,
                                    amount_inr = EXCLUDED.amount_inr,
                                    confidence_score = EXCLUDED.confidence_score,
                                    evidence_types_used = EXCLUDED.evidence_types_used;
                            """, (
                                dispute_id, card_bin, issuing_bank, network,
                                reason_code, outcome, amount_inr, confidence_score,
                                evidence_json
                            ))
                            return True
                except Exception as e:
                    logger.error("Error saving dispute outcome in Supabase", error=str(e))

            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                cur = conn.cursor()
                cur.execute("""
                    INSERT OR REPLACE INTO dispute_outcomes (
                        dispute_id, card_bin, issuing_bank, network,
                        reason_code, outcome, amount_inr, confidence_score,
                        evidence_types_used
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    dispute_id, card_bin, issuing_bank, network,
                    reason_code, outcome, amount_inr, confidence_score,
                    evidence_json
                ))
                conn.commit()
                conn.close()
                return True
            except Exception as e:
                logger.error("Error saving dispute outcome in SQLite", error=str(e))
                return False

    def get_bin_outcomes(self, card_bin: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            results = []
            if self._is_postgres:
                try:
                    from psycopg.rows import dict_row
                    with self._get_pg_conn(row_factory=dict_row) as conn:
                        with conn.cursor() as cur:
                            if card_bin:
                                cur.execute("SELECT * FROM dispute_outcomes WHERE card_bin = %s", (card_bin,))
                            else:
                                cur.execute("SELECT * FROM dispute_outcomes ORDER BY resolved_at DESC LIMIT 500")
                            return list(cur.fetchall())
                except Exception as e:
                    logger.error("Error fetching BIN outcomes from Supabase", error=str(e))

            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                if card_bin:
                    cur.execute("SELECT * FROM dispute_outcomes WHERE card_bin = ?", (card_bin,))
                else:
                    cur.execute("SELECT * FROM dispute_outcomes ORDER BY resolved_at DESC LIMIT 500")
                rows = cur.fetchall()
                for row in rows:
                    item = dict(row)
                    if item.get("evidence_types_used"):
                        try:
                            item["evidence_types_used"] = json.loads(item["evidence_types_used"])
                        except Exception:
                            pass
                    results.append(item)
                conn.close()
                return results
            except Exception as e:
                logger.error("Error fetching BIN outcomes from SQLite", error=str(e))
                return []

    # ------------------ TIMELINE EVENTS CRUD ------------------
    def add_timeline_event(
        self,
        dispute_id: str,
        event_type: str,
        title: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        self._ensure_initialized()
        with self._lock:
            meta_json = json.dumps(metadata or {})
            if self._is_postgres:
                try:
                    with self._get_pg_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                INSERT INTO dispute_timeline_events (
                                    dispute_id, event_type, title, description, metadata, timestamp
                                ) VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                                RETURNING id;
                            """, (dispute_id, event_type, title, description, meta_json))
                            row = cur.fetchone()
                            return row[0] if row else 1
                except Exception as e:
                    logger.error("Error adding timeline event to Supabase", dispute_id=dispute_id, error=str(e))

            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO dispute_timeline_events (
                        dispute_id, event_type, title, description, metadata, timestamp
                    ) VALUES (?, ?, ?, ?, ?, datetime('now'))
                """, (dispute_id, event_type, title, description, meta_json))
                event_id = cur.lastrowid or 1
                conn.commit()
                conn.close()
                return event_id
            except Exception as e:
                logger.error("Error adding timeline event to SQLite", dispute_id=dispute_id, error=str(e))
                return 1

    def get_timeline_events(self, dispute_id: str) -> List[Dict[str, Any]]:
        self._ensure_initialized()
        with self._lock:
            events = []
            if self._is_postgres:
                try:
                    from psycopg.rows import dict_row
                    with self._get_pg_conn(row_factory=dict_row) as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                SELECT id, dispute_id, event_type, title, description, metadata, timestamp
                                FROM dispute_timeline_events
                                WHERE dispute_id = %s
                                ORDER BY id ASC
                            """, (dispute_id,))
                            rows = cur.fetchall()
                            for r in rows:
                                meta = r.get("metadata")
                                if isinstance(meta, str):
                                    try:
                                        meta = json.loads(meta)
                                    except Exception:
                                        pass
                                ts = r.get("timestamp")
                                events.append({
                                    "id": r["id"],
                                    "dispute_id": r["dispute_id"],
                                    "event_type": r["event_type"],
                                    "title": r["title"],
                                    "description": r["description"],
                                    "metadata": meta or {},
                                    "timestamp": str(ts) if ts else ""
                                })
                            return events
                except Exception as e:
                    logger.error("Error fetching timeline events from Supabase", dispute_id=dispute_id, error=str(e))

            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, dispute_id, event_type, title, description, metadata, timestamp
                    FROM dispute_timeline_events
                    WHERE dispute_id = ?
                    ORDER BY id ASC
                """, (dispute_id,))
                rows = cur.fetchall()
                for r in rows:
                    meta = r["metadata"]
                    if isinstance(meta, str):
                        try:
                            meta = json.loads(meta)
                        except Exception:
                            meta = {}
                    events.append({
                        "id": r["id"],
                        "dispute_id": r["dispute_id"],
                        "event_type": r["event_type"],
                        "title": r["title"],
                        "description": r["description"],
                        "metadata": meta or {},
                        "timestamp": str(r["timestamp"])
                    })
                conn.close()
                return events
            except Exception as e:
                logger.error("Error fetching timeline events from SQLite", dispute_id=dispute_id, error=str(e))
                return []

    # ------------------ HITL REVIEW & ASSIGNMENT ------------------
    def assign_dispute(self, dispute_id: str, assigned_to: str) -> bool:
        self._ensure_initialized()
        with self._lock:
            dossier = self.get_dossier(dispute_id)
            if not dossier:
                return False
            dossier.assigned_to = assigned_to
            self.save_dossier(dossier)
            self.add_timeline_event(
                dispute_id=dispute_id,
                event_type="ASSIGNED",
                title="Dispute Assigned to Reviewer",
                description=f"Dispute assigned to {assigned_to} for human review and evidence preparation.",
                metadata={"assigned_to": assigned_to}
            )
            return True

    def get_hitl_queue(self) -> List[Dict[str, Any]]:
        self._ensure_initialized()
        dossiers = self.get_all_dossiers()
        queue = []
        for d in dossiers.values():
            is_hitl = (
                d.decision in ("ROUTE_TO_HITL_QUEUE", "MANUAL_REVIEW", "NEEDS_EVIDENCE") or
                d.assigned_to is not None or
                (d.confidence_score < 75.0 and d.decision != "AUTO_ACCEPT_OR_REFUND")
            )
            if is_hitl:
                p_win = (
                    d.estimated_win_probability if d.estimated_win_probability is not None
                    else (d.win_probability if d.win_probability is not None else (d.p_win or 0.0))
                )
                ev_val = (
                    d.expected_value if d.expected_value is not None
                    else (d.expected_value_inr or 0.0)
                )
                queue.append({
                    "dispute_id": d.dispute_id,
                    "payment_id": d.payment_id,
                    "amount_inr": d.amount_inr,
                    "card_network": d.card_network,
                    "reason_code": d.reason_code,
                    "confidence_score": d.confidence_score,
                    "decision": d.decision,
                    "estimated_win_probability": p_win,
                    "win_probability": p_win,
                    "expected_value_inr": ev_val,
                    "assigned_to": d.assigned_to,
                    "timestamp": d.timestamp,
                    "diagnostic_gaps": d.evaluation.diagnostic_gaps if d.evaluation else [],
                    "summary": d.summary,
                    "due_by": getattr(d, "due_by", None),
                    "priority_score": getattr(d, "priority_score", 0.0),
                    "urgency": getattr(d, "urgency", "normal"),
                    "contradictions": [c.model_dump() if hasattr(c, "model_dump") else c for c in getattr(d, "contradictions", [])],
                    "priority_factors": getattr(d, "priority_factors", {})
                })
        # Sort primarily by priority_score DESC, then timestamp DESC
        queue.sort(key=lambda x: (x.get("priority_score", 0.0), x.get("timestamp", "")), reverse=True)
        return queue


    # ------------------ DASHBOARD AGGREGATION ------------------
    def get_dashboard_summary(self) -> Dict[str, Any]:
        self._ensure_initialized()
        dossiers = list(self.get_all_dossiers().values())
        outcomes = self.get_bin_outcomes()
        
        total_disputes = len(dossiers)
        total_amount_inr = sum(d.amount_inr for d in dossiers)
        
        # Outcome tracking
        won_count = 0
        resolved_count = 0
        for out in outcomes:
            resolved_count += 1
            if out.get("outcome") == "won":
                won_count += 1
        
        if resolved_count > 0:
            win_rate = round((won_count / resolved_count) * 100, 1)
        elif total_disputes > 0:
            avg_p_win = sum((d.win_probability or d.p_win or 0.0) for d in dossiers) / total_disputes
            win_rate = round(avg_p_win * 100, 1)
        else:
            win_rate = 0.0

        recovered_amount = 0.0
        for d in dossiers:
            pw = d.win_probability if d.win_probability is not None else (d.p_win or 0.0)
            if d.decision in ("AUTO_DISPATCH", "AUTO_DISPATCHED") or pw >= 0.70:
                recovered_amount += d.amount_inr * pw
        recovered_amount_inr = round(recovered_amount, 2)

        auto_decisions = sum(1 for d in dossiers if d.decision in ("AUTO_DISPATCH", "AUTO_DISPATCHED", "AUTO_ACCEPT_OR_REFUND"))
        auto_decision_rate = round((auto_decisions / total_disputes * 100), 1) if total_disputes > 0 else 0.0
        avg_confidence = round(sum(d.confidence_score for d in dossiers) / total_disputes, 1) if total_disputes > 0 else 0.0

        status_counts: Dict[str, int] = {}
        decision_counts: Dict[str, int] = {}
        network_map: Dict[str, Dict[str, Any]] = {}
        reason_map: Dict[str, Dict[str, Any]] = {}
        hitl_count = 0

        for d in dossiers:
            decision_counts[d.decision] = decision_counts.get(d.decision, 0) + 1
            if d.decision in ("ROUTE_TO_HITL_QUEUE", "MANUAL_REVIEW") or d.assigned_to is not None:
                hitl_count += 1
            
            # Network aggregation
            net = d.card_network.lower() if d.card_network else "unknown"
            if net not in network_map:
                network_map[net] = {"count": 0, "amount": 0.0, "p_win_sum": 0.0}
            network_map[net]["count"] += 1
            network_map[net]["amount"] += d.amount_inr
            network_map[net]["p_win_sum"] += (d.win_probability or d.p_win or 0.0)

            # Reason code aggregation
            rc = d.reason_code or "unknown"
            if rc not in reason_map:
                reason_map[rc] = {"count": 0, "amount": 0.0}
            reason_map[rc]["count"] += 1
            reason_map[rc]["amount"] += d.amount_inr

        network_breakdown = [
            {
                "network": k,
                "count": v["count"],
                "total_amount_inr": round(v["amount"], 2),
                "win_rate": round((v["p_win_sum"] / v["count"]) * 100, 1) if v["count"] > 0 else 0.0
            }
            for k, v in network_map.items()
        ]

        reason_breakdown = [
            {
                "reason_code": k,
                "count": v["count"],
                "total_amount_inr": round(v["amount"], 2)
            }
            for k, v in reason_map.items()
        ]

        # Recent 10 disputes
        sorted_dossiers = sorted(dossiers, key=lambda x: x.timestamp, reverse=True)[:10]
        recent_disputes = [
            {
                "dispute_id": d.dispute_id,
                "payment_id": d.payment_id,
                "amount_inr": d.amount_inr,
                "card_network": d.card_network,
                "reason_code": d.reason_code,
                "confidence_score": d.confidence_score,
                "decision": d.decision,
                "win_probability": d.win_probability if d.win_probability is not None else d.p_win,
                "expected_value_inr": d.expected_value_inr,
                "assigned_to": d.assigned_to,
                "timestamp": d.timestamp,
                "sealed_hash": d.sealed_hash
            }
            for d in sorted_dossiers
        ]

        return {
            "total_disputes": total_disputes,
            "total_amount_inr": round(total_amount_inr, 2),
            "recovered_amount_inr": recovered_amount_inr,
            "win_rate": win_rate,
            "auto_decision_rate": auto_decision_rate,
            "avg_confidence_score": avg_confidence,
            "status_counts": status_counts,
            "decision_counts": decision_counts,
            "network_breakdown": network_breakdown,
            "reason_breakdown": reason_breakdown,
            "hitl_pending_count": hitl_count,
            "recent_disputes": recent_disputes
        }


# Module-level singleton — DatabaseManager.__new__ is now crash-safe so this
# import will always succeed even if the database is unreachable at cold start.
db = DatabaseManager()
