from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import quote

import psycopg
import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

DENUE_BASE_URL = "https://www.inegi.org.mx/app/api/denue/v1/consulta/BuscarAreaActEstr"
DENUE_COUNT_URL = "https://www.inegi.org.mx/app/api/denue/v1/consulta/Cuantificar"
SOURCE_NAME = "DENUE_CDMX"
DENUE_SECTOR_CODES = (
    "11", "21", "22", "23", "31", "32", "33", "43", "46", "48", "49",
    "51", "52", "53", "54", "55", "56", "61", "62", "71", "72", "81", "93",
)

STAGE_COLUMNS = (
    "id_denue",
    "clee",
    "nom_estab",
    "raz_social",
    "codigo_act",
    "nombre_act",
    "per_ocu",
    "tipo_vial",
    "nom_vial",
    "numero_ext",
    "edificio",
    "edificio_e",
    "numero_int",
    "tipo_asent",
    "nomb_asent",
    "num_local",
    "cod_postal",
    "cve_ent",
    "entidad",
    "cve_mun",
    "municipio",
    "cve_loc",
    "localidad",
    "ageb",
    "manzana",
    "telefono",
    "correoelec",
    "www",
    "tipounieco",
    "latitud",
    "longitud",
    "fecha_alta",
    "ubicacion_api",
    "tipo_corredor_industrial",
    "nom_corredor_industrial",
    "sector_actividad_id",
    "subsector_actividad_id",
    "rama_actividad_id",
    "subrama_actividad_id",
    "edificio_piso",
    "area_geo",
    "api_payload",
    "actividad_id",
)


class DenueSyncError(RuntimeError):
    """Error controlado durante la sincronización DENUE."""


@dataclass(frozen=True)
class SyncConfig:
    token: str
    database_url: str
    entity: str = "09"
    page_size: int = 1000
    min_records: int = 100_000
    timeout_seconds: int = 60
    request_delay_seconds: float = 0.10
    max_pages: int = 2000

    @classmethod
    def from_env(cls) -> "SyncConfig":
        token = os.getenv("DENUE_TOKEN", "").strip()
        database_url = os.getenv(
            "ETL_DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5434/sae_cdmx",
        ).strip()
        return cls(
            token=token,
            database_url=_normalize_psycopg_dsn(database_url),
            entity=os.getenv("DENUE_ENTITY", "09").strip() or "09",
            page_size=max(1, int(os.getenv("DENUE_PAGE_SIZE", "1000"))),
            min_records=max(1, int(os.getenv("DENUE_MIN_RECORDS", "100000"))),
            timeout_seconds=max(5, int(os.getenv("DENUE_REQUEST_TIMEOUT", "60"))),
            request_delay_seconds=max(0.0, float(os.getenv("DENUE_REQUEST_DELAY_SECONDS", "0.10"))),
            max_pages=max(1, int(os.getenv("DENUE_MAX_PAGES", "2000"))),
        )


@dataclass
class SyncStats:
    api_records: int = 0
    staged_records: int = 0
    duplicate_ids: int = 0
    skipped_invalid_id: int = 0
    skipped_invalid_coordinates: int = 0
    skipped_unknown_activity: int = 0
    pages: int = 0

    @property
    def skipped_total(self) -> int:
        return (
            self.skipped_invalid_id
            + self.skipped_invalid_coordinates
            + self.skipped_unknown_activity
        )


