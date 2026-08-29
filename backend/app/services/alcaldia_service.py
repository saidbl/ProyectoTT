from sqlalchemy import text
from sqlalchemy.orm import Session


def _percentage(units: int, total: int) -> float:
    if not total:
        return 0.0
    return round((units / total) * 100, 2)


def get_alcaldia_summary(db: Session, alcaldia_id: int):
    alcaldia = db.execute(text("""
        SELECT id, nombre, cvegeo, cve_ent, cve_mun
        FROM alcaldia
        WHERE id = :alcaldia_id
    """), {"alcaldia_id": alcaldia_id}).mappings().first()

    if not alcaldia:
        return None

    general = db.execute(text("""
        SELECT
            COUNT(u.id)::integer AS total_unidades,
            COUNT(DISTINCT u.actividad_id)::integer AS actividades_distintas
        FROM unidad_economica u
        WHERE u.alcaldia_id = :alcaldia_id
    """), {"alcaldia_id": alcaldia_id}).mappings().one()

    total = int(general["total_unidades"] or 0)

    activity_rows = db.execute(text("""
        SELECT
            a.id,
            a.codigo_scian,
            a.descripcion,
            COUNT(u.id)::integer AS unidades
        FROM actividad_economica a
        LEFT JOIN unidad_economica u
          ON u.actividad_id = a.id
         AND u.alcaldia_id = :alcaldia_id
        GROUP BY a.id, a.codigo_scian, a.descripcion
        ORDER BY a.id
    """), {"alcaldia_id": alcaldia_id}).mappings().all()

    activity_distribution = []
    for row in activity_rows:
        item = dict(row)
        item["unidades"] = int(item["unidades"] or 0)
        item["porcentaje"] = _percentage(item["unidades"], total)
        activity_distribution.append(item)

    top_activities = sorted(
        (item for item in activity_distribution if item["unidades"] > 0),
        key=lambda item: (-item["unidades"], item["codigo_scian"]),
    )[:5]

    sector_rows = db.execute(text("""
        SELECT
            s.id,
            s.nombre,
            COUNT(u.id)::integer AS unidades
        FROM sector s
        LEFT JOIN actividad_economica a ON a.sector_id = s.id
        LEFT JOIN unidad_economica u
          ON u.actividad_id = a.id
         AND u.alcaldia_id = :alcaldia_id
        GROUP BY s.id, s.nombre
        ORDER BY unidades DESC, s.id
    """), {"alcaldia_id": alcaldia_id}).mappings().all()

    sectors = []
    for row in sector_rows:
        item = dict(row)
        item["unidades"] = int(item["unidades"] or 0)
        item["porcentaje"] = _percentage(item["unidades"], total)
        sectors.append(item)

    city_rows = db.execute(text("""
        SELECT
            al.id,
            al.nombre,
            COUNT(u.id)::integer AS unidades
        FROM alcaldia al
        LEFT JOIN unidad_economica u ON u.alcaldia_id = al.id
        GROUP BY al.id, al.nombre
        ORDER BY unidades DESC, al.nombre
    """)).mappings().all()

    city_distribution = []
    for position, row in enumerate(city_rows, start=1):
        item = dict(row)
        item["unidades"] = int(item["unidades"] or 0)
        item["ranking"] = position
        item["seleccionada"] = int(item["id"]) == alcaldia_id
        city_distribution.append(item)

    selected_rank = next(
        (item["ranking"] for item in city_distribution if item["seleccionada"]),
        None,
    )

    activity_leader = top_activities[0] if top_activities else None
    sector_leader = sectors[0] if sectors and sectors[0]["unidades"] > 0 else None

    return {
        "alcaldia": dict(alcaldia),
        "total_unidades": total,
        "actividades_distintas": int(general["actividades_distintas"] or 0),
        "actividad_lider": activity_leader,
        "sector_lider": sector_leader,
        "distribucion_scian": activity_distribution,
        "distribucion_sector": sectors,
        "top_actividades": top_activities,
        "distribucion_alcaldias": city_distribution,
        "ranking_cdmx": selected_rank,
    }
