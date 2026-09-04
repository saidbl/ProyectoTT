from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ml.inference import (
    predict_activity,
)

def _inside_cdmx(
    db: Session,
    lat: float,
    lon: float,
) -> bool:

    result = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM alcaldia a
                WHERE ST_Covers(
                    a.geom,
                    ST_SetSRID(
                        ST_MakePoint(
                            :lon,
                            :lat
                        ),
                        4326
                    )
                )
            ) AS inside;
            """
        ),
        {
            "lat": lat,
            "lon": lon,
        },
    ).scalar_one()

    return bool(result)

def _nearby_context(
    db: Session,
    lat: float,
    lon: float,
    radius_m: int = 800,
):

    row = db.execute(
        text(
            """
            WITH punto AS (
                SELECT
                    ST_Transform(
                        ST_SetSRID(
                            ST_MakePoint(
                                :lon,
                                :lat
                            ),
                            4326
                        ),
                        32614
                    ) AS geom
            )

            SELECT
                COUNT(*) AS nearby_units,

                (
                    SELECT
                        a2.descripcion

                    FROM
                        unidad_economica u2

                    JOIN actividad_economica a2
                        ON a2.id = u2.actividad_id,

                        punto p2

                    WHERE
                        u2.geom_utm IS NOT NULL

                        AND ST_DWithin(
                            u2.geom_utm,
                            p2.geom,
                            :radius
                        )

                    GROUP BY
                        a2.id,
                        a2.descripcion

                    ORDER BY
                        COUNT(*) DESC

                    LIMIT 1
                ) AS dominant_activity

            FROM
                unidad_economica u,
                punto p

            WHERE
                u.geom_utm IS NOT NULL

                AND ST_DWithin(
                    u.geom_utm,
                    p.geom,
                    :radius
                );
            """
        ),
        {
            "lat": lat,
            "lon": lon,
            "radius": radius_m,
        },
    ).mappings().one()

    return dict(row)

def _activity_catalog(
    db: Session,
):

    rows = db.execute(
        text(
            """
            SELECT
                id,
                codigo_scian,
                descripcion

            FROM actividad_economica

            ORDER BY id;
            """
        )
    ).mappings().all()

    return {
        int(row["id"]): {
            "scian": row["codigo_scian"],
            "description": row["descripcion"],
        }
        for row in rows
    }

def _decorate_prediction(
    raw_item: dict,
    catalog: dict,
    rare_activity_ids: list[int],
):

    activity_id = int(
        raw_item["activity_id"]
    )

    operational_class = int(
        raw_item["operational_class"]
    )


    if activity_id == -1:

        return {
            "operational_class":
                operational_class,

            "activity_id":
                None,

            "scian":
                None,

            "activity":
                "Otras actividades económicas",

            "probability":
                float(
                    raw_item["probability"]
                ),

            "decision_score":
                float(
                    raw_item["decision_score"]
                ),

            "grouped":
                True,

            "included_activity_ids":
                [
                    int(value)
                    for value
                    in rare_activity_ids
                ],
        }

    activity = catalog.get(
        activity_id
    )

    if activity is None:

        raise RuntimeError(
            "El modelo devolvió una actividad "
            "que no existe en el catálogo: "
            f"{activity_id}"
        )

    return {
        "operational_class":
            operational_class,

        "activity_id":
            activity_id,

        "scian":
            str(
                activity["scian"]
            ),

        "activity":
            str(
                activity["description"]
            ),

        "probability":
            float(
                raw_item["probability"]
            ),

        "decision_score":
            float(
                raw_item["decision_score"]
            ),

        "grouped":
            False,

        "included_activity_ids":
            [],
    }

def _outside_cdmx_response(
    lat: float,
    lon: float,
):

    return {
        "status":
            "outside_cdmx",

        "message":
            (
                "El punto seleccionado se encuentra "
                "fuera de la Ciudad de México."
            ),

        "lat":
            lat,

        "lon":
            lon,

        "nearby_units":
            0,

        "dominant_activity":
            None,

        "confidence":
            None,

        "model_version":
            None,

        "cell":
            None,

        "prediction":
            None,

        "ambiguity":
            None,

        "top3":
            [],
    }

def _model_not_loaded_response(
    *,
    lat: float,
    lon: float,
    context: dict,
    error: Exception,
):

    return {
        "status":
            "model_not_loaded",

        "message":
            str(error),

        "lat":
            lat,

        "lon":
            lon,

        "nearby_units":
            int(
                context.get(
                    "nearby_units"
                )
                or 0
            ),

        "dominant_activity":
            context.get(
                "dominant_activity"
            ),

        "confidence":
            None,

        "model_version":
            None,

        "cell":
            None,

        "prediction":
            None,

        "ambiguity":
            None,

        "top3":
            [],
    }

def predict(
    db: Session,
    lat: float,
    lon: float,
):

    if not _inside_cdmx(
        db,
        lat,
        lon,
    ):

        return _outside_cdmx_response(
            lat,
            lon,
        )

    context = _nearby_context(
        db,
        lat,
        lon,
    )

    try:

        result = predict_activity(
            lat,
            lon,
        )

    except FileNotFoundError as exc:

        return _model_not_loaded_response(
            lat=lat,
            lon=lon,
            context=context,
            error=exc,
        )

    catalog = _activity_catalog(
        db
    )

    rare_activity_ids = [
        int(value)
        for value
        in result[
            "rare_activity_ids"
        ]
    ]

    raw_prediction = {
        "operational_class":
            result[
                "operational_class"
            ],

        "activity_id":
            result[
                "activity_id"
            ],

        "probability":
            result[
                "probability"
            ],

        "decision_score":
            result[
                "decision_score"
            ],
    }

    prediction = _decorate_prediction(
        raw_prediction,
        catalog,
        rare_activity_ids,
    )


    top3 = [
        _decorate_prediction(
            item,
            catalog,
            rare_activity_ids,
        )
        for item in result[
            "top3"
        ]
    ]

    ambiguity = result[
        "ambiguity"
    ]


    if ambiguity[
        "ambiguous"
    ]:

        message = (
            "Zona altamente ambigua. "
            "La evidencia del modelo no permite "
            "seleccionar una actividad económica "
            "individual con suficiente claridad. "
            "Consulta el Top-3 de alternativas."
        )

    elif result[
        "occupied"
    ]:

        message = (
            "Predicción aceptada por la política "
            "de confianza del modelo económico "
            "espacial de 422 variables."
        )

    else:

        message = (
            "Predicción aceptada utilizando contexto "
            "económico vecino. La celda de 300 m "
            "seleccionada no contiene unidades DENUE "
            "en el contexto utilizado por el modelo."
        )

    return {
        "status":
            "ok",

        "message":
            message,

        "lat":
            lat,

        "lon":
            lon,

        "nearby_units":
            int(
                context[
                    "nearby_units"
                ]
                or 0
            ),

        "dominant_activity":
            context[
                "dominant_activity"
            ],

        "confidence":
            None,

        "model_version":
            result[
                "model_version"
            ],

        # ----------------------------------------------------
        # CELDA ESPACIAL
        # ----------------------------------------------------

        "cell":
            {
                "x":
                    result[
                        "cell_x"
                    ],

                "y":
                    result[
                        "cell_y"
                    ],

                "size_m":
                    result[
                        "cell_size"
                    ],

                "occupied":
                    result[
                        "occupied"
                    ],
            },

        "prediction":
            prediction,


        "ambiguity":
            ambiguity,

        "top3":
            top3,
    }