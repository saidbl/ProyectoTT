from pathlib import Path
import joblib
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings

settings = get_settings()


def _nearby_context(db: Session, lat: float, lon: float, radius_m: int = 800):
    row = db.execute(text("""
        WITH punto AS (
            SELECT ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 32614) AS geom
        )
        SELECT
            COUNT(*) AS nearby_units,
            (
                SELECT a2.descripcion
                FROM unidad_economica u2
                JOIN actividad_economica a2 ON a2.id = u2.actividad_id, punto p2
                WHERE u2.geom_utm IS NOT NULL
                  AND ST_DWithin(u2.geom_utm, p2.geom, :radius)
                GROUP BY a2.id, a2.descripcion
                ORDER BY COUNT(*) DESC
                LIMIT 1
            ) AS dominant_activity
        FROM unidad_economica u, punto p
        WHERE u.geom_utm IS NOT NULL
          AND ST_DWithin(u.geom_utm, p.geom, :radius)
    """), {"lat": lat, "lon": lon, "radius": radius_m}).mappings().one()
    return dict(row)


def predict(db: Session, lat: float, lon: float):
    context = _nearby_context(db, lat, lon)
    model_file = Path(settings.model_path)

    if not model_file.exists():
        return {
            "status": "model_not_loaded",
            "message": "La API y el análisis espacial ya funcionan; falta integrar el modelo entrenado de TT2.",
            "lat": lat,
            "lon": lon,
            "nearby_units": int(context["nearby_units"] or 0),
            "dominant_activity": context["dominant_activity"],
            "confidence": None,
        }

    _model = joblib.load(model_file)
    return {
        "status": "model_loaded_needs_feature_adapter",
        "message": "Modelo localizado. Conecta aquí el transformador de variables espaciales usado en entrenamiento.",
        "lat": lat,
        "lon": lon,
        "nearby_units": int(context["nearby_units"] or 0),
        "dominant_activity": context["dominant_activity"],
        "confidence": None,
    }
