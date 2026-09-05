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
        """Utility for test suites to synchronously await background completion."""
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


def get_dispute_queue() -> DisputeProcessingQueue:
    global _queue_instance
    if _queue_instance is None:
        with _queue_lock:
            if _queue_instance is None:
                _queue_instance = InMemoryBackgroundQueue()
    return _queue_instance