def _normalize_psycopg_dsn(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", normalized.lower())


def _record_map(record: dict[str, Any]) -> dict[str, Any]:
    return {_normalize_key(k): v for k, v in record.items()}


def _pick(record: dict[str, Any], *aliases: str) -> Any:
    normalized = _record_map(record)
    for alias in aliases:
        key = _normalize_key(alias)
        if key in normalized and normalized[key] not in (None, ""):
            return normalized[key]
    return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _to_text(value: Any, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_len] if max_len is not None else text


def _digits(value: Any) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits or None


def _sector_key(raw_sector: Any, raw_class: Any) -> str | None:
    """Convierte sector/clase SCIAN de la API al catálogo de 20 actividades del TT."""
    candidates = [raw_sector, raw_class]
    prefix = None
    for value in candidates:
        digits = _digits(value)
        if digits and len(digits) >= 2:
            prefix = digits[:2]
            break

    if prefix is None:
        return None
    if prefix in {"31", "32", "33"}:
        return "31-33"
    if prefix in {"48", "49"}:
        return "48-49"
    return prefix


def _parse_area_geo(area_geo: Any, fallback_entity: str) -> tuple[str, str | None, str | None, str | None]:
    """Separa la clave geográfica de la API en entidad (2), municipio (3) y localidad (4).

    El valor puede llegar numérico y perder el cero inicial de CDMX; por eso se rellena a
    nueve posiciones antes de separarlo.
    """
    raw = _to_text(area_geo)
    digits = _digits(area_geo)
    entity = fallback_entity.zfill(2)[:2]
    if not digits:
        return entity, None, None, raw

    if len(digits) <= 9:
        digits = digits.zfill(9)
    else:
        digits = digits[:9]

    return digits[:2], digits[2:5], digits[5:9], raw


def _parse_ubicacion(ubicacion: Any) -> tuple[str | None, str | None, str | None]:
    """Intenta separar 'Localidad, Municipio, Entidad' sin inventar valores."""
    text = _to_text(ubicacion)
    if not text:
        return None, None, None
    parts = [part.strip() for part in text.rsplit(",", 2)]
    if len(parts) != 3:
        return None, None, None
    return parts[0] or None, parts[1] or None, parts[2] or None


def _parse_record(
    record: dict[str, Any],
    activity_by_code: dict[str, int],
    entity: str,
) -> tuple[tuple[Any, ...] | None, str | None]:
    """Convierte un objeto API en una fila temporal raw + la actividad de 20 sectores."""
    id_denue = _to_int(_pick(record, "Id", "Id_Establecimiento", "Id establecimiento"))
    if id_denue is None:
        return None, "invalid_id"

    lat = _to_float(_pick(record, "Latitud", "Latitude"))
    lon = _to_float(_pick(record, "Longitud", "Longitude"))
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None, "invalid_coordinates"

    raw_class = _pick(
        record,
        "CLASE_ACTIVIDAD_ID",
        "Id_Clase",
        "Id Clase",
        "Clase_Id",
        "Codigo_Act",
        "Codigo actividad",
    )
    raw_sector = _pick(
        record,
        "SECTOR_ACTIVIDAD_ID",
        "Id_Sector",
        "Id Sector",
        "Sector_Id",
    )
    sector_code = _sector_key(raw_sector, raw_class)
    activity_id = activity_by_code.get(sector_code or "")
    if activity_id is None:
        return None, "unknown_activity"

    ubicacion = _to_text(_pick(record, "Ubicacion", "Ubicación"))
    localidad, municipio, entidad = _parse_ubicacion(ubicacion)

    cve_ent, cve_mun, cve_loc, area_geo_raw = _parse_area_geo(
        _pick(record, "AreaGeo", "Area_Geo", "Clave_Area_Geografica", "Clave área geográfica"),
        entity,
    )

    codigo_act = _digits(raw_class)
    sector_api = _digits(raw_sector)
    subsector_api = _digits(_pick(record, "SUBSECTOR_ACTIVIDAD_ID", "Id_Subsector", "Subsector_Id"))
    rama_api = _digits(_pick(record, "RAMA_ACTIVIDAD_ID", "Id_Rama", "Rama_Id"))
    subrama_api = _digits(_pick(record, "SUBRAMA_ACTIVIDAD_ID", "Id_Subrama", "Subrama_Id"))

    row = (
        id_denue,
        _to_text(_pick(record, "CLEE", "Clee")),
        _to_text(_pick(record, "Nombre", "Nombre_Establecimiento", "Nombre establecimiento")),
        _to_text(_pick(record, "Razon_social", "Razón social", "Razon Social")),
        codigo_act,
        _to_text(_pick(record, "Clase_actividad", "Clase actividad", "Nombre_Actividad")),
        _to_text(_pick(record, "Estrato", "Personal ocupado", "Per_ocu")),
        _to_text(_pick(record, "Tipo_vialidad", "Tipo vialidad")),
        _to_text(_pick(record, "Calle", "Nombre_vialidad", "Nom_vial")),
        _to_text(_pick(record, "Num_Exterior", "Numero_Exterior", "Número exterior")),
        _to_text(_pick(record, "EDIFICIO", "Edificio")),
        _to_text(_pick(record, "EDIFICIO_PISO", "Edificio_Piso", "Numero_Piso")),
        _to_text(_pick(record, "Num_Interior", "Numero_Interior", "Número interior")),
        _to_text(_pick(record, "Tipo_Asentamiento", "Tipo asentamiento")),
        _to_text(_pick(record, "Colonia", "Nombre_Asentamiento", "Nomb_Asent")),
        _to_text(_pick(record, "numero_local", "Numero_Local", "Número local")),
        _to_text(_pick(record, "CP", "Codigo_Postal", "Código postal")),
        cve_ent,
        entidad,
        cve_mun,
        municipio,
        cve_loc,
        localidad,
        _to_text(_pick(record, "AGEB", "Ageb")),
        _to_text(_pick(record, "Manzana")),
        _to_text(_pick(record, "Telefono", "Teléfono")),
        _to_text(_pick(record, "Correo_e", "Correo", "Correo electrónico")),
        _to_text(_pick(record, "Sitio_internet", "WWW", "Sitio internet")),
        _to_text(_pick(record, "Tipo", "Tipo_Unidad_Economica", "Tipo unidad económica")),
        lat,
        lon,
        _to_text(_pick(record, "Fecha_Alta", "Fecha Alta", "fecha_alta")),
        ubicacion,
        _to_text(_pick(record, "tipo_corredor_industrial", "Tipo_Corredor_Industrial")),
        _to_text(_pick(record, "nom_corredor_industrial", "Nombre_Corredor_Industrial")),
        sector_api,
        subsector_api,
        rama_api,
        subrama_api,
        _to_text(_pick(record, "EDIFICIO_PISO", "Edificio_Piso", "Numero_Piso")),
        area_geo_raw,
        json.dumps(record, ensure_ascii=False, separators=(",", ":")),
        activity_id,
    )
    return row, None


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=2, pool_maxsize=2)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": "SAE-CDMX-TT/1.1 (+DENUE annual updater)",
        }
    )
    return session


