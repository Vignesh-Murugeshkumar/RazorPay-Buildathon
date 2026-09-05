from fastapi import APIRouter
from app.schemas.dashboard import DashboardSummary
from app.core.db import db

router = APIRouter(prefix="/dashboard", tags=["Dashboard & Analytics"])


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary():
    """
    Returns enterprise-grade dispute dashboard summary including:
    - Dispute volume & protected recovery INR
    - Win-rate percentage
    - Automation rate (Auto-dispatch vs HITL vs Auto-accept)
    - Network and reason code breakdowns
    - Pending HITL review queue counter
    - Recent disputes list
    """
    summary_data = db.get_dashboard_summary()
    return DashboardSummary(**summary_data)
