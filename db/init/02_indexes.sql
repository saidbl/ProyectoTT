CREATE UNIQUE INDEX IF NOT EXISTS uq_actividad_codigo_scian ON actividad_economica(codigo_scian);
CREATE INDEX IF NOT EXISTS idx_actividad_sector ON actividad_economica(sector_id);
CREATE INDEX IF NOT EXISTS idx_unidad_actividad ON unidad_economica(actividad_id);
CREATE INDEX IF NOT EXISTS idx_unidad_alcaldia ON unidad_economica(alcaldia_id);
CREATE INDEX IF NOT EXISTS idx_unidad_geom ON unidad_economica USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_unidad_geom_utm ON unidad_economica USING GIST (geom_utm);
CREATE INDEX IF NOT EXISTS idx_alcaldia_geom ON alcaldia USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_prediccion_fecha ON prediccion(fecha DESC);
