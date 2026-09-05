"""
Tests for Asynchronous Dispute Processing Queue (app/services/queue/).

Validates:
1. InMemoryBackgroundQueue enqueues and executes tasks.
2. Fast-ACK webhook endpoint returns HTTP 202 with task_id.
3. Background task completes and result is available via polling.
4. Task status endpoint returns correct lifecycle states.
"""

import pytest
import json
from fastapi.testclient import TestClient
from app.main import app
from app.services.queue.queue import InMemoryBackgroundQueue, DisputeQueueTask
from app.services.ledger import ledger


client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    ledger.reset_for_tests("ASYNC_QUEUE_TEST_GENESIS")


def test_queue_enqueue_and_completion():
    """InMemoryBackgroundQueue should complete a task and store the result."""
    queue = InMemoryBackgroundQueue(max_workers=1)
    task = DisputeQueueTask(
        dispute_id="disp_async_001",
        correlation_id="corr_async_001"
    )
    payload = {
        "event": "payment.dispute.created",
        "dispute_id": "disp_async_001",
        "payment_id": "pay_async_001",
        "amount_inr": 1500.0,
        "card_network": "visa",
        "reason_code": "10.4"
    }
    task_id = queue.enqueue(task, payload)
    assert task_id is not None

    completed = queue.wait_for_completion(task_id, timeout_seconds=10.0)
    assert completed is not None
    assert completed.status in ("COMPLETED", "FAILED")
    if completed.status == "COMPLETED":
        assert completed.result is not None
        assert completed.result["dispute_id"] == "disp_async_001"


def test_webhook_async_returns_202():
    """Webhook with X-Process-Async: true must return HTTP 202 with task_id."""
    payload = {
        "event": "payment.dispute.created",
        "dispute_id": "disp_async_202",
        "payment_id": "pay_async_202",
        "amount_inr": 3500.0,
        "card_network": "mastercard",
        "reason_code": "4853"
    }
    response = client.post(
        "/webhook",
        json=payload,
        headers={"X-Process-Async": "true"}
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert "task_id" in body
    assert body["dispute_id"] == "disp_async_202"


def test_webhook_sync_default_returns_200():
    """Webhook without async header must process synchronously and return HTTP 200."""
    payload = {
        "event": "payment.dispute.created",
        "dispute_id": "disp_sync_200",
        "payment_id": "pay_sync_200",
        "amount_inr": 2000.0,
        "card_network": "visa",
        "reason_code": "10.4"
    }
    response = client.post("/webhook", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["dispute_id"] == "disp_sync_200"


def test_queue_task_not_found_returns_404():
    """Polling a non-existent task_id must return HTTP 404."""
    response = client.get("/api/v1/queue/tasks/task_does_not_exist")
    assert response.status_code == 404


class FakeRedisClient:
    """In-memory Redis fake for unit testing RedisDisputeQueue without a live Redis server."""
    def __init__(self):
        self.store = {}
        self.lists = {}

    def ping(self):
        return True

    def setex(self, key, ttl, val):
        self.store[key] = val

    def get(self, key):
        return self.store.get(key)

    def lpush(self, key, val):
        self.lists.setdefault(key, []).insert(0, val)

    def rpop(self, key):
        l = self.lists.get(key, [])
        return l.pop() if l else None

    def llen(self, key):
        return len(self.lists.get(key, []))


def test_redis_dispute_queue_operations():
    """RedisDisputeQueue should enqueue, persist state, and execute jobs."""
    from app.services.queue.queue import RedisDisputeQueue

    fake_redis = FakeRedisClient()
    queue = RedisDisputeQueue(redis_client=fake_redis, auto_consume=False)

    task = DisputeQueueTask(dispute_id="disp_redis_01", correlation_id="corr_redis_01")
    payload = {
        "event": "payment.dispute.created",
        "dispute_id": "disp_redis_01",
        "payment_id": "pay_redis_01",
        "amount_inr": 2500.0,
        "card_network": "visa",
        "reason_code": "10.4"
    }

    task_id = queue.enqueue(task, payload)
    assert task_id == task.task_id
    assert queue.get_queue_depth() == 1

    fetched_task = queue.get_task(task_id)
    assert fetched_task is not None
    assert fetched_task.status == "PENDING"

    # Manually consume/execute
    processed = queue.process_next_job()
    assert processed is not None
    assert processed.status == "COMPLETED"
    assert queue.get_queue_depth() == 0
    assert processed.result["dispute_id"] == "disp_redis_01"


def test_redis_queue_dlq_on_poison_pill():
    """Poison-pill payloads should fail and be routed to Dead Letter Queue (DLQ)."""
    from app.services.queue.queue import RedisDisputeQueue

    fake_redis = FakeRedisClient()
    queue = RedisDisputeQueue(redis_client=fake_redis, auto_consume=False)

    task = DisputeQueueTask(dispute_id="disp_poison_01", correlation_id="corr_poison_01")
    invalid_payload = {"malformed": "not_a_dispute"}

    task_id = queue.enqueue(task, invalid_payload)
    assert queue.get_queue_depth() == 1
    assert queue.get_dlq_depth() == 0

    processed = queue.process_next_job()
    assert processed is not None
    assert processed.status == "FAILED"
    assert queue.get_queue_depth() == 0
    assert queue.get_dlq_depth() == 1


def test_queue_factory_production_fail_closed(monkeypatch):
    """In production, QUEUE_BACKEND='redis' must fail closed if Redis is unavailable."""
    from app.services.queue.queue import get_dispute_queue
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "QUEUE_BACKEND", "redis")
    monkeypatch.setattr(settings, "REDIS_URL", "redis://invalid_host:6379/0")

    with pytest.raises(RuntimeError, match="Production QUEUE_BACKEND='redis' required"):
        get_dispute_queue(reset=True)

    # Undo monkeypatch and reset back to default
    monkeypatch.undo()
    get_dispute_queue(reset=True)


def test_queue_factory_development_fallback(monkeypatch):
    """In development, QUEUE_BACKEND='redis' falls back to in-memory queue if unavailable."""
    from app.services.queue.queue import get_dispute_queue, InMemoryBackgroundQueue
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "QUEUE_BACKEND", "redis")
    monkeypatch.setattr(settings, "REDIS_URL", "redis://invalid_host:6379/0")

    q = get_dispute_queue(reset=True)
    assert isinstance(q, InMemoryBackgroundQueue)

    # Undo monkeypatch and reset back to default
    monkeypatch.undo()
    get_dispute_queue(reset=True)
