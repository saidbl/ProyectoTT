CREATE UNIQUE INDEX IF NOT EXISTS uq_unidad_id_denue ON unidad_economica(id_denue) WHERE id_denue IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_actividad_codigo_scian ON actividad_economica(codigo_scian);
CREATE INDEX IF NOT EXISTS idx_actividad_sector ON actividad_economica(sector_id);
CREATE INDEX IF NOT EXISTS idx_unidad_actividad ON unidad_economica(actividad_id);
CREATE INDEX IF NOT EXISTS idx_unidad_alcaldia ON unidad_economica(alcaldia_id);
CREATE INDEX IF NOT EXISTS idx_unidad_geom ON unidad_economica USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_unidad_geom_utm ON unidad_economica USING GIST (geom_utm);
CREATE INDEX IF NOT EXISTS idx_alcaldia_geom ON alcaldia USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_prediccion_fecha ON prediccion(fecha DESC);

CREATE INDEX IF NOT EXISTS idx_denue_raw_id ON denue_raw(id);
CREATE INDEX IF NOT EXISTS idx_denue_raw_codigo_act ON denue_raw(codigo_act);
CREATE INDEX IF NOT EXISTS idx_denue_raw_cve_mun ON denue_raw(cve_mun);
