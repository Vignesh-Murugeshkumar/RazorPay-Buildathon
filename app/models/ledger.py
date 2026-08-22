from typing import List, Optional
from pydantic import BaseModel, Field


class LedgerBlock(BaseModel):
    index: int = Field(..., description="0-indexed block sequence in the hash chain")
    previous_hash: str = Field(..., description="SHA-256 hash of block n-1 (or genesis seed for block 0)")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp")
    agent_id: str = Field(..., description="Agent or module identifier performing the state transition")
    state_transition: str = Field(..., description="Name of the transition (e.g. INGESTION, EVALUATION, SEAL_AND_DISPATCH)")
    payload_hash: str = Field(..., description="SHA-256 digest of the state payload")
    block_hash: str = Field(..., description="Computed block hash: SHA256(prev_hash || timestamp || agent_id || transition || payload_hash)")


class LedgerIntegrityReport(BaseModel):
    is_valid: bool = Field(..., description="True if the entire hash chain from genesis to head is continuous and intact")
    total_blocks: int = Field(..., description="Number of blocks currently in the ledger")
    genesis_hash: Optional[str] = Field(None, description="Hash of the genesis block")
    latest_hash: Optional[str] = Field(None, description="Hash of the latest/head block")
    discrepancy_details: Optional[str] = Field(None, description="Details if tampering is detected")
    verified_at: str = Field(..., description="Timestamp of verification execution")
