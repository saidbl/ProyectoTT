# SAE CDMX — MVP inicial

Primera implementación ejecutable del **Sistema web para el despliegue/caracterización de unidades económicas de la Ciudad de México**. Incluye dashboard visual, API REST, consultas geoespaciales, estructura del módulo predictivo, PostgreSQL/PostGIS, ETL inicial, Docker Compose, respaldos y CI para GitHub.

## 1. Arquitectura

```text
Browser
  -> Nginx / Frontend (HTML + CSS + JS + Leaflet)
      -> /api -> FastAPI
                  -> Servicios / lógica de negocio
                  -> PostgreSQL + PostGIS

DENUE -> ETL Python -> denue_raw -> normalización -> PostgreSQL/PostGIS
Modelo entrenado -> prediction_service -> API -> frontend
```

Consulta `ARCHITECTURE.md` para la separación completa.

## 2. Qué funciona en este MVP

- Dashboard con estructura visual cercana a los mockups de TT1.
- Filtro por alcaldía y sector.
- Conteo total, top de actividades, distribución por sector y alcaldía.
- Mapa de unidades económicas en GeoJSON.
- Capa GeoJSON de alcaldías.
- Detalle básico de una unidad económica al hacer clic.
- Selección de punto para el módulo predictivo.
- Análisis espacial de unidades cercanas al punto.
- Contrato listo para integrar el modelo ML sin inventar resultados.
- API documentada automáticamente en `/docs`.
- PostgreSQL/PostGIS en Docker.
- Backup/restore de BD.
- Workflow básico de GitHub Actions.

## 3. Arranque rápido

### Requisitos

- Docker Desktop
- Git

### Ejecutar

```bash
cp .env.example .env
docker compose up -d --build
```

En Windows PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

Abre:

- Aplicación: `http://localhost:8080`
- Swagger API: `http://localhost:8000/docs`
- Health: `http://localhost:8000/api/health`
- PostgreSQL desde host: `localhost:5434`

## 4. Usar tu base real

El esquema de `db/init/01_schema.sql` se construyó para ser compatible con la estructura que compartiste: `sector`, `actividad_economica`, `alcaldia`, `unidad_economica`, `prediccion` y `denue_raw`.

Si ya tienes un dump completo con alcaldías y unidades económicas, la forma recomendada es:

1. Inicia sólo la BD: `docker compose up -d db`.
2. Restaura tu dump con `scripts/restore.sh archivo.dump` si es formato custom de `pg_dump -Fc`.
3. Si tu archivo es SQL plano, usa `cat backup.sql | docker compose exec -T db psql -U postgres -d sae_cdmx`.
4. Inicia backend y frontend: `docker compose up -d --build backend frontend`.

**Importante:** el dump pegado en el chat está incompleto respecto a datos geográficos; para ver polígonos y establecimientos reales en el mapa necesitas restaurar el dump/CSV completo que contenga `alcaldia.geom` y `unidad_economica`.

## 5. Endpoints iniciales

- `GET /api/health`
- `GET /api/alcaldias`
- `GET /api/alcaldias/geojson`
- `GET /api/sectores`
- `GET /api/actividades`
- `GET /api/dashboard/resumen`
- `GET /api/unidades`
- `GET /api/unidades/{id}`
- `POST /api/predicciones`

## 6. Módulo predictivo

El documento define dos modelos, comparación de resultados y selección del mejor. Eso todavía requiere el pipeline de features exacto y el artefacto entrenado. Por eso este MVP no devuelve una clasificación falsa.

`backend/app/services/prediction_service.py` ya:

1. recibe `lat/lon`;
2. transforma el punto a EPSG:32614;
3. busca unidades cercanas con `ST_DWithin`;
4. resume el contexto local;
5. deja el adaptador para cargar el modelo final.

La siguiente fase debe incorporar exactamente el mismo generador de variables de entrenamiento: celda, multiescala, proporciones, entropía, Simpson, margen de dominancia y demás features validadas.

## 7. ETL

La primera etapa está en `etl/load_denue_csv.py` y carga el CSV original en `denue_raw` para conservar trazabilidad. La normalización completa se debe implementar como segundo paso una vez fijemos el layout exacto del CSV y la carga oficial de polígonos de alcaldías.

Ejemplo local:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r etl/requirements.txt
python etl/load_denue_csv.py data/denue.csv --truncate
```

## 8. Respaldo de BD

Linux/macOS/Git Bash:

```bash
./scripts/backup.sh
```

PowerShell:

```powershell
./scripts/backup.ps1
```

Los backups se excluyen de Git porque pueden ser muy grandes y contener datos generados. Para respaldo externo usa GitHub Releases, almacenamiento de objetos o un bucket privado.

## 9. GitHub

```bash
git init
git checkout -b main
git add .
git commit -m "feat: bootstrap SAE CDMX MVP"
git remote add origin https://github.com/TU_USUARIO/sae-cdmx.git
git push -u origin main
```

Flujo sugerido:

- `main`: versión estable.
- `develop`: integración del equipo.
- `feature/backend-dashboard`, `feature/frontend-map`, `feature/etl-denue`, `feature/modelo-predictivo`.

Nunca subas `.env`, passwords, dumps pesados ni modelos de producción sin una estrategia de versionado.

## 10. Siguiente incremento recomendado

1. Restaurar datos completos reales.
2. Validar índices y conteos contra PostgreSQL actual.
3. Completar vista de consulta por alcaldía y detalle.
4. Implementar clustering/renderizado eficiente para cientos de miles de puntos.
5. Construir pipeline analítico reproducible.
6. Entrenar/evaluar los dos modelos.
7. Integrar el mejor modelo y guardar `prediccion`.
8. Agregar pruebas de integración y e2e.
