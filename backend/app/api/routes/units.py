from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["units"])


@router.get("/unidades")
def unidades_geojson(
    alcaldia_id: int | None = Query(default=None),
    sector_id: int | None = Query(default=None),
    actividad_id: int | None = Query(default=None),
    limit: int = Query(default=1200, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    conditions = ["u.geom IS NOT NULL"]
    params: dict[str, int] = {"limit": limit}

    if alcaldia_id is not None:
        conditions.append("u.alcaldia_id = :alcaldia_id")
        params["alcaldia_id"] = alcaldia_id

    if sector_id is not None:
        conditions.append("a.sector_id = :sector_id")
        params["sector_id"] = sector_id

    if actividad_id is not None:
        conditions.append("u.actividad_id = :actividad_id")
        params["actividad_id"] = actividad_id

    rows = db.execute(text(f"""
        SELECT
            u.id,
            u.nombre,
            u.lat,
            u.lon,
            a.codigo_scian,
            a.descripcion AS actividad,
            s.nombre AS sector,
            al.nombre AS alcaldia,
            ST_AsGeoJSON(u.geom)::json AS geometry
        FROM unidad_economica u
        LEFT JOIN actividad_economica a ON a.id = u.actividad_id
        LEFT JOIN sector s ON s.id = a.sector_id
        LEFT JOIN alcaldia al ON al.id = u.alcaldia_id
        WHERE {' AND '.join(conditions)}
        ORDER BY u.id
        LIMIT :limit
    """), params).mappings().all()

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": r["geometry"],
                "properties": {
                    "id": r["id"],
                    "nombre": r["nombre"],
                    "codigo_scian": r["codigo_scian"],
                    "actividad": r["actividad"],
                    "sector": r["sector"],
                    "alcaldia": r["alcaldia"],
                },
            }
            for r in rows
        ],
    }


@router.get("/unidades/{unidad_id}")
def unidad_detalle(unidad_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT
            u.id, u.nombre, u.lat, u.lon, u.dist_to_border,
            a.codigo_scian, a.descripcion AS actividad,
            s.id AS sector_id, s.nombre AS sector,
            al.id AS alcaldia_id, al.nombre AS alcaldia
        FROM unidad_economica u
        LEFT JOIN actividad_economica a ON a.id = u.actividad_id
        LEFT JOIN sector s ON s.id = a.sector_id
        LEFT JOIN alcaldia al ON al.id = u.alcaldia_id
        WHERE u.id = :id
    """), {"id": unidad_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Unidad económica no encontrada")
    return dict(row)
