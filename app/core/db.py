import os
import json
import sqlite3
import threading
from typing import List, Optional, Dict, Any
from app.schemas.dispute import Dossier, RazorpayDisputeWebhook
from app.services.ledger import LedgerBlock
from app.core.logger import get_logger

logger = get_logger("db")

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DATABASE_URL") or os.getenv("POSTGRES_URL")
# Safety: never allow destructive clear on prod Postgres via test code
# Set ENVIRONMENT=test or TEST_MODE=1 to allow clear_all_data() on SQLite only
_IS_TEST_ENV = os.getenv("ENVIRONMENT", "development").lower() in ("test", "testing") or os.getenv("TEST_MODE", "0") == "1"

# Determine optimal fallback SQLite path for local/offline dev
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH")
if not SQLITE_DB_PATH:
    if os.path.exists("/tmp") and not os.access(".", os.W_OK):
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
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DatabaseManager, cls).__new__(cls)
                cls._instance._is_postgres = False
                cls._instance._init_db()
            return cls._instance

    def _init_db(self):
        with self._lock:
            if DATABASE_URL:
                try:
                    # Clean up url if needed (e.g. postgres:// to postgresql://)
                    pg_url = DATABASE_URL
                    if pg_url.startswith("postgres://"):
                        pg_url = pg_url.replace("postgres://", "postgresql://", 1)
                    
                    import psycopg
                    from psycopg.rows import dict_row
                    
                    self._pg_url = pg_url
                    self._is_postgres = True
                    
                    # Initialize PostgreSQL / Supabase tables
                    with psycopg.connect(self._pg_url, autocommit=True) as conn:
                        with conn.cursor() as cur:
                            # 1. Dossiers Table (with JSONB)
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
                            """)
                            
                            # 2. Ledger Blocks Table
                            cur.execute("""
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
                            """)
                            
                            # 3. Processed Events / Replay Guard Table
                            cur.execute("""
                                CREATE TABLE IF NOT EXISTS processed_events (
                                    event_id VARCHAR PRIMARY KEY,
                                    signature VARCHAR,
                                    received_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                                );
                            """)

                            # 4. Customer Telemetry Table (Partitioned / Indexed Cold Storage)
                            cur.execute("""
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
                            """)

                            # 5. Pre-Dispute Interception Logs Table
                            cur.execute("""
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
                            """)

                            # 6. Dispute Resolution Outcomes Table (Closed-Loop ML)
                            cur.execute("""
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
                            """)
                            
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
                        received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
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
                conn.commit()
                conn.close()
                logger.info("SQLite database initialized successfully", db_path=SQLITE_DB_PATH)
            except Exception as e:
                logger.error("Failed to initialize SQLite database", error=str(e), db_path=SQLITE_DB_PATH)

    # ------------------ DOSSIERS CRUD ------------------
    def save_dossier(self, dossier: Dossier, raw_payload: Optional[RazorpayDisputeWebhook] = None):
        with self._lock:
            dossier_dict = dossier.model_dump()
            raw_dict = raw_payload.model_dump() if raw_payload else None
            
            if self._is_postgres:
                try:
                    import psycopg
                    with psycopg.connect(self._pg_url, autocommit=True) as conn:
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
        with self._lock:
            if self._is_postgres:
                try:
                    import psycopg
                    from psycopg.rows import dict_row
                    with psycopg.connect(self._pg_url, row_factory=dict_row) as conn:
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
        with self._lock:
            result = {}
            if self._is_postgres:
                try:
                    import psycopg
                    from psycopg.rows import dict_row
                    with psycopg.connect(self._pg_url, row_factory=dict_row) as conn:
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
        with self._lock:
            if self._is_postgres:
                try:
                    import psycopg
                    from psycopg.rows import dict_row
                    with psycopg.connect(self._pg_url, row_factory=dict_row) as conn:
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
        with self._lock:
            payload_json = json.dumps(payload_data) if payload_data else None
            
            if self._is_postgres:
                try:
                    import psycopg
                    with psycopg.connect(self._pg_url, autocommit=True) as conn:
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
        with self._lock:
            blocks = []
            if self._is_postgres:
                try:
                    import psycopg
                    from psycopg.rows import dict_row
                    with psycopg.connect(self._pg_url, row_factory=dict_row) as conn:
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
        """Used for clean test resets ONLY.

        Safety rules:
        - PostgreSQL / Supabase: TRUNCATE is only executed when ENVIRONMENT=test
          or TEST_MODE=1 is set, preventing accidental wipe of production data.
        - SQLite: Always safe to clear (local file, no prod risk).
        """
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
                        import psycopg
                        with psycopg.connect(self._pg_url, autocommit=True) as conn:
                            with conn.cursor() as cur:
                                cur.execute("TRUNCATE TABLE dossiers, ledger_blocks, processed_events;")
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
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error("Error clearing SQLite DB", error=str(e))


    # ------------------ REPLAY GUARD / NONCES ------------------
    def record_and_verify_event(self, event_id: str, signature: str) -> bool:
        """
        Records an incoming event ID / signature.
        Returns True if fresh/new, False if it was already processed (replay detected).
        """
        with self._lock:
            if self._is_postgres:
                try:
                    import psycopg
                    from psycopg.rows import dict_row
                    with psycopg.connect(self._pg_url, autocommit=True, row_factory=dict_row) as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT event_id FROM processed_events WHERE event_id = %s", (event_id,))
                            if cur.fetchone() is not None:
                                return False
                            cur.execute(
                                "INSERT INTO processed_events (event_id, signature) VALUES (%s, %s)",
                                (event_id, signature)
                            )
                            return True
                except Exception as e:
                    logger.error("Error checking processed event in Supabase", event_id=event_id, error=str(e))

            # SQLite fallback
            try:
                conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False, timeout=15.0)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT event_id FROM processed_events WHERE event_id = ?", (event_id,))
                if cur.fetchone() is not None:
                    conn.close()
                    return False
                cur.execute(
                    "INSERT INTO processed_events (event_id, signature) VALUES (?, ?)",
                    (event_id, signature)
                )
                conn.commit()
                conn.close()
                return True
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
                    import psycopg
                    with psycopg.connect(self._pg_url, autocommit=True) as conn:
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
                    import psycopg
                    with psycopg.connect(self._pg_url, autocommit=True) as conn:
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
                    import psycopg
                    with psycopg.connect(self._pg_url, autocommit=True) as conn:
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
                    import psycopg
                    from psycopg.rows import dict_row
                    with psycopg.connect(self._pg_url, autocommit=True, row_factory=dict_row) as conn:
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


db = DatabaseManager()

