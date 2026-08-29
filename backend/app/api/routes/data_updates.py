from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["data-updates"])


@router.get("/datos/estado-actualizacion")
def data_update_status(db: Session = Depends(get_db)):
    exists = db.execute(
        text("SELECT to_regclass('public.denue_sync_state') IS NOT NULL")
    ).scalar_one()
    if not exists:
        return {
            "source": "DENUE_CDMX",
            "status": "not_initialized",
            "last_attempt_at": None,
            "last_success_at": None,
            "last_records": None,
        }

    row = db.execute(
        text(
            """
            SELECT source, last_attempt_at, last_success_at, last_status, last_records
            FROM denue_sync_state
            WHERE source = 'DENUE_CDMX'
            """
        )
    ).mappings().first()

    if not row:
        return {
            "source": "DENUE_CDMX",
            "status": "pending",
            "last_attempt_at": None,
            "last_success_at": None,
            "last_records": None,
        }

    return {
        "source": row["source"],
        "status": row["last_status"],
        "last_attempt_at": row["last_attempt_at"],
        "last_success_at": row["last_success_at"],
        "last_records": row["last_records"],
    }
