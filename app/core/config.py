import os
from typing import List, Optional

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
    ALLOWED_ORIGINS: List[str] = ["*"]
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Optional Redis / Database connections
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL", None)
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL", None)

    # Score Thresholds
    AUTO_DISPATCH_THRESHOLD: float = 85.0

    if SettingsConfigDict:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore"
        )


settings = Settings()
