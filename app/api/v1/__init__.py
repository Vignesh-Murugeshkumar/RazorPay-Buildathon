from fastapi import APIRouter
from app.api.v1.endpoints.webhooks import router as webhooks_router
from app.api.v1.endpoints.pre_dispute import router as pre_dispute_router
from app.api.v1.endpoints.outcomes import router as outcomes_router
from app.api.v1.endpoints.dashboard import router as dashboard_router
from app.api.v1.endpoints.timeline import router as timeline_router
from app.api.v1.endpoints.packages import router as packages_router
from app.api.v1.endpoints.review import router as review_router
from app.api.v1.endpoints.rules import router as rules_router
from app.api.v1.endpoints.provenance import router as provenance_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(webhooks_router)
api_v1_router.include_router(pre_dispute_router)
api_v1_router.include_router(outcomes_router)
api_v1_router.include_router(dashboard_router)
api_v1_router.include_router(timeline_router)
api_v1_router.include_router(packages_router)
api_v1_router.include_router(review_router)
api_v1_router.include_router(rules_router)
api_v1_router.include_router(provenance_router)

__all__ = ["api_v1_router"]

