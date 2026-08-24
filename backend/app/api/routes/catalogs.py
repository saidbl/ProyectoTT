import json
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["catalogs"])


@router.get("/alcaldias")
def list_alcaldias(db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT id, nombre, cvegeo FROM alcaldia ORDER BY nombre")).mappings().all()
    return [dict(r) for r in rows]


@router.get("/alcaldias/geojson")
def alcaldias_geojson(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT id, nombre, cvegeo, ST_AsGeoJSON(geom)::json AS geometry
        FROM alcaldia
        WHERE geom IS NOT NULL
        ORDER BY nombre
    """)).mappings().all()
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": r["geometry"],
                "properties": {"id": r["id"], "nombre": r["nombre"], "cvegeo": r["cvegeo"]},
            }
            for r in rows
        ],
    }


@router.get("/sectores")
def list_sectores(db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT id, nombre FROM sector ORDER BY id")).mappings().all()
    return [dict(r) for r in rows]


@router.get("/actividades")
def list_actividades(
    sector_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    sql = "SELECT id, codigo_scian, descripcion, sector_id FROM actividad_economica"
    params = {}
    if sector_id is not None:
        sql += " WHERE sector_id = :sector_id"
        params["sector_id"] = sector_id
    sql += " ORDER BY codigo_scian"
    rows = db.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]
