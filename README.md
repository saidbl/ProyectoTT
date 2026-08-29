# SAE CDMX — MVP inicial

Primera implementación ejecutable del **Sistema web para el despliegue/caracterización de unidades económicas de la Ciudad de México**. Incluye dashboard visual, API REST, consultas geoespaciales, estructura del módulo predictivo, PostgreSQL/PostGIS, ETL inicial, Docker Compose, respaldos y CI para GitHub.

## 1. Arquitectura

```text
Browser
  -> Nginx / Frontend (HTML + CSS + JS + Leaflet)
      -> /api -> FastAPI
                  -> Servicios / lógica de negocio
                  -> PostgreSQL + PostGIS

API DENUE -> actualizador anual -> tabla temporal -> unidad_economica -> PostgreSQL/PostGIS
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
- Sincronización automática anual desde la API oficial del DENUE.
- Estado de la última actualización disponible en la API y en el dashboard.
- Backup/restore de BD.
- Workflow básico de GitHub Actions.

## 3. Arranque rápido

### Requisitos

- Docker Desktop
- Git

### Ejecutar

1. Copia la configuración de ejemplo.
2. Obtén un token gratuito de la API DENUE de INEGI.
3. Colócalo en `DENUE_TOKEN` dentro de `.env`.
4. Levanta el sistema.

```bash
cp .env.example .env
# Edita .env y coloca DENUE_TOKEN=TU_TOKEN
docker compose up -d --build
```

En Windows PowerShell:

```powershell
Copy-Item .env.example .env
# Edita .env y coloca DENUE_TOKEN=TU_TOKEN
docker compose up -d --build
```

El contenedor `denue-updater` revisa una vez al día si la última actualización exitosa tiene 365 días o más. Si nunca se ha ejecutado, realiza la primera sincronización automáticamente al detectar un token válido.

Abre:

- Aplicación: `http://localhost:8081`
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
- `GET /api/datos/estado-actualizacion`

## 6. Módulo predictivo

El documento define dos modelos, comparación de resultados y selección del mejor. Eso todavía requiere el pipeline de features exacto y el artefacto entrenado. Por eso este MVP no devuelve una clasificación falsa.

`backend/app/services/prediction_service.py` ya:

1. recibe `lat/lon`;
2. transforma el punto a EPSG:32614;
3. busca unidades cercanas con `ST_DWithin`;
4. resume el contexto local;
5. deja el adaptador para cargar el modelo final.

La siguiente fase debe incorporar exactamente el mismo generador de variables de entrenamiento: celda, multiescala, proporciones, entropía, Simpson, margen de dominancia y demás features validadas.

## 7. Actualización automática con la API DENUE

La actualización operativa ya no depende de descargar y versionar un CSV. El proceso principal está en `etl/update_denue_api.py` y usa el método `BuscarAreaAct` de la API DENUE para consultar todos los establecimientos de la entidad `09` (Ciudad de México) por páginas.

Flujo implementado:

1. Consulta la API DENUE por páginas.
2. Valida `Id`, coordenadas y sector/clase SCIAN.
3. Mapea la actividad al mismo catálogo de 20 sectores que ya usa el dashboard/modelo.
4. Carga los registros válidos en una **tabla temporal** de PostgreSQL. Esta tabla desaparece al terminar el proceso y no crea versiones del dataset.
5. Si la descarga supera el umbral de seguridad, reemplaza `unidad_economica` dentro de una sola transacción. Si la API falla o devuelve pocos registros, la tabla actual se conserva intacta.
6. Regenera `geom`, `geom_utm`, `alcaldia_id` y `dist_to_border` con PostGIS.
7. Guarda únicamente el estado operativo de la última ejecución en `denue_sync_state` (fecha, estado y cantidad de registros). No se guardan snapshots históricos.

La actualización automática está en `etl/yearly_denue_updater.py`. Por defecto revisa cada 24 horas y ejecuta una nueva sincronización sólo cuando han pasado 365 días desde el último éxito.

### Ejecutar una actualización ahora

```bash
docker compose run --rm denue-updater python update_denue_api.py
```

Con Make:

```bash
make denue-sync
```

### Probar la descarga sin tocar la tabla actual

```bash
docker compose run --rm denue-updater python update_denue_api.py --dry-run
```

### Ver el servicio automático

```bash
docker compose logs -f denue-updater
```

El script `etl/load_denue_csv.py` se conserva únicamente como herramienta de carga manual/legado; ya no forma parte del flujo automático principal.

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

1. Configurar `DENUE_TOKEN` y ejecutar la primera sincronización API.
2. Verificar el estado en `/api/datos/estado-actualizacion`.
3. Completar vista de consulta por alcaldía y detalle.
4. Implementar clustering/renderizado eficiente para cientos de miles de puntos.
5. Mantener el pipeline analítico del modelo separado de la actualización operativa.
6. Entrenar/evaluar los dos modelos.
7. Integrar el mejor modelo y guardar `prediccion`.
8. Agregar pruebas de integración y e2e.
