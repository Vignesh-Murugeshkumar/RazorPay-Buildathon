import datetime
import json
import threading
from typing import List, Optional, Dict, Any
from app.models.ledger import LedgerBlock, LedgerIntegrityReport
from app.security import compute_sha256_hash


class AuditLedger:
    """
    Cryptographic Append-Only SHA-256 Hash Chain Ledger.
    Ensures legal auditability and tamper-evident logging of dispute state transitions.
    Formula:
    h_n = SHA256(h_{n-1} || Timestamp_n || AgentID_n || StateTransition_n || PayloadHash_n)
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AuditLedger, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, genesis_seed: str = "GENESIS_SENTINEL_DISPUTE_RAZORPAY_SEED_2026"):
        if getattr(self, "_initialized", False):
            return
        self.chain: List[LedgerBlock] = []
        self._genesis_seed = genesis_seed
        self._init_genesis_block()
        self._initialized = True

    def _init_genesis_block(self):
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload_hash = compute_sha256_hash(self._genesis_seed)
        prev_hash = "0" * 64
        agent_id = "SYSTEM_INITIALIZER"
        transition = "GENESIS_BLOCK"
        
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

    def append_block(
        self,
        agent_id: str,
        state_transition: str,
        payload: Dict[str, Any] | str | bytes
    ) -> LedgerBlock:
        with self._lock:
            if isinstance(payload, (dict, list)):
                payload_str = json.dumps(payload, sort_keys=True)
            elif isinstance(payload, bytes):
                payload_str = payload.decode('utf-8', errors='ignore')
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
        """
        Iterates from block 0 to block N to verify hash continuity and detect any tampering.
        """
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
                
                # Check index sequence
                if curr.index != i:
                    return LedgerIntegrityReport(
                        is_valid=False,
                        total_blocks=len(self.chain),
                        genesis_hash=genesis_block.block_hash,
                        latest_hash=latest_block.block_hash,
                        discrepancy_details=f"Block sequence mismatch at index {i}: expected {i}, found {curr.index}",
                        verified_at=verified_at
                    )

                # Check previous hash pointer
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

                # Recalculate block hash
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

    def reset_for_tests(self):
        """Testing utility to clear and re-initialize genesis."""
        with self._lock:
            self.chain = []
            self._init_genesis_block()


# Global singleton instance
ledger = AuditLedger()
