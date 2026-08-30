from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["units"])


def _map_conditions(
    alcaldia_id: int | None,
    sector_id: int | None,
    actividad_id: int | None,
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
):
    conditions = ["u.geom IS NOT NULL"]
    params: dict[str, int | float] = {}

    if alcaldia_id is not None:
        conditions.append("u.alcaldia_id = :alcaldia_id")
        params["alcaldia_id"] = alcaldia_id

    if sector_id is not None:
        conditions.append("a.sector_id = :sector_id")
        params["sector_id"] = sector_id

    if actividad_id is not None:
        conditions.append("u.actividad_id = :actividad_id")
        params["actividad_id"] = actividad_id

    bbox_values = (west, south, east, north)
    if all(value is not None for value in bbox_values):
        conditions.append(
            "u.geom && ST_MakeEnvelope(:west, :south, :east, :north, 4326)"
        )
        conditions.append(
            "ST_Intersects(u.geom, ST_MakeEnvelope(:west, :south, :east, :north, 4326))"
        )
        params.update({
            "west": float(west),
            "south": float(south),
            "east": float(east),
            "north": float(north),
        })

    return conditions, params


@router.get("/unidades")
def unidades_geojson(
    alcaldia_id: int | None = Query(default=None),
    sector_id: int | None = Query(default=None),
    actividad_id: int | None = Query(default=None),
    limit: int = Query(default=1200, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    conditions, params = _map_conditions(alcaldia_id, sector_id, actividad_id)
    params["limit"] = limit

    rows = db.execute(text(f"""
        SELECT
            u.id,
            u.id_denue,
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
                    "tipo": "unidad",
                    "id": r["id"],
                    "id_denue": r["id_denue"],
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


@router.get("/unidades/mapa")
def unidades_mapa(
    alcaldia_id: int | None = Query(default=None),
    sector_id: int | None = Query(default=None),
    actividad_id: int | None = Query(default=None),
    west: float | None = Query(default=None, ge=-180, le=180),
    south: float | None = Query(default=None, ge=-90, le=90),
    east: float | None = Query(default=None, ge=-180, le=180),
    north: float | None = Query(default=None, ge=-90, le=90),
    zoom: int = Query(default=10, ge=1, le=22),
    individual_limit: int = Query(default=15000, ge=1000, le=25000),
    db: Session = Depends(get_db),
):
    conditions, params = _map_conditions(
        alcaldia_id,
        sector_id,
        actividad_id,
        west,
        south,
        east,
        north,
    )
    where = " AND ".join(conditions)

    total_in_view = int(db.execute(text(f"""
        SELECT COUNT(*)
        FROM unidad_economica u
        LEFT JOIN actividad_economica a ON a.id = u.actividad_id
        WHERE {where}
    """), params).scalar() or 0)
    if zoom < 15:
        if zoom <= 9:
            cell_size = 3500       # 3.5 km
        elif zoom == 10:
            cell_size = 2200       # 2.2 km
        elif zoom == 11:
            cell_size = 1400       # 1.4 km
        elif zoom == 12:
            cell_size = 900        # 900 m
        elif zoom == 13:
            cell_size = 550        # 550 m
        else:
            cell_size = 300        # 300 m

        cluster_params = dict(params)
        cluster_params["cell_size"] = cell_size

        rows = db.execute(text(f"""
            SELECT
                FLOOR(ST_X(u.geom_utm) / :cell_size)::bigint AS grid_x,
                FLOOR(ST_Y(u.geom_utm) / :cell_size)::bigint AS grid_y,
                COUNT(*)::integer AS unidades,
                AVG(u.lat)::double precision AS lat,
                AVG(u.lon)::double precision AS lon
            FROM unidad_economica u
            LEFT JOIN actividad_economica a ON a.id = u.actividad_id
            WHERE {where}
              AND u.geom_utm IS NOT NULL
            GROUP BY grid_x, grid_y
            ORDER BY unidades DESC, grid_y, grid_x
        """), cluster_params).mappings().all()

        represented = sum(int(r["unidades"] or 0) for r in rows)
        return {
            "type": "FeatureCollection",
            "meta": {
                "mode": "clusters",
                "zoom": zoom,
                "cell_m": cell_size,
                "total_in_view": total_in_view,
                "represented": represented,
                "returned": len(rows),
                "truncated": False,
            },
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(r["lon"]), float(r["lat"])],
                    },
                    "properties": {
                        "tipo": "cluster",
                        "unidades": int(r["unidades"] or 0),
                        "cell_m": cell_size,
                    },
                }
                for r in rows
            ],
        }

    individual_params = dict(params)
    individual_params["limit"] = individual_limit + 1
    rows = db.execute(text(f"""
        SELECT
            u.id,
            u.id_denue,
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
        WHERE {where}
        ORDER BY u.id
        LIMIT :limit
    """), individual_params).mappings().all()

    truncated = len(rows) > individual_limit
    visible_rows = rows[:individual_limit]

    return {
        "type": "FeatureCollection",
        "meta": {
            "mode": "individual",
            "zoom": zoom,
            "total_in_view": total_in_view,
            "represented": len(visible_rows),
            "returned": len(visible_rows),
            "truncated": truncated,
        },
        "features": [
            {
                "type": "Feature",
                "geometry": r["geometry"],
                "properties": {
                    "tipo": "unidad",
                    "id": r["id"],
                    "id_denue": r["id_denue"],
                    "nombre": r["nombre"],
                    "codigo_scian": r["codigo_scian"],
                    "actividad": r["actividad"],
                    "sector": r["sector"],
                    "alcaldia": r["alcaldia"],
                },
            }
            for r in visible_rows
        ],
    }


@router.get("/unidades/{unidad_id}")
def unidad_detalle(unidad_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("""
        WITH target AS (
            SELECT
                u.id,
                u.id_denue,
                u.nombre,
                u.lat,
                u.lon,
                u.dist_to_border,
                u.geom_utm,

                a.codigo_scian AS codigo_scian_sistema,
                a.descripcion AS actividad_sistema,

                s.id AS sector_id,
                s.nombre AS sector,

                al.id AS alcaldia_id,
                al.nombre AS alcaldia,
                al.cvegeo AS alcaldia_cvegeo,

                d.clee,
                d.raz_social,
                d.codigo_act AS codigo_scian_denue,
                d.nombre_act AS actividad_denue,
                d.per_ocu,

                d.tipo_vial,
                d.nom_vial,
                d.numero_ext,
                d.letra_ext,
                d.numero_int,
                d.letra_int,

                d.tipo_asent,
                d.nomb_asent,
                d.cod_postal,

                d.localidad,
                d.ageb,
                d.manzana,

                d.telefono,
                d.correoelec,
                d.www,

                d.tipounieco,
                d.fecha_alta,

                CASE
                    WHEN u.geom_utm IS NOT NULL
                    THEN FLOOR(ST_X(u.geom_utm) / 300.0)::bigint
                END AS cell_x,

                CASE
                    WHEN u.geom_utm IS NOT NULL
                    THEN FLOOR(ST_Y(u.geom_utm) / 300.0)::bigint
                END AS cell_y

            FROM unidad_economica u

            LEFT JOIN actividad_economica a
                ON a.id = u.actividad_id

            LEFT JOIN sector s
                ON s.id = a.sector_id

            LEFT JOIN alcaldia al
                ON al.id = u.alcaldia_id

            LEFT JOIN denue_raw d
                ON d.id = u.id_denue

            WHERE u.id = :id
        )

        SELECT
            t.*,

            CASE
                WHEN t.cell_x IS NOT NULL
                 AND t.cell_y IS NOT NULL
                THEN CONCAT(t.cell_x, ':', t.cell_y)
            END AS cell_id,

            CASE
                WHEN t.cell_x IS NOT NULL
                 AND t.cell_y IS NOT NULL
                THEN (
                    SELECT COUNT(*)::integer

                    FROM unidad_economica ux

                    WHERE ux.geom_utm IS NOT NULL

                      AND FLOOR(
                            ST_X(ux.geom_utm) / 300.0
                          )::bigint = t.cell_x

                      AND FLOOR(
                            ST_Y(ux.geom_utm) / 300.0
                          )::bigint = t.cell_y
                )

                ELSE 0
            END AS unidades_misma_celda

        FROM target t

    """), {
        "id": unidad_id
    }).mappings().first()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Unidad económica no encontrada"
        )

    result = dict(row)
    result.pop("geom_utm", None)

    vecinos = []

    if row["cell_x"] is not None and row["cell_y"] is not None:

        vecinos = db.execute(text("""
            WITH target AS (
                SELECT
                    id,
                    geom_utm
                FROM unidad_economica
                WHERE id = :id
            )

            SELECT
                ux.id,
                ux.id_denue,
                ux.nombre,

                ax.codigo_scian,
                ax.descripcion AS actividad,

                ROUND(
                    ST_Distance(
                        ux.geom_utm,
                        t.geom_utm
                    )::numeric,
                    2
                ) AS distancia_m

            FROM unidad_economica ux

            CROSS JOIN target t

            LEFT JOIN actividad_economica ax
                ON ax.id = ux.actividad_id

            WHERE ux.id <> :id
              AND ux.geom_utm IS NOT NULL

              AND FLOOR(
                    ST_X(ux.geom_utm) / 300.0
                  )::bigint = :cell_x

              AND FLOOR(
                    ST_Y(ux.geom_utm) / 300.0
                  )::bigint = :cell_y

            ORDER BY
                ST_Distance(
                    ux.geom_utm,
                    t.geom_utm
                ),
                ux.id

            LIMIT 8

        """), {
            "id": unidad_id,
            "cell_x": row["cell_x"],
            "cell_y": row["cell_y"],
        }).mappings().all()

    result["unidades_cercanas"] = [
        dict(item)
        for item in vecinos
    ]

    result["cell_size_m"] = 300

    return result
