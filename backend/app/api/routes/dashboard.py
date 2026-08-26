from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.dashboard_service import get_dashboard_summary

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/resumen")
def dashboard_resumen(
    alcaldia_id: int | None = Query(default=None),
    sector_id: int | None = Query(default=None),
    actividad_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return get_dashboard_summary(db, alcaldia_id, sector_id, actividad_id)
