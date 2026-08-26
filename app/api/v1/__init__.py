from fastapi import APIRouter
from app.api.v1.endpoints.webhooks import router as webhooks_router
from app.api.v1.endpoints.pre_dispute import router as pre_dispute_router
from app.api.v1.endpoints.outcomes import router as outcomes_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(webhooks_router)
api_v1_router.include_router(pre_dispute_router)
api_v1_router.include_router(outcomes_router)

__all__ = ["api_v1_router"]

