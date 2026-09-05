from typing import List
from fastapi import APIRouter, HTTPException
from app.schemas.timeline import TimelineEvent
from app.core.db import db

router = APIRouter(prefix="/disputes", tags=["Dispute Timeline"])


@router.get("/{dispute_id}/timeline", response_model=List[TimelineEvent])
async def get_dispute_timeline(dispute_id: str):
    """
    Returns complete chronological audit timeline of events for a dispute:
    - Webhook ingestion
    - Evidence aggregation
    - Network rule evaluation
    - Economic E[V] decisioning
    - SHA-256 seal dispatch
    - Reviewer assignments
    - Gateway outcome resolution
    """
    events = db.get_timeline_events(dispute_id)
    return [TimelineEvent(**ev) for ev in events]
