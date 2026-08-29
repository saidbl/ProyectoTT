# Arquitectura inicial — SAE CDMX

## Enfoque

Monolito modular desplegado con **frontend**, **backend**, **PostgreSQL/PostGIS** y un proceso desacoplado **denue-updater**. El actualizador consume la API oficial del DENUE y se ejecuta bajo demanda o automáticamente cuando han transcurrido 365 días desde la última sincronización exitosa. Esto implementa la separación por capas descrita en TT1 sin introducir microservicios antes de que sean necesarios.

```text
Usuario / Navegador
       |
       v
Nginx + HTML/CSS/JS + Leaflet
       |  /api/*
       v
FastAPI
  |-- routes/controllers
  |-- services (negocio)
  |-- prediction adapter
  `-- acceso SQL/PostGIS
       |
       v
PostgreSQL + PostGIS
       ^
       |
Actualizador DENUE API (proceso desacoplado)
  |-- descarga paginada BuscarAreaAct
  |-- validación + tabla TEMPORAL
  `-- reemplazo transaccional de unidad_economica
```

## Módulos

- `frontend/`: Vista; dashboard, consulta, detalle y pantalla de predicción.
- `backend/app/api/routes/`: Controladores HTTP.
- `backend/app/services/`: Lógica de negocio y consultas agregadas.
- `backend/app/db/`: conexión/persistencia.
- `etl/`: sincronización DENUE por API, programación anual y carga CSV manual de legado.
- `db/init/`: esquema e índices reproducibles.
- `scripts/`: respaldo/restauración.
- `.github/workflows/`: integración continua.

## Decisiones de la primera entrega

1. Se conserva FastAPI + Python + PostgreSQL/PostGIS + HTML/CSS/JS + Leaflet, como define el documento.
2. No se simula un modelo predictivo. El endpoint existe y ya calcula el entorno espacial; cuando el artefacto de ML esté disponible se conecta mediante el servicio `prediction_service.py`.
3. El frontend consume solamente REST/JSON/GeoJSON.
4. Nginx sirve el frontend y actúa como reverse proxy, por lo que todo puede publicarse detrás de un solo host.
5. La base se respalda con `pg_dump` y el código con Git/GitHub.


## Actualización DENUE

La sincronización no conserva versiones del dataset. Los registros obtenidos desde INEGI se cargan primero en una tabla temporal y sólo después de validar la descarga sustituyen el contenido operativo de `unidad_economica`. La sustitución usa una transacción para que una falla no deje la base a medias.

Se agregó `unidad_economica.id_denue` como identificador de origen y `denue_sync_state` como estado operativo de una sola fila lógica. Esta última no contiene establecimientos ni snapshots; únicamente permite saber cuándo corresponde la siguiente ejecución automática.
