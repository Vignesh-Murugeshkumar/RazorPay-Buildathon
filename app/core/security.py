import time
import hmac
import hashlib
from typing import Optional, Union


def verify_razorpay_webhook(
    raw_body: bytes,
    signature_header: Optional[str],
    webhook_secret: str
) -> bool:
    """
    Verifies the Razorpay webhook signature using constant-time HMAC-SHA256 comparison.
    Prevents timing attacks.
    """
    if not signature_header or not webhook_secret:
        return False

    try:
        expected_signature = hmac.new(
            key=webhook_secret.encode("utf-8"),
            msg=raw_body,
            digestmod=hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected_signature, signature_header.strip())
    except Exception:
        return False


def validate_webhook_timestamp(
    timestamp: Union[int, float, str],
    tolerance_seconds: int = 300
) -> bool:
    """
    Replay attack prevention: checks if the webhook timestamp is within the tolerance window (default 300s / 5 min).
    """
    try:
        ts = float(timestamp)
        now = time.time()
        return abs(now - ts) <= tolerance_seconds
    except (ValueError, TypeError):
        return False


def generate_razorpay_signature(raw_body: bytes, webhook_secret: str) -> str:
    """
    Generates a valid HMAC-SHA256 signature for test cases and webhook simulations.
    """
    return hmac.new(
        key=webhook_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest()


def compute_sha256_hash(data: Union[bytes, str]) -> str:
    """
    Computes a SHA-256 hexadecimal digest for payloads, state hashes, and ledger blocks.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()
