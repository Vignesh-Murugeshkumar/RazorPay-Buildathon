import os
import json
import sqlite3
import threading
from typing import List, Optional, Dict, Any
from app.schemas.dispute import Dossier, RazorpayDisputeWebhook
from app.services.ledger import LedgerBlock
from app.core.logger import get_logger

logger = get_logger("db")

# Determine optimal database path (supports local dev and serverless /tmp)
DB_PATH = os.getenv("SQLITE_DB_PATH")
if not DB_PATH:
    if os.path.exists("/tmp") and not os.access(".", os.W_OK):
        DB_PATH = "/tmp/sentinel_dispute.db"
    else:
        DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "sentinel_dispute.db")


class DatabaseManager:
    """
    Embedded SQLite persistent store for SentinelDispute.
    Provides ACID transaction safety for Dossiers, SHA-256 Ledger Blocks, and Replay Nonces.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DatabaseManager, cls).__new__(cls)
                cls._instance._init_db()
            return cls._instance

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                
                # 1. Dossiers Table
                cursor.execute("""
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
                
                # 2. Ledger Blocks Table
                cursor.execute("""
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
                
                # 3. Webhook Nonce & Replay Cache Table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS processed_events (
                        event_id TEXT PRIMARY KEY,
                        signature TEXT,
                        received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                conn.commit()
                conn.close()
                logger.info("Database initialized successfully", db_path=DB_PATH)
            except Exception as e:
                logger.error("Failed to initialize database", error=str(e), db_path=DB_PATH)

    # ------------------ DOSSIERS CRUD ------------------
    def save_dossier(self, dossier: Dossier, raw_payload: Optional[RazorpayDisputeWebhook] = None):
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                
                dossier_json = json.dumps(dossier.model_dump())
                raw_json = json.dumps(raw_payload.model_dump()) if raw_payload else None
                
                cursor.execute("""
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
                    dossier_json,
                    raw_json
                ))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error("Error saving dossier to DB", dispute_id=dossier.dispute_id, error=str(e))

    def get_dossier(self, dispute_id: str) -> Optional[Dossier]:
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT dossier_json FROM dossiers WHERE dispute_id = ?", (dispute_id,))
                row = cursor.fetchone()
                conn.close()
                if row:
                    data = json.loads(row["dossier_json"])
                    return Dossier(**data)
            except Exception as e:
                logger.error("Error fetching dossier from DB", dispute_id=dispute_id, error=str(e))
            return None

    def get_all_dossiers(self) -> Dict[str, Dossier]:
        with self._lock:
            result = {}
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT dispute_id, dossier_json FROM dossiers ORDER BY updated_at ASC")
                rows = cursor.fetchall()
                conn.close()
                for r in rows:
                    try:
                        data = json.loads(r["dossier_json"])
                        result[r["dispute_id"]] = Dossier(**data)
                    except Exception:
                        pass
            except Exception as e:
                logger.error("Error loading all dossiers from DB", error=str(e))
            return result

    def get_raw_payload(self, dispute_id: str) -> Optional[RazorpayDisputeWebhook]:
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT raw_payload_json FROM dossiers WHERE dispute_id = ?", (dispute_id,))
                row = cursor.fetchone()
                conn.close()
                if row and row["raw_payload_json"]:
                    data = json.loads(row["raw_payload_json"])
                    return RazorpayDisputeWebhook(**data)
            except Exception as e:
                logger.error("Error fetching raw payload from DB", dispute_id=dispute_id, error=str(e))
            return None

    # ------------------ LEDGER BLOCKS CRUD ------------------
    def save_ledger_block(self, block: LedgerBlock, payload_data: Any = None):
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                
                payload_json = json.dumps(payload_data) if payload_data else None
                
                cursor.execute("""
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
                logger.error("Error persisting ledger block to DB", index=block.index, error=str(e))

    def load_all_ledger_blocks(self) -> List[LedgerBlock]:
        with self._lock:
            blocks = []
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT block_index, previous_hash, timestamp, agent_id, state_transition, payload_hash, block_hash
                    FROM ledger_blocks
                    ORDER BY block_index ASC
                """)
                rows = cursor.fetchall()
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
                logger.error("Error loading ledger blocks from DB", error=str(e))
            return blocks

    def clear_all_data(self):
        """Used exclusively for clean test runs."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM dossiers")
                cursor.execute("DELETE FROM ledger_blocks")
                cursor.execute("DELETE FROM processed_events")
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error("Error clearing DB", error=str(e))

    # ------------------ REPLAY GUARD / NONCES ------------------
    def record_and_verify_event(self, event_id: str, signature: str) -> bool:
        """
        Records an incoming event ID / signature.
        Returns True if fresh/new, False if it was already processed (replay detected).
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT event_id FROM processed_events WHERE event_id = ?", (event_id,))
                if cursor.fetchone() is not None:
                    conn.close()
                    return False  # Replay detected
                
                cursor.execute(
                    "INSERT INTO processed_events (event_id, signature) VALUES (?, ?)",
                    (event_id, signature)
                )
                conn.commit()
                conn.close()
                return True
            except Exception as e:
                logger.error("Error checking processed event", event_id=event_id, error=str(e))
                return True


db = DatabaseManager()
