import os
from typing import List, Optional, Any, Union

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    from pydantic import BaseModel as BaseSettings  # fallback
    SettingsConfigDict = None


class Settings(BaseSettings):
    PROJECT_NAME: str = "SentinelDispute"
    PROJECT_VERSION: str = "1.0.0"
    API_PREFIX: str = "/api/v1"
    
    # Security & Razorpay Webhook Configuration
    RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "sentinel_secret_key_dev")
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "sentinel_secret_key_dev")
    
    # Server & CORS
    ALLOWED_ORIGINS: Any = os.getenv("ALLOWED_ORIGINS", "*")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Optional Redis / Database connections
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL", None)
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL", None)

    # Security & Traffic Thresholds
    AUTO_DISPATCH_THRESHOLD: float = 85.0
    MAX_REQUEST_BODY_BYTES: int = 2 * 1024 * 1024  # 2MB max payload size
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def is_test(self) -> bool:
        return self.ENVIRONMENT.lower() in ("test", "testing") or os.getenv("TEST_MODE", "0") == "1"

    def get_cors_origins(self) -> List[str]:
        """Parses ALLOWED_ORIGINS safely for both single strings, comma-separated lists, and asterisks."""
        if isinstance(self.ALLOWED_ORIGINS, list):
            return self.ALLOWED_ORIGINS
        if isinstance(self.ALLOWED_ORIGINS, str):
            if self.ALLOWED_ORIGINS.strip() == "*":
                # In production, wildcard with credentials is restricted; permit explicit list or wildcard
                return ["*"]
            return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]
        return ["*"]

    def validate_production_readiness(self):
        """Fail-fast check on startup if running in production with insecure defaults."""
        if self.is_production:
            secret = self.RAZORPAY_WEBHOOK_SECRET or self.WEBHOOK_SECRET
            if not secret or secret == "sentinel_secret_key_dev":
                raise ValueError(
                    "FATAL: Insecure configuration detected! Running with ENVIRONMENT=production "
                    "requires a valid, custom RAZORPAY_WEBHOOK_SECRET (cannot use 'sentinel_secret_key_dev' or empty secret)."
                )
            if len(secret) < 16:
                raise ValueError(
                    "FATAL: RAZORPAY_WEBHOOK_SECRET must be at least 16 characters in production for HMAC-SHA256 security."
                )

    if SettingsConfigDict:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore"
        )


settings = Settings()