def _build_page_url(config: SyncConfig, start: int, end: int) -> str:
    token = quote(config.token, safe="")
    return (
        f"{DENUE_BASE_URL}/{config.entity}/0/0/0/0/0/0/0/0/0/"
        f"{start}/{end}/0/0/{token}"
    )


def _fetch_total(session: requests.Session, config: SyncConfig) -> int:
    token = quote(config.token, safe="")
    totals_by_sector: dict[str, int] = {}

    for sector in DENUE_SECTOR_CODES:
        url = f"{DENUE_COUNT_URL}/{sector}/{config.entity}/0/{token}"
        try:
            response = session.get(url, timeout=config.timeout_seconds)
        except requests.RequestException as exc:
            message = str(exc).replace(config.token, "***")
            raise DenueSyncError(
                f"No fue posible cuantificar el sector SCIAN {sector}: {message}"
            ) from exc

        if response.status_code != 200:
            raise DenueSyncError(
                f"Cuantificar DENUE respondió HTTP {response.status_code} para el sector "
                f"SCIAN {sector}. Revisa el token y la disponibilidad del servicio."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise DenueSyncError(
                f"Cuantificar DENUE respondió contenido no JSON para el sector {sector}."
            ) from exc

        if not isinstance(payload, list):
            raise DenueSyncError(
                f"Cuantificar DENUE devolvió un formato inesperado para el sector {sector}."
            )

        sector_total = 0
        for item in payload:
            if not isinstance(item, dict):
                continue
            activity = _digits(_pick(item, "AE", "Id_Actividad", "Id Actividad", "Actividad"))
            total = _to_int(_pick(item, "Total"))
            if activity == sector and total is not None:
                sector_total += total
        totals_by_sector[sector] = sector_total
        if config.request_delay_seconds:
            time.sleep(config.request_delay_seconds)

    total = sum(totals_by_sector.values())
    nonzero = sum(1 for value in totals_by_sector.values() if value > 0)
    if total <= 0:
        raise DenueSyncError(
            "Cuantificar DENUE reportó cero establecimientos al sumar los sectores SCIAN de CDMX."
        )

    print(
        f"[DENUE] Cuantificar por sectores: {nonzero}/{len(DENUE_SECTOR_CODES)} sectores "
        f"con registros, total={total:,}."
    )
    return total


def _fetch_page(
    session: requests.Session,
    config: SyncConfig,
    start: int,
    end: int,
) -> list[dict[str, Any]]:
    url = _build_page_url(config, start, end)
    try:
        response = session.get(url, timeout=config.timeout_seconds)
    except requests.RequestException as exc:
        message = str(exc).replace(config.token, "***")
        raise DenueSyncError(f"No fue posible conectar con la API DENUE: {message}") from exc

    if response.status_code != 200:
        raise DenueSyncError(
            f"La API DENUE respondió HTTP {response.status_code}. "
            "Revisa el token, disponibilidad del servicio y parámetros de consulta."
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise DenueSyncError("La API DENUE respondió contenido no JSON.") from exc

    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        possible = payload.get("result") or payload.get("results") or payload.get("data")
        if isinstance(possible, list):
            return [item for item in possible if isinstance(item, dict)]
        detail = payload.get("Message") or payload.get("message") or payload.get("error")
        raise DenueSyncError(f"Respuesta inesperada de la API DENUE: {detail or 'objeto sin resultados'}")

    raise DenueSyncError("Formato de respuesta no reconocido en la API DENUE.")


def ensure_schema(conn: psycopg.Connection) -> None:
    """Aplica cambios mínimos necesarios tanto en BD nuevas como ya restauradas."""
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE unidad_economica ADD COLUMN IF NOT EXISTS id_denue bigint")
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_unidad_id_denue "
            "ON unidad_economica(id_denue) WHERE id_denue IS NOT NULL"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS denue_sync_state (
                source varchar(40) PRIMARY KEY,
                last_attempt_at timestamptz,
                last_success_at timestamptz,
                last_status varchar(20),
                last_records integer,
                last_error text
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS denue_raw (
                id bigint, clee text, nom_estab text, raz_social text, codigo_act text, nombre_act text,
                per_ocu text, tipo_vial text, nom_vial text, tipo_v_e_1 text, nom_v_e_1 text,
                tipo_v_e_2 text, nom_v_e_2 text, tipo_v_e_3 text, nom_v_e_3 text,
                numero_ext text, letra_ext text, edificio text, edificio_e text, numero_int text,
                letra_int text, tipo_asent text, nomb_asent text, tipocencom text, nom_cencom text,
                num_local text, cod_postal text, cve_ent text, entidad text, cve_mun text, municipio text,
                cve_loc text, localidad text, ageb text, manzana text, telefono text, correoelec text,
                www text, tipounieco text, latitud double precision, longitud double precision, fecha_alta text
            )
            """
        )
        cur.execute("ALTER TABLE denue_raw ADD COLUMN IF NOT EXISTS ubicacion_api text")
        cur.execute("ALTER TABLE denue_raw ADD COLUMN IF NOT EXISTS tipo_corredor_industrial text")
        cur.execute("ALTER TABLE denue_raw ADD COLUMN IF NOT EXISTS nom_corredor_industrial text")
        cur.execute("ALTER TABLE denue_raw ADD COLUMN IF NOT EXISTS sector_actividad_id text")
        cur.execute("ALTER TABLE denue_raw ADD COLUMN IF NOT EXISTS subsector_actividad_id text")
        cur.execute("ALTER TABLE denue_raw ADD COLUMN IF NOT EXISTS rama_actividad_id text")
        cur.execute("ALTER TABLE denue_raw ADD COLUMN IF NOT EXISTS subrama_actividad_id text")
        cur.execute("ALTER TABLE denue_raw ADD COLUMN IF NOT EXISTS edificio_piso text")
        cur.execute("ALTER TABLE denue_raw ADD COLUMN IF NOT EXISTS area_geo text")
        cur.execute("ALTER TABLE denue_raw ADD COLUMN IF NOT EXISTS api_payload jsonb")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_denue_raw_id ON denue_raw(id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_denue_raw_codigo_act ON denue_raw(codigo_act)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_denue_raw_cve_mun ON denue_raw(cve_mun)")
    conn.commit()


def mark_attempt(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO denue_sync_state(source, last_attempt_at, last_status, last_error)
            VALUES (%s, now(), 'running', NULL)
            ON CONFLICT (source) DO UPDATE SET
                last_attempt_at = EXCLUDED.last_attempt_at,
                last_status = 'running',
                last_error = NULL
            """,
            (SOURCE_NAME,),
        )
    conn.commit()


def mark_failure(conn: psycopg.Connection, message: str) -> None:
    safe_message = message[:4000]
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO denue_sync_state(source, last_attempt_at, last_status, last_error)
            VALUES (%s, now(), 'failed', %s)
            ON CONFLICT (source) DO UPDATE SET
                last_attempt_at = now(),
                last_status = 'failed',
                last_error = EXCLUDED.last_error
            """,
            (SOURCE_NAME, safe_message),
        )
    conn.commit()


def _load_activity_map(conn: psycopg.Connection) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, codigo_scian FROM actividad_economica")
        result = {str(code).strip(): int(activity_id) for activity_id, code in cur.fetchall()}
    required = {
        "11", "21", "22", "23", "31-33", "43", "46", "48-49", "51", "52",
        "53", "54", "55", "56", "61", "62", "71", "72", "81", "93",
    }
    missing = sorted(required - set(result))
    if missing:
        raise DenueSyncError(
            "El catálogo actividad_economica no contiene los sectores esperados: " + ", ".join(missing)
        )
    return result


def _prepare_temp_stage(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS denue_sync_stage")
        cur.execute(
            """
            CREATE TEMP TABLE denue_sync_stage (
                id_denue bigint NOT NULL,
                clee text,
                nom_estab text,
                raz_social text,
                codigo_act text,
                nombre_act text,
                per_ocu text,
                tipo_vial text,
                nom_vial text,
                numero_ext text,
                edificio text,
                edificio_e text,
                numero_int text,
                tipo_asent text,
                nomb_asent text,
                num_local text,
                cod_postal text,
                cve_ent text,
                entidad text,
                cve_mun text,
                municipio text,
                cve_loc text,
                localidad text,
                ageb text,
                manzana text,
                telefono text,
                correoelec text,
                www text,
                tipounieco text,
                latitud double precision NOT NULL,
                longitud double precision NOT NULL,
                fecha_alta text,
                ubicacion_api text,
                tipo_corredor_industrial text,
                nom_corredor_industrial text,
                sector_actividad_id text,
                subsector_actividad_id text,
                rama_actividad_id text,
                subrama_actividad_id text,
                edificio_piso text,
                area_geo text,
                api_payload text,
                actividad_id integer NOT NULL
            ) ON COMMIT PRESERVE ROWS
            """
        )
    conn.commit()


def _copy_rows(conn: psycopg.Connection, rows: Iterable[tuple[Any, ...]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    columns = ", ".join(STAGE_COLUMNS)
    with conn.cursor() as cur:
        with cur.copy(f"COPY denue_sync_stage ({columns}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)
    conn.commit()
    return len(rows)


def fetch_into_stage(conn: psycopg.Connection, config: SyncConfig) -> SyncStats:
    activity_by_code = _load_activity_map(conn)
    _prepare_temp_stage(conn)

    session = _build_session()
    stats = SyncStats()
    seen_ids: set[int] = set()
    start = 1
    total_available = _fetch_total(session, config)
    if total_available < config.min_records:
        raise DenueSyncError(
            f"Cuantificar DENUE reportó sólo {total_available:,} registros, por debajo del mínimo "
            f"de seguridad ({config.min_records:,}). Las tablas actuales NO fueron reemplazadas."
        )

    print(
        f"[DENUE] Iniciando descarga de entidad {config.entity} (CDMX). "
        f"Cuantificar reporta {total_available:,} establecimientos."
    )
    print("[DENUE] Fuente detallada: BuscarAreaActEstr; SCIAN final del sistema: 20 sectores.")

    for page_number in range(1, config.max_pages + 1):
        if start > total_available:
            break
        end = min(start + config.page_size - 1, total_available)
        records = _fetch_page(session, config, start, end)
        stats.pages = page_number

        if not records:
            raise DenueSyncError(
                f"La API dejó de devolver datos en el registro {start:,}, antes del total "
                f"reportado por Cuantificar ({total_available:,}). Las tablas actuales NO fueron reemplazadas."
            )

        stats.api_records += len(records)
        parsed_rows: list[tuple[Any, ...]] = []

        for record in records:
            parsed, reason = _parse_record(record, activity_by_code, config.entity)
            if parsed is None:
                if reason == "invalid_id":
                    stats.skipped_invalid_id += 1
                elif reason == "invalid_coordinates":
                    stats.skipped_invalid_coordinates += 1
                elif reason == "unknown_activity":
                    stats.skipped_unknown_activity += 1
                continue

            if int(parsed[0]) in seen_ids:
                stats.duplicate_ids += 1
                continue
            seen_ids.add(int(parsed[0]))
            parsed_rows.append(parsed)

        inserted = _copy_rows(conn, parsed_rows)
        stats.staged_records += inserted
        print(
            f"[DENUE] Página {page_number}: API={len(records):,}, válidos={inserted:,}, "
            f"acumulado={stats.staged_records:,}."
        )

        start += len(records)
        if config.request_delay_seconds:
            time.sleep(config.request_delay_seconds)
    else:
        raise DenueSyncError(
            f"Se alcanzó DENUE_MAX_PAGES={config.max_pages} sin llegar al total reportado."
        )

    if stats.api_records != total_available:
        raise DenueSyncError(
            f"Descarga inconsistente: se recibieron {stats.api_records:,} registros y "
            f"Cuantificar reportó {total_available:,}. Las tablas actuales NO fueron reemplazadas."
        )

    min_valid_records = max(config.min_records, int(total_available * 0.95))
    if stats.staged_records < min_valid_records:
        raise DenueSyncError(
            f"Validación de seguridad fallida: sólo {stats.staged_records:,} de "
            f"{total_available:,} registros ({stats.staged_records / total_available:.1%}) "
            "son utilizables. Se requiere al menos 95 % y las tablas actuales NO fueron reemplazadas."
        )

    print(
        "[DENUE] Descarga validada: "
        f"API={stats.api_records:,}, preparados={stats.staged_records:,}, "
        f"omitidos={stats.skipped_total:,}, duplicados={stats.duplicate_ids:,}."
    )
    return stats


def replace_current_data(conn: psycopg.Connection, stats: SyncStats) -> tuple[int, int]:
    """Sustituye denue_raw y unidad_economica en una única transacción."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM alcaldia WHERE geom IS NOT NULL")
            alcaldia_count = int(cur.fetchone()[0])
            if alcaldia_count < 16:
                raise DenueSyncError(
                    f"Se esperaban las 16 geometrías de alcaldías y sólo hay {alcaldia_count}. "
                    "Se cancela la actualización para no perder la asignación territorial."
                )
            cur.execute("DELETE FROM denue_raw")
            cur.execute(
                """
                INSERT INTO denue_raw (
                    id, clee, nom_estab, raz_social, codigo_act, nombre_act, per_ocu,
                    tipo_vial, nom_vial, numero_ext, edificio, edificio_e, numero_int,
                    tipo_asent, nomb_asent, num_local, cod_postal,
                    cve_ent, entidad, cve_mun, municipio, cve_loc, localidad,
                    ageb, manzana, telefono, correoelec, www, tipounieco,
                    latitud, longitud, fecha_alta,
                    ubicacion_api, tipo_corredor_industrial, nom_corredor_industrial,
                    sector_actividad_id, subsector_actividad_id, rama_actividad_id,
                    subrama_actividad_id, edificio_piso, area_geo, api_payload
                )
                SELECT
                    id_denue, clee, nom_estab, raz_social, codigo_act, nombre_act, per_ocu,
                    tipo_vial, nom_vial, numero_ext, edificio, edificio_e, numero_int,
                    tipo_asent, nomb_asent, num_local, cod_postal,
                    cve_ent, entidad, cve_mun, municipio, cve_loc, localidad,
                    ageb, manzana, telefono, correoelec, www, tipounieco,
                    latitud, longitud, fecha_alta,
                    ubicacion_api, tipo_corredor_industrial, nom_corredor_industrial,
                    sector_actividad_id, subsector_actividad_id, rama_actividad_id,
                    subrama_actividad_id, edificio_piso, area_geo, api_payload::jsonb
                FROM denue_sync_stage
                """
            )
            raw_inserted = cur.rowcount
            if raw_inserted != stats.staged_records:
                raise DenueSyncError(
                    f"denue_raw insertó {raw_inserted:,} registros, pero se esperaban "
                    f"{stats.staged_records:,}; la transacción será revertida."
                )

            cur.execute("DELETE FROM unidad_economica")
            cur.execute(
                """
                WITH src AS (
                    SELECT
                        id_denue,
                        nom_estab AS nombre,
                        latitud AS lat,
                        longitud AS lon,
                        actividad_id,
                        ST_SetSRID(ST_MakePoint(longitud, latitud), 4326) AS geom
                    FROM denue_sync_stage
                ),
                src_utm AS (
                    SELECT *, ST_Transform(geom, 32614) AS geom_utm
                    FROM src
                ),
                alcaldias_utm AS (
                    SELECT id, geom, ST_Transform(geom, 32614) AS geom_utm
                    FROM alcaldia
                    WHERE geom IS NOT NULL
                )
                INSERT INTO unidad_economica (
                    id_denue,
                    nombre,
                    lat,
                    lon,
                    geom,
                    actividad_id,
                    alcaldia_id,
                    geom_utm,
                    dist_to_border
                )
                SELECT
                    s.id_denue,
                    s.nombre,
                    s.lat,
                    s.lon,
                    s.geom,
                    s.actividad_id,
                    COALESCE(inside_al.id, nearest_al.id) AS alcaldia_id,
                    s.geom_utm,
                    ST_Distance(
                        s.geom_utm,
                        ST_Boundary(COALESCE(inside_al.geom_utm, nearest_al.geom_utm))
                    ) AS dist_to_border
                FROM src_utm s
                LEFT JOIN LATERAL (
                    SELECT a.id, a.geom_utm
                    FROM alcaldias_utm a
                    WHERE ST_Covers(a.geom, s.geom)
                    LIMIT 1
                ) inside_al ON TRUE
                LEFT JOIN LATERAL (
                    SELECT a.id, a.geom_utm
                    FROM alcaldias_utm a
                    WHERE inside_al.id IS NULL
                    ORDER BY a.geom <-> s.geom
                    LIMIT 1
                ) nearest_al ON TRUE
                """
            )
            units_inserted = cur.rowcount
            if units_inserted != stats.staged_records:
                raise DenueSyncError(
                    f"unidad_economica insertó {units_inserted:,} registros, pero se esperaban "
                    f"{stats.staged_records:,}; la transacción será revertida."
                )

            cur.execute(
                """
                INSERT INTO denue_sync_state(
                    source, last_attempt_at, last_success_at, last_status, last_records, last_error
                )
                VALUES (%s, now(), now(), 'success', %s, NULL)
                ON CONFLICT (source) DO UPDATE SET
                    last_attempt_at = now(),
                    last_success_at = now(),
                    last_status = 'success',
                    last_records = EXCLUDED.last_records,
                    last_error = NULL
                """,
                (SOURCE_NAME, units_inserted),
            )

    with conn.cursor() as cur:
        cur.execute("ANALYZE denue_raw")
        cur.execute("ANALYZE unidad_economica")
    conn.commit()
    return raw_inserted, units_inserted


def run_sync(config: SyncConfig, dry_run: bool = False) -> SyncStats:
    if not config.token:
        raise DenueSyncError(
            "Falta DENUE_TOKEN. Obtén un token de la API DENUE de INEGI y colócalo en el archivo .env."
        )

    started = datetime.now(timezone.utc)
    print(f"[DENUE] Sincronización iniciada: {started.isoformat(timespec='seconds')}")

    with psycopg.connect(config.database_url) as conn:
        ensure_schema(conn)
        if not dry_run:
            mark_attempt(conn)
        try:
            stats = fetch_into_stage(conn, config)
            if dry_run:
                print(
                    "[DENUE] DRY-RUN: validación terminada; denue_raw y unidad_economica "
                    "no se modificaron."
                )
                return stats

            raw_inserted, units_inserted = replace_current_data(conn, stats)
            print(
                f"[DENUE] Sincronización completada. denue_raw={raw_inserted:,}; "
                f"unidad_economica={units_inserted:,}."
            )
            return stats
        except Exception as exc:
            if not dry_run:
                try:
                    conn.rollback()
                    mark_failure(conn, str(exc).replace(config.token, "***"))
                except Exception:
                    pass
            raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Actualiza denue_raw y unidad_economica desde la API DENUE para la Ciudad de México."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Descarga y valida los datos, pero no reemplaza denue_raw ni unidad_economica.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = SyncConfig.from_env()
    try:
        run_sync(config, dry_run=args.dry_run)
        return 0
    except DenueSyncError as exc:
        print(f"[DENUE] ERROR: {str(exc).replace(config.token, '***')}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("[DENUE] Interrumpido por el usuario.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(
            f"[DENUE] ERROR inesperado: {str(exc).replace(config.token, '***')}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
