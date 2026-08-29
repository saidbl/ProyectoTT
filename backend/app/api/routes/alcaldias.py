from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.alcaldia_service import get_alcaldia_summary

router = APIRouter(tags=["alcaldias"])


@router.get("/alcaldias/{alcaldia_id}/resumen")
def alcaldia_resumen(alcaldia_id: int, db: Session = Depends(get_db)):
    result = get_alcaldia_summary(db, alcaldia_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Alcaldía no encontrada")
    return result
