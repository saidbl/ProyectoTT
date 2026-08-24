CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS sector (
    id integer PRIMARY KEY,
    nombre varchar(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS actividad_economica (
    id serial PRIMARY KEY,
    codigo_scian varchar(10) NOT NULL,
    descripcion text NOT NULL,
    sector_id integer REFERENCES sector(id)
);

CREATE TABLE IF NOT EXISTS alcaldia (
    id serial PRIMARY KEY,
    nombre varchar(100) NOT NULL,
    cvegeo varchar(10),
    geom geometry(MultiPolygon,4326) NOT NULL,
    cve_ent varchar(2),
    cve_mun varchar(3)
);

CREATE TABLE IF NOT EXISTS unidad_economica (
    id serial PRIMARY KEY,
    nombre varchar(255),
    lat double precision NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lon double precision NOT NULL CHECK (lon BETWEEN -180 AND 180),
    geom geometry(Point,4326),
    actividad_id integer REFERENCES actividad_economica(id),
    alcaldia_id integer REFERENCES alcaldia(id),
    geom_utm geometry(Point,32614),
    dist_to_border double precision,
    CONSTRAINT chk_geom_srid CHECK (geom IS NULL OR ST_SRID(geom) = 4326),
    CONSTRAINT chk_geom_utm_srid CHECK (geom_utm IS NULL OR ST_SRID(geom_utm) = 32614)
);

CREATE TABLE IF NOT EXISTS prediccion (
    id serial PRIMARY KEY,
    lat double precision NOT NULL,
    lon double precision NOT NULL,
    actividad_predicha integer REFERENCES actividad_economica(id),
    confianza double precision CHECK (confianza BETWEEN 0 AND 1),
    fecha timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS denue_raw (
    id bigint, clee text, nom_estab text, raz_social text, codigo_act text, nombre_act text,
    per_ocu text, tipo_vial text, nom_vial text, tipo_v_e_1 text, nom_v_e_1 text,
    tipo_v_e_2 text, nom_v_e_2 text, tipo_v_e_3 text, nom_v_e_3 text,
    numero_ext text, letra_ext text, edificio text, edificio_e text, numero_int text,
    letra_int text, tipo_asent text, nomb_asent text, tipocencom text, nom_cencom text,
    num_local text, cod_postal text, cve_ent text, entidad text, cve_mun text, municipio text,
    cve_loc text, localidad text, ageb text, manzana text, telefono text, correoelec text,
    www text, tipounieco text, latitud double precision, longitud double precision, fecha_alta text
);

CREATE OR REPLACE FUNCTION mapear_sector(codigo text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE prefijo int;
BEGIN
    prefijo := substring(codigo from 1 for 2)::int;
    IF prefijo BETWEEN 31 AND 33 THEN RETURN '31-33';
    ELSIF prefijo BETWEEN 48 AND 49 THEN RETURN '48-49';
    ELSE RETURN substring(codigo from 1 for 2);
    END IF;
END;
$$;

INSERT INTO sector (id, nombre) VALUES
(1, 'Primario'), (2, 'Secundario'), (3, 'Terciario')
ON CONFLICT (id) DO NOTHING;

INSERT INTO actividad_economica (id, codigo_scian, descripcion, sector_id) VALUES
(1,'11','Agricultura, cría y explotación de animales, aprovechamiento forestal, pesca y caza',1),
(2,'21','Minería',2),
(3,'22','Generación, transmisión, distribución y comercialización de energía eléctrica, suministro de agua y de gas natural por ductos al consumidor final',2),
(4,'23','Construcción',2),
(5,'31-33','Industrias manufactureras',2),
(6,'43','Comercio al por mayor',3),
(7,'46','Comercio al por menor',3),
(8,'48-49','Transportes, correos y almacenamiento',3),
(9,'51','Información en medios masivos',3),
(10,'52','Servicios financieros y de seguros',3),
(11,'53','Servicios inmobiliarios y de alquiler de bienes muebles e intangibles',3),
(12,'54','Servicios profesionales, científicos y técnicos',3),
(13,'55','Dirección y administración de grupos empresariales o corporativos',3),
(14,'56','Servicios de apoyo a los negocios y manejo de residuos, y servicios de remediación',3),
(15,'61','Servicios educativos',3),
(16,'62','Servicios de salud y de asistencia social',3),
(17,'71','Servicios de esparcimiento culturales y deportivos, y otros servicios recreativos',3),
(18,'72','Servicios de alojamiento temporal y de preparación de alimentos y bebidas',3),
(19,'81','Otros servicios excepto actividades gubernamentales',3),
(20,'93','Actividades legislativas, gubernamentales, de impartición de justicia y de organismos internacionales y extraterritoriales',3)
ON CONFLICT (id) DO NOTHING;

SELECT setval(pg_get_serial_sequence('actividad_economica','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM actividad_economica),1));
