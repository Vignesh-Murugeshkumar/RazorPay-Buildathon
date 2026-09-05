from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from app.core.db import db

router = APIRouter(tags=["Human-in-the-Loop Review Queue"])


class AssignDisputePayload(BaseModel):
    assigned_to: str = Field(..., description="Reviewer name, email, or analyst identifier")


@router.get("/review-queue")
async def get_review_queue():
    """
    Returns disputes queued for Human-in-the-Loop (HITL) analyst review.
    Sorted by urgency and timestamp. Includes diagnostic gaps and actionable evidence needs.
    """
    queue = db.get_hitl_queue()
    return {
        "count": len(queue),
        "disputes": queue
    }


@router.post("/disputes/{dispute_id}/assign")
async def assign_dispute_reviewer(dispute_id: str, payload: AssignDisputePayload):
    """
    Assigns a dispute to a specific analyst/reviewer and records the assignment in the audit timeline.
    """
    success = db.assign_dispute(dispute_id, payload.assigned_to)
    if not success:
        raise HTTPException(status_code=404, detail=f"Dispute {dispute_id} not found")
    
    return {
        "status": "success",
        "dispute_id": dispute_id,
        "assigned_to": payload.assigned_to,
        "message": f"Dispute {dispute_id} successfully assigned to {payload.assigned_to}"
    }
