from fastapi import APIRouter
from app.api.v1.endpoints.webhooks import router as webhooks_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(webhooks_router)

__all__ = ["api_v1_router"]
