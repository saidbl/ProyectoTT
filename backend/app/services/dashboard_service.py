from sqlalchemy import text
from sqlalchemy.orm import Session


def _filters(
    alcaldia_id: int | None,
    sector_id: int | None,
    actividad_id: int | None,
):
    conditions: list[str] = []
    params: dict[str, int] = {}

    if alcaldia_id is not None:
        conditions.append("u.alcaldia_id = :alcaldia_id")
        params["alcaldia_id"] = alcaldia_id

    if sector_id is not None:
        conditions.append("a.sector_id = :sector_id")
        params["sector_id"] = sector_id

    if actividad_id is not None:
        conditions.append("u.actividad_id = :actividad_id")
        params["actividad_id"] = actividad_id

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where, params


def _with_percentage(rows, total: int):
    safe_total = total or 1
    result = []
    for row in rows:
        item = dict(row)
        unidades = int(item.get("unidades") or 0)
        item["unidades"] = unidades
        item["porcentaje"] = round((unidades / safe_total) * 100, 2) if total else 0.0
        result.append(item)
    return result


def get_dashboard_summary(
    db: Session,
    alcaldia_id: int | None,
    sector_id: int | None,
    actividad_id: int | None,
):
    where, params = _filters(alcaldia_id, sector_id, actividad_id)

    general = db.execute(text(f"""
        SELECT
            COUNT(*) AS total_unidades,
            COUNT(DISTINCT u.alcaldia_id) AS alcaldias_representadas,
            CURRENT_TIMESTAMP AS consulta_generada
        FROM unidad_economica u
        LEFT JOIN actividad_economica a ON a.id = u.actividad_id
        {where}
    """), params).mappings().one()

    total = int(general["total_unidades"] or 0)

    top_activities_rows = db.execute(text(f"""
        SELECT
            a.id,
            a.codigo_scian,
            a.descripcion,
            COUNT(*) AS unidades
        FROM unidad_economica u
        JOIN actividad_economica a ON a.id = u.actividad_id
        {where}
        GROUP BY a.id, a.codigo_scian, a.descripcion
        ORDER BY unidades DESC, a.codigo_scian
        LIMIT 5
    """), params).mappings().all()

    sector_rows = db.execute(text(f"""
        SELECT
            s.id,
            s.nombre,
            COUNT(*) AS unidades
        FROM unidad_economica u
        JOIN actividad_economica a ON a.id = u.actividad_id
        JOIN sector s ON s.id = a.sector_id
        {where}
        GROUP BY s.id, s.nombre
        ORDER BY unidades DESC, s.id
    """), params).mappings().all()

    alcaldia_rows = db.execute(text(f"""
        SELECT
            al.id,
            al.nombre,
            COUNT(*) AS unidades
        FROM unidad_economica u
        JOIN alcaldia al ON al.id = u.alcaldia_id
        LEFT JOIN actividad_economica a ON a.id = u.actividad_id
        {where}
        GROUP BY al.id, al.nombre
        ORDER BY unidades DESC, al.nombre
        LIMIT 10
    """), params).mappings().all()

    top_activities = _with_percentage(top_activities_rows, total)
    sector_distribution = _with_percentage(sector_rows, total)
    alcaldia_distribution = _with_percentage(alcaldia_rows, total)

    return {
        "total_unidades": total,
        "alcaldias_representadas": int(general["alcaldias_representadas"] or 0),
        "consulta_generada": general["consulta_generada"],
        "actividad_lider": top_activities[0] if top_activities else None,
        "sector_lider": sector_distribution[0] if sector_distribution else None,
        "top_actividades": top_activities,
        "distribucion_sector": sector_distribution,
        "distribucion_alcaldia": alcaldia_distribution,
    }
