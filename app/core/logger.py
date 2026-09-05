import logging
import re
import sys
from typing import Any, Dict

# PII / Secret redaction patterns applied to all structured log values
_PII_PATTERNS = [
    # Card numbers: 13–19 digit sequences (with optional spaces/dashes)
    (re.compile(r'\b(\d{4})[\s-]?(\d{4})[\s-]?(\d{4})[\s-]?(\d{1,7})\b'), r'\1****\4'),
    # Authorization tokens / Bearer tokens
    (re.compile(r'(Bearer\s+)[A-Za-z0-9._\-]+', re.IGNORECASE), r'\1[REDACTED]'),
    # Webhook secrets or API keys (rzp_..., sk_..., whsec_...)
    (re.compile(r'\b(rzp_\w{4}|sk_\w{4}|whsec_\w{4})\w+\b'), r'\1****'),
    # Email addresses
    (re.compile(r'\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Z|a-z]{2,})\b'), r'[EMAIL_REDACTED]'),
]


def _redact_value(value: Any) -> str:
    """Sanitize a single value against all PII patterns."""
    s = str(value)
    for pattern, replacement in _PII_PATTERNS:
        s = pattern.sub(replacement, s)
    return s


class StructuredLoggerAdapter:
    """Fallback adapter for standard logging that supports kwargs as structured data with PII redaction."""
    def __init__(self, std_logger: logging.Logger):
        self._logger = std_logger

    def _format_msg(self, msg: str, kwargs: Dict[str, Any]) -> str:
        sanitized_msg = _redact_value(msg)
        if kwargs:
            extra_str = " ".join(f"{k}={_redact_value(v)}" for k, v in kwargs.items())
            return f"{sanitized_msg} | {extra_str}"
        return sanitized_msg

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.info(self._format_msg(msg, kwargs), *args)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.warning(self._format_msg(msg, kwargs), *args)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.error(self._format_msg(msg, kwargs), *args)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.debug(self._format_msg(msg, kwargs), *args)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.critical(self._format_msg(msg, kwargs), *args)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.exception(self._format_msg(msg, kwargs), *args)


def get_logger(name: str = "sentinel_dispute"):
    try:
        import structlog
        return structlog.get_logger(name)
    except Exception:
        std_logger = logging.getLogger(name)
        if not std_logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(
                logging.Formatter('{"timestamp":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","message":"%(message)s"}')
            )
            std_logger.addHandler(handler)
            std_logger.setLevel(logging.INFO)
        return StructuredLoggerAdapter(std_logger)


logger = get_logger("sentinel_dispute")

