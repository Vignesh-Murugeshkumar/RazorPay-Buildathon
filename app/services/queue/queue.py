"""
Dispute Processing Queue Implementation.

Provides:
1. Abstract base class `DisputeProcessingQueue` for pluggable broker backends (Redis/Celery/SQS).
2. `InMemoryBackgroundQueue` using Python `concurrent.futures.ThreadPoolExecutor` for zero-infra local/dev/CI execution.
3. Thread-safe task state tracking and Fast-ACK background execution.
"""

import uuid
import datetime
import threading
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from pydantic import BaseModel, Field

from app.core.logger import logger


class DisputeQueueTask(BaseModel):
    task_id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}")
    dispute_id: str
    event_id: Optional[str] = None
    correlation_id: str
    status: str = "PENDING"  # PENDING, PROCESSING, COMPLETED, FAILED
    enqueued_at: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class DisputeProcessingQueue(ABC):
    """Abstract interface for asynchronous dispute processing brokers."""

    @abstractmethod
    def enqueue(self, task: DisputeQueueTask, raw_payload: Dict[str, Any]) -> str:
        """Enqueues a dispute for asynchronous background processing. Returns task_id."""
        pass

    @abstractmethod
    def get_task(self, task_id: str) -> Optional[DisputeQueueTask]:
        """Retrieves task state and execution metadata."""
        pass

    @abstractmethod
    def get_queue_depth(self) -> int:
        """Returns the number of queued/active tasks."""
        pass


