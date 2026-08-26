import time
import json
import hashlib
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("redis_telemetry")


class RedisTelemetryClient:
    """
    Dual-Tier Hot Telemetry Storage Client.
    Maintains active customer identifiers with 365-day sliding TTL for sub-millisecond
    CE 3.0 / Mastercard FPT lookback queries.

    Features:
    - Redis sorted sets & hashes when REDIS_URL is configured.
    - Embedded High-Performance In-Memory Sliding Cache fallback for serverless cold-starts & local execution.
    - Indexing by card_fingerprint, customer_id, device_id, and ip_address.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis = None
        self._memory_store: Dict[str, List[Dict[str, Any]]] = {}
        self._initialized = False
        self._init_connection()

    def _init_connection(self):
        if self.redis_url:
            try:
                import redis
                self._redis = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_timeout=1.0,
                    socket_connect_timeout=1.0
                )
                self._redis.ping()
                logger.info("Connected to Redis Telemetry Hot Cache", redis_url=self.redis_url)
            except Exception as e:
                logger.warning(
                    "Redis connection failed, falling back to High-Performance Memory Cache",
                    error=str(e)
                )
                self._redis = None
        self._initialized = True

    @staticmethod
    def hash_identifier(val: str) -> str:
        """Computes deterministic SHA-256 fingerprint for PII."""
        if not val:
            return ""
        return hashlib.sha256(val.strip().lower().encode("utf-8")).hexdigest()

    def record_transaction(
        self,
        card_fingerprint: str,
        customer_id: str,
        ip_address: str,
        device_fingerprint: str,
        shipping_address: str,
        amount_inr: float,
        transaction_time: Optional[float] = None,
        transaction_id: Optional[str] = None,
        undisputed: bool = True
    ) -> Dict[str, Any]:
        """
        Ingests a customer transaction into hot telemetry cache with 365-day sliding TTL.
        """
        now = time.time()
        tx_time = transaction_time if transaction_time is not None else now
        tx_id = transaction_id or f"tx_{int(tx_time)}_{self.hash_identifier(card_fingerprint)[:8]}"
        addr_hash = self.hash_identifier(shipping_address)

        record = {
            "transaction_id": tx_id,
            "card_fingerprint": card_fingerprint,
            "customer_id": customer_id,
            "ip_address": ip_address,
            "device_fingerprint": device_fingerprint,
            "shipping_address_hash": addr_hash,
            "shipping_address": shipping_address,
            "amount_inr": amount_inr,
            "transaction_time": tx_time,
            "undisputed": undisputed,
            "recorded_at": now
        }

        # 1. Hot Redis Path
        if self._redis:
            try:
                key = f"telemetry:card:{card_fingerprint}"
                payload_str = json.dumps(record)
                pipe = self._redis.pipeline()
                pipe.zadd(key, {payload_str: tx_time})
                # Evict entries older than 365 days (365 * 86400 = 31,536,000s)
                min_valid_time = now - (365 * 86400)
                pipe.zremrangebyscore(key, "-inf", min_valid_time)
                pipe.expire(key, 365 * 86400)
                pipe.execute()
            except Exception as e:
                logger.error("Failed to write to Redis hot cache", error=str(e))

        # 2. In-Memory Fast Cache Path
        if card_fingerprint not in self._memory_store:
            self._memory_store[card_fingerprint] = []

        # Remove duplicate transaction_id if present
        self._memory_store[card_fingerprint] = [
            t for t in self._memory_store[card_fingerprint]
            if t.get("transaction_id") != tx_id
        ]
        self._memory_store[card_fingerprint].append(record)

        # Evict >365d in memory
        min_valid_time = now - (365 * 86400)
        self._memory_store[card_fingerprint] = [
            t for t in self._memory_store[card_fingerprint]
            if t.get("transaction_time", 0) >= min_valid_time
        ]

        return record

    def get_qualifying_orders(
        self,
        card_fingerprint: str,
        min_days: int = 120,
        max_days: int = 365,
        reference_time: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Sub-millisecond query for transactions matching the Visa CE 3.0 / Mastercard FPT
        lookback window [min_days, max_days] prior to reference_time.
        """
        ref = reference_time if reference_time is not None else time.time()
        start_bound = ref - (max_days * 86400)
        end_bound = ref - (min_days * 86400)

        # 1. Check Redis if available
        if self._redis:
            try:
                key = f"telemetry:card:{card_fingerprint}"
                raw_records = self._redis.zrangebyscore(key, start_bound, end_bound)
                qualifying = []
                for r in raw_records:
                    data = json.loads(r)
                    if data.get("undisputed", True):
                        data["days_ago"] = int((ref - data.get("transaction_time", ref)) / 86400)
                        qualifying.append(data)
                qualifying.sort(key=lambda x: x.get("transaction_time", 0), reverse=True)
                return qualifying
            except Exception as e:
                logger.warning("Redis query failed, checking memory fallback", error=str(e))

        # 2. In-Memory Fallback
        cached = self._memory_store.get(card_fingerprint, [])
        qualifying = []
        for item in cached:
            tx_time = item.get("transaction_time", 0)
            if start_bound <= tx_time <= end_bound and item.get("undisputed", True):
                entry = dict(item)
                entry["days_ago"] = int((ref - tx_time) / 86400)
                qualifying.append(entry)

        qualifying.sort(key=lambda x: x.get("transaction_time", 0), reverse=True)
        return qualifying

    def clear(self):
        """Clears memory store (for testing)."""
        self._memory_store.clear()


# Global Singleton
telemetry_hot_cache = RedisTelemetryClient()
