from fastapi import APIRouter, HTTPException, Response
from app.core.db import db
from app.services.representment_package import representment_package_generator

router = APIRouter(prefix="/disputes", tags=["Representment Packages"])


@router.get("/{dispute_id}/representment-package")
async def get_representment_package_json(dispute_id: str):
    """
    Returns full automated representment package in structured JSON format:
    - Cover page metadata
    - Transaction & dispute identifiers
    - Evidence intelligence breakdown (3DS, carrier, GPS, logs, history)
    - Rebuttal argument
    - Expected Value economic metrics
    - SHA-256 seal verification
    """
    dossier = db.get_dossier(dispute_id)
    if not dossier:
        raise HTTPException(status_code=404, detail="Dispute dossier not found")
    
    return representment_package_generator.generate_package_json(dossier)


@router.get("/{dispute_id}/representment-pdf")
async def get_representment_package_pdf(dispute_id: str):
    """
    Generates and returns an audit-grade bank-ready PDF representment packet.
    """
    dossier = db.get_dossier(dispute_id)
    if not dossier:
        raise HTTPException(status_code=404, detail="Dispute dossier not found")
    
    try:
        pdf_bytes = representment_package_generator.generate_package_pdf(dossier)
    except RuntimeError as err:
        raise HTTPException(status_code=501, detail=str(err))
    filename = f"representment_{dispute_id}.pdf"
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/pdf"
        }
    )
