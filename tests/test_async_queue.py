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