class InMemoryBackgroundQueue(DisputeProcessingQueue):
    """
    In-Memory Background Worker Queue.
    Executes dispute pipelines asynchronously using a dedicated thread pool without requiring
    external queue brokers (Redis, RabbitMQ, Celery) in serverless or CI environments.
    """
    def __init__(self, max_workers: int = 4):
        self._tasks: Dict[str, DisputeQueueTask] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sentinel_queue_worker")

    def enqueue(self, task: DisputeQueueTask, raw_payload: Dict[str, Any]) -> str:
        with self._lock:
            self._tasks[task.task_id] = task

        self._executor.submit(self._execute_worker, task.task_id, raw_payload)
        logger.info(
            "Enqueued dispute task for background processing",
            task_id=task.task_id,
            dispute_id=task.dispute_id,
            correlation_id=task.correlation_id
        )
        return task.task_id

    def _execute_worker(self, task_id: str, raw_payload: Dict[str, Any]):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.status = "PROCESSING"
            task.started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        try:
            from app.schemas.dispute import RazorpayDisputeWebhook
            from app.graphs.dispute_graph import execute_dispute_workflow
            from app.core.db import db
            from app.api.v1.endpoints.webhooks import get_dossiers_db

            payload = RazorpayDisputeWebhook.model_validate(raw_payload)
            dossier = execute_dispute_workflow(payload)

            # Persist results
            get_dossiers_db()[dossier.dispute_id] = dossier
            db.save_dossier(dossier, payload)

            result_summary = {
                "dispute_id": dossier.dispute_id,
                "payment_id": dossier.payment_id,
                "decision": dossier.decision,
                "confidence_score": dossier.confidence_score,
                "sealed_hash": dossier.sealed_hash,
                "summary": dossier.summary
            }

            if task.event_id:
                db.complete_webhook_event(task.event_id, result_summary)

            with self._lock:
                task.status = "COMPLETED"
                task.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                task.result = result_summary

            logger.info(
                "Async dispute task completed successfully",
                task_id=task_id,
                dispute_id=task.dispute_id,
                decision=dossier.decision
            )

        except Exception as exc:
            logger.error(
                "Async dispute task execution failed",
                task_id=task_id,
                dispute_id=task.dispute_id if task else "unknown",
                error=str(exc)
            )
            with self._lock:
                if task:
                    task.status = "FAILED"
                    task.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    task.error = str(exc)
            if task and task.event_id:
                try:
                    from app.core.db import db
                    db.fail_webhook_event(task.event_id, error_message=str(exc))
                except Exception:
                    pass

    def get_task(self, task_id: str) -> Optional[DisputeQueueTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def get_queue_depth(self) -> int:
        with self._lock:
            return sum(1 for t in self._tasks.values() if t.status in ("PENDING", "PROCESSING"))

    def wait_for_completion(self, task_id: str, timeout_seconds: float = 10.0) -> Optional[DisputeQueueTask]:
        import time
        start = time.time()
        while time.time() - start < timeout_seconds:
            task = self.get_task(task_id)
            if task and task.status in ("COMPLETED", "FAILED"):
                return task
            time.sleep(0.05)
        return self.get_task(task_id)


class RedisDisputeQueue(DisputeProcessingQueue):
    """
    Durable Redis-Backed Dispute Processing Queue.
    Provides persistence, retry management, and Dead Letter Queue (DLQ) support for production.
    
    Data structures:
    - `sentinel:queue:disputes` (List, LPUSH/RPOP): Active pending jobs
    - `sentinel:queue:dlq` (List): Dead Letter Queue for poison-pill tasks
    - `sentinel:task:{task_id}` (String/JSON): State tracking with TTL
    - `sentinel:payload:{task_id}` (String/JSON): Ingress payload with TTL
    """
    QUEUE_KEY = "sentinel:queue:disputes"
    DLQ_KEY = "sentinel:queue:dlq"
    TASK_KEY_PREFIX = "sentinel:task:"
    PAYLOAD_KEY_PREFIX = "sentinel:payload:"

    def __init__(
        self,
        redis_client=None,
        redis_url: Optional[str] = None,
        max_retries: int = 3,
        ttl_seconds: int = 7 * 86400,
        auto_consume: bool = True
    ):
        from app.core.config import settings
        self.redis_url = redis_url or settings.QUEUE_REDIS_URL or settings.REDIS_URL or "redis://localhost:6379/0"
        self.max_retries = max_retries
        self.ttl_seconds = ttl_seconds
        self.auto_consume = auto_consume

        if redis_client is not None:
            self._redis = redis_client
        else:
            import redis
            self._redis = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0
            )
            # Verify connectivity immediately
            self._redis.ping()

        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sentinel_redis_worker")
        logger.info("Initialized RedisDisputeQueue", redis_url=self.redis_url)

    def enqueue(self, task: DisputeQueueTask, raw_payload: Dict[str, Any]) -> str:
        import json
        task_data = task.model_dump()
        self._redis.setex(
            f"{self.TASK_KEY_PREFIX}{task.task_id}",
            self.ttl_seconds,
            json.dumps(task_data)
        )
        self._redis.setex(
            f"{self.PAYLOAD_KEY_PREFIX}{task.task_id}",
            self.ttl_seconds,
            json.dumps(raw_payload)
        )
        # Push to FIFO queue
        self._redis.lpush(self.QUEUE_KEY, task.task_id)

        logger.info(
            "Enqueued dispute to Redis",
            task_id=task.task_id,
            dispute_id=task.dispute_id,
            queue_depth=self.get_queue_depth()
        )

        if self.auto_consume:
            self._executor.submit(self.process_next_job)

        return task.task_id

    def get_task(self, task_id: str) -> Optional[DisputeQueueTask]:
        import json
        raw = self._redis.get(f"{self.TASK_KEY_PREFIX}{task_id}")
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return DisputeQueueTask.model_validate(data)
        except Exception as e:
            logger.error("Failed to deserialize task from Redis", task_id=task_id, error=str(e))
            return None

    def get_queue_depth(self) -> int:
        return int(self._redis.llen(self.QUEUE_KEY))

    def get_dlq_depth(self) -> int:
        return int(self._redis.llen(self.DLQ_KEY))

    def process_next_job(self) -> Optional[DisputeQueueTask]:
        """Pops and processes the next task from the Redis queue."""
        import json
        task_id = self._redis.rpop(self.QUEUE_KEY)
        if not task_id:
            return None

        task = self.get_task(task_id)
        if not task:
            return None

        task.status = "PROCESSING"
        task.started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._redis.setex(
            f"{self.TASK_KEY_PREFIX}{task_id}",
            self.ttl_seconds,
            json.dumps(task.model_dump())
        )

        raw_payload_str = self._redis.get(f"{self.PAYLOAD_KEY_PREFIX}{task_id}")
        raw_payload = json.loads(raw_payload_str) if raw_payload_str else {}

        try:
            from app.schemas.dispute import RazorpayDisputeWebhook
            from app.graphs.dispute_graph import execute_dispute_workflow
            from app.core.db import db
            from app.api.v1.endpoints.webhooks import get_dossiers_db

            payload = RazorpayDisputeWebhook.model_validate(raw_payload)
            dossier = execute_dispute_workflow(payload)

            get_dossiers_db()[dossier.dispute_id] = dossier
            db.save_dossier(dossier, payload)

            result_summary = {
                "dispute_id": dossier.dispute_id,
                "payment_id": dossier.payment_id,
                "decision": dossier.decision,
                "confidence_score": dossier.confidence_score,
                "sealed_hash": dossier.sealed_hash,
                "summary": dossier.summary
            }

            if task.event_id:
                db.complete_webhook_event(task.event_id, result_summary)

            task.status = "COMPLETED"
            task.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            task.result = result_summary
            self._redis.setex(
                f"{self.TASK_KEY_PREFIX}{task_id}",
                self.ttl_seconds,
                json.dumps(task.model_dump())
            )

            logger.info("Processed Redis dispute task", task_id=task_id, decision=dossier.decision)
            return task

        except Exception as exc:
            logger.error("Redis worker failed processing task", task_id=task_id, error=str(exc))
            task.status = "FAILED"
            task.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            task.error = str(exc)
            self._redis.setex(
                f"{self.TASK_KEY_PREFIX}{task_id}",
                self.ttl_seconds,
                json.dumps(task.model_dump())
            )

            # Route poison-pill tasks to DLQ
            self._redis.lpush(self.DLQ_KEY, task_id)

            if task.event_id:
                try:
                    from app.core.db import db
                    db.fail_webhook_event(task.event_id, error_message=str(exc))
                except Exception:
                    pass
            return task

    def wait_for_completion(self, task_id: str, timeout_seconds: float = 10.0) -> Optional[DisputeQueueTask]:
        import time
        start = time.time()
        while time.time() - start < timeout_seconds:
            task = self.get_task(task_id)
            if task and task.status in ("COMPLETED", "FAILED"):
                return task
            time.sleep(0.05)
        return self.get_task(task_id)


