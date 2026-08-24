from sqlalchemy import text
from sqlalchemy.orm import Session


def _filters(alcaldia_id: int | None, sector_id: int | None):
    conditions: list[str] = []
    params: dict[str, int] = {}
    if alcaldia_id is not None:
        conditions.append("u.alcaldia_id = :alcaldia_id")
        params["alcaldia_id"] = alcaldia_id
    if sector_id is not None:
        conditions.append("a.sector_id = :sector_id")
        params["sector_id"] = sector_id
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where, params


def get_dashboard_summary(db: Session, alcaldia_id: int | None, sector_id: int | None):
    where, params = _filters(alcaldia_id, sector_id)

    total = db.execute(text(f"""
        SELECT COUNT(*) AS total
        FROM unidad_economica u
        LEFT JOIN actividad_economica a ON a.id = u.actividad_id
        {where}
    """), params).scalar_one()

    top_activities = db.execute(text(f"""
        SELECT a.codigo_scian, a.descripcion, COUNT(*) AS unidades
        FROM unidad_economica u
        JOIN actividad_economica a ON a.id = u.actividad_id
        {where}
        GROUP BY a.id, a.codigo_scian, a.descripcion
        ORDER BY unidades DESC
        LIMIT 5
    """), params).mappings().all()

    sector_distribution = db.execute(text(f"""
        SELECT s.id, s.nombre, COUNT(*) AS unidades
        FROM unidad_economica u
        JOIN actividad_economica a ON a.id = u.actividad_id
        JOIN sector s ON s.id = a.sector_id
        {where}
        GROUP BY s.id, s.nombre
        ORDER BY unidades DESC
    """), params).mappings().all()

    alcaldia_distribution = db.execute(text(f"""
        SELECT al.id, al.nombre, COUNT(*) AS unidades
        FROM unidad_economica u
        JOIN alcaldia al ON al.id = u.alcaldia_id
        LEFT JOIN actividad_economica a ON a.id = u.actividad_id
        {where}
        GROUP BY al.id, al.nombre
        ORDER BY unidades DESC
        LIMIT 16
    """), params).mappings().all()

    return {
        "total_unidades": total,
        "top_actividades": [dict(r) for r in top_activities],
        "distribucion_sector": [dict(r) for r in sector_distribution],
        "distribucion_alcaldia": [dict(r) for r in alcaldia_distribution],
    }
