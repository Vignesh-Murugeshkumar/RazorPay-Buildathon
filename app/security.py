import hmac
import hashlib
from typing import Optional


def verify_razorpay_webhook(raw_body: bytes, signature_header: Optional[str], webhook_secret: str) -> bool:
    """
    Verifies the Razorpay webhook signature using constant-time HMAC-SHA256 comparison.
    Prevents timing attacks.
    """
    if not signature_header or not webhook_secret:
        return False

    try:
        expected = hmac.new(
            webhook_secret.encode('utf-8'),
            raw_body,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header.strip())
    except Exception:
        return False


def generate_razorpay_signature(raw_body: bytes, webhook_secret: str) -> str:
    """
    Generates a valid HMAC-SHA256 signature for test cases and webhook simulations.
    """
    return hmac.new(
        webhook_secret.encode('utf-8'),
        raw_body,
        hashlib.sha256
    ).hexdigest()


def compute_sha256_hash(data: bytes | str) -> str:
    """
    Computes a SHA-256 hexadecimal hash for payloads and ledger blocks.
    """
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()
