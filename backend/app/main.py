from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import catalogs, dashboard, health, predictions, units
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API inicial del Sistema de Análisis Económico de la CDMX.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (health.router, catalogs.router, dashboard.router, units.router, predictions.router):
    app.include_router(router, prefix=settings.api_prefix)
