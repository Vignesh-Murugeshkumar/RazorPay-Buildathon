import datetime
import json
import threading
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field
from app.core.security import compute_sha256_hash


class LedgerBlock(BaseModel):
    index: int = Field(..., description="0-indexed block sequence in the hash chain")
    previous_hash: str = Field(..., description="SHA-256 hash of block n-1 (or genesis seed for block 0)")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp")
    agent_id: str = Field(..., description="Agent or module identifier performing the state transition")
    state_transition: str = Field(..., description="Name of the transition (e.g. INGRESS, EVALUATION, SEAL_AND_DISPATCH)")
    payload_hash: str = Field(..., description="SHA-256 digest of the state payload")
    block_hash: str = Field(..., description="Computed block hash: SHA256(prev_hash || timestamp || agent_id || transition || payload_hash)")


class LedgerIntegrityReport(BaseModel):
    is_valid: bool = Field(..., description="True if the entire hash chain from genesis to head is continuous and intact")
    total_blocks: int = Field(..., description="Number of blocks currently in the ledger")
    genesis_hash: Optional[str] = Field(None, description="Hash of the genesis block")
    latest_hash: Optional[str] = Field(None, description="Hash of the latest/head block")
    discrepancy_details: Optional[str] = Field(None, description="Details if tampering is detected")
    verified_at: str = Field(..., description="Timestamp of verification execution")


class AuditLedger:
    """
    Append-Only SHA-256 Cryptographic Audit Chain Ledger.
    Ensures legal auditability and non-repudiation of dispute state transitions.
    Formula:
    h_n = SHA256(h_{n-1} || Timestamp_n || AgentID_n || StateTransition_n || PayloadHash_n)
    Genesis hash H_0 is initialized from verified webhook signature or seed.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AuditLedger, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, genesis_signature: Optional[str] = None, genesis_seed: Optional[str] = None, **kwargs):
        if getattr(self, "_initialized", False):
            return
        self.chain: List[LedgerBlock] = []
        
        # Attempt to load persistent chain from DB
        try:
            from app.core.db import db
            persisted_blocks = db.load_all_ledger_blocks()
            if persisted_blocks:
                self.chain = persisted_blocks
        except Exception:
            pass

        if not self.chain:
            seed = genesis_seed or genesis_signature
            self._init_genesis_block(seed)
        self._initialized = True

    def _init_genesis_block(self, genesis_seed: Optional[str] = None):
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        seed = genesis_seed or "GENESIS_SENTINEL_DISPUTE_RAZORPAY_SEED_2026"
        payload_hash = compute_sha256_hash(seed)
        prev_hash = "0" * 64
        agent_id = "INGRESS_GATEWAY"
        transition = "GENESIS_INIT"
        
        raw_to_hash = f"{prev_hash}||{timestamp}||{agent_id}||{transition}||{payload_hash}"
        block_hash = compute_sha256_hash(raw_to_hash)
        
        genesis_block = LedgerBlock(
            index=0,
            previous_hash=prev_hash,
            timestamp=timestamp,
            agent_id=agent_id,
            state_transition=transition,
            payload_hash=payload_hash,
            block_hash=block_hash
        )
        self.chain.append(genesis_block)
        try:
            from app.core.db import db
            db.save_ledger_block(genesis_block, {"genesis_seed": seed})
        except Exception:
            pass

    def append_block(
        self,
        agent_id: str,
        state_transition: str,
        payload: Union[Dict[str, Any], List[Any], str, bytes]
    ) -> LedgerBlock:
        with self._lock:
            if isinstance(payload, (dict, list)):
                payload_str = json.dumps(payload, sort_keys=True)
            elif isinstance(payload, bytes):
                payload_str = payload.decode("utf-8", errors="ignore")
            else:
                payload_str = str(payload)

            payload_hash = compute_sha256_hash(payload_str)
            prev_block = self.chain[-1]
            prev_hash = prev_block.block_hash
            index = len(self.chain)
            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

            raw_to_hash = f"{prev_hash}||{timestamp}||{agent_id}||{state_transition}||{payload_hash}"
            block_hash = compute_sha256_hash(raw_to_hash)

            new_block = LedgerBlock(
                index=index,
                previous_hash=prev_hash,
                timestamp=timestamp,
                agent_id=agent_id,
                state_transition=state_transition,
                payload_hash=payload_hash,
                block_hash=block_hash
            )
            self.chain.append(new_block)
            try:
                from app.core.db import db
                db.save_ledger_block(new_block, payload)
            except Exception:
                pass
            return new_block

    def get_blocks(self, limit: int = 100, offset: int = 0) -> List[LedgerBlock]:
        with self._lock:
            return list(reversed(self.chain[offset:offset + limit]))

    def get_all_blocks(self) -> List[LedgerBlock]:
        with self._lock:
            return list(self.chain)

    def get_total_count(self) -> int:
        with self._lock:
            return len(self.chain)

    def verify_integrity(self) -> LedgerIntegrityReport:
        with self._lock:
            verified_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            if not self.chain:
                return LedgerIntegrityReport(
                    is_valid=False,
                    total_blocks=0,
                    genesis_hash=None,
                    latest_hash=None,
                    discrepancy_details="Ledger chain is empty",
                    verified_at=verified_at
                )

            genesis_block = self.chain[0]
            latest_block = self.chain[-1]

            for i in range(len(self.chain)):
                curr = self.chain[i]
                
                if curr.index != i:
                    return LedgerIntegrityReport(
                        is_valid=False,
                        total_blocks=len(self.chain),
                        genesis_hash=genesis_block.block_hash,
                        latest_hash=latest_block.block_hash,
                        discrepancy_details=f"Block sequence mismatch at index {i}: expected {i}, found {curr.index}",
                        verified_at=verified_at
                    )

                if i > 0:
                    prev = self.chain[i - 1]
                    if curr.previous_hash != prev.block_hash:
                        return LedgerIntegrityReport(
                            is_valid=False,
                            total_blocks=len(self.chain),
                            genesis_hash=genesis_block.block_hash,
                            latest_hash=latest_block.block_hash,
                            discrepancy_details=f"Hash chain broken between block {i-1} ({prev.block_hash[:8]}...) and block {i} ({curr.previous_hash[:8]}...)",
                            verified_at=verified_at
                        )

                raw_to_hash = f"{curr.previous_hash}||{curr.timestamp}||{curr.agent_id}||{curr.state_transition}||{curr.payload_hash}"
                expected_hash = compute_sha256_hash(raw_to_hash)
                if curr.block_hash != expected_hash:
                    return LedgerIntegrityReport(
                        is_valid=False,
                        total_blocks=len(self.chain),
                        genesis_hash=genesis_block.block_hash,
                        latest_hash=latest_block.block_hash,
                        discrepancy_details=f"Block {i} hash altered: expected {expected_hash[:8]}..., found {curr.block_hash[:8]}...",
                        verified_at=verified_at
                    )

            return LedgerIntegrityReport(
                is_valid=True,
                total_blocks=len(self.chain),
                genesis_hash=genesis_block.block_hash,
                latest_hash=latest_block.block_hash,
                discrepancy_details=None,
                verified_at=verified_at
            )

    def reset_for_tests(self, genesis_seed: Optional[str] = None):
        with self._lock:
            self.chain = []
            try:
                from app.core.db import db
                db.clear_all_data()
            except Exception:
                pass
            self._init_genesis_block(genesis_seed)


# Global Singleton Ledger Instance
ledger = AuditLedger()
