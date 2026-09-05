"""
SentinelDispute Asynchronous Processing Queue Abstraction.

Decouples ingress webhook latency from heavy AI investigation and evidence processing.
Provides Fast-ACK (HTTP 202 Accepted) capabilities conforming to Razorpay webhook timeout tolerances (<5s).
"""

from app.services.queue.queue import (
    DisputeQueueTask,
    DisputeProcessingQueue,
    InMemoryBackgroundQueue,
    get_dispute_queue,
)

__all__ = [
    "DisputeQueueTask",
    "DisputeProcessingQueue",
    "InMemoryBackgroundQueue",
    "get_dispute_queue",
]
