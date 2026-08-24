# Arquitectura inicial — SAE CDMX

## Enfoque

Monolito modular desplegado como tres contenedores: **frontend**, **backend** y **PostgreSQL/PostGIS**. El ETL se mantiene como proceso separado y ejecutable bajo demanda/programación. Esto implementa la separación por capas descrita en TT1 sin introducir microservicios antes de que sean necesarios.

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
ETL DENUE (proceso desacoplado)
```

## Módulos

- `frontend/`: Vista; dashboard, consulta, detalle y pantalla de predicción.
- `backend/app/api/routes/`: Controladores HTTP.
- `backend/app/services/`: Lógica de negocio y consultas agregadas.
- `backend/app/db/`: conexión/persistencia.
- `etl/`: extracción/carga inicial DENUE.
- `db/init/`: esquema e índices reproducibles.
- `scripts/`: respaldo/restauración.
- `.github/workflows/`: integración continua.

## Decisiones de la primera entrega

1. Se conserva FastAPI + Python + PostgreSQL/PostGIS + HTML/CSS/JS + Leaflet, como define el documento.
2. No se simula un modelo predictivo. El endpoint existe y ya calcula el entorno espacial; cuando el artefacto de ML esté disponible se conecta mediante el servicio `prediction_service.py`.
3. El frontend consume solamente REST/JSON/GeoJSON.
4. Nginx sirve el frontend y actúa como reverse proxy, por lo que todo puede publicarse detrás de un solo host.
5. La base se respalda con `pg_dump` y el código con Git/GitHub.
