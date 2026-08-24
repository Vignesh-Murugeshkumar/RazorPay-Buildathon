import logging
import sys
from typing import Any, Dict

class StructuredLoggerAdapter:
    """Fallback adapter for standard logging that supports kwargs as structured data."""
    def __init__(self, std_logger: logging.Logger):
        self._logger = std_logger

    def _format_msg(self, msg: str, kwargs: Dict[str, Any]) -> str:
        if kwargs:
            extra_str = " ".join(f"{k}={v}" for k, v in kwargs.items())
            return f"{msg} | {extra_str}"
        return msg

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.info(self._format_msg(msg, kwargs), *args)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.warning(self._format_msg(msg, kwargs), *args)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.error(self._format_msg(msg, kwargs), *args)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.debug(self._format_msg(msg, kwargs), *args)

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