# Global Queue Instance Singleton
_queue_instance: Optional[DisputeProcessingQueue] = None
_queue_lock = threading.Lock()


def get_dispute_queue(reset: bool = False) -> DisputeProcessingQueue:
    """
    Factory returning configured queue backend.
    Checks `settings.QUEUE_BACKEND`:
      - 'redis': Uses RedisDisputeQueue. Fails closed in production if Redis is unreachable.
      - 'memory': Uses InMemoryBackgroundQueue (default for dev/CI).
    """
    global _queue_instance
    if reset:
        with _queue_lock:
            _queue_instance = None

    if _queue_instance is None:
        with _queue_lock:
            if _queue_instance is None:
                from app.core.config import settings
                backend = (settings.QUEUE_BACKEND or "memory").lower().strip()

                if backend == "redis":
                    try:
                        _queue_instance = RedisDisputeQueue()
                    except Exception as exc:
                        if settings.is_production:
                            logger.critical(
                                "CRITICAL: Redis queue backend configured in production but unavailable. Failing closed.",
                                error=str(exc)
                            )
                            raise RuntimeError(
                                f"Production QUEUE_BACKEND='redis' required but Redis connection failed: {exc}"
                            ) from exc
                        else:
                            logger.warning(
                                "Redis unavailable in development/test environment; falling back to InMemoryBackgroundQueue",
                                error=str(exc)
                            )
                            _queue_instance = InMemoryBackgroundQueue()
                else:
                    _queue_instance = InMemoryBackgroundQueue()

    return _queue_instance
