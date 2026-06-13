import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.logging import setup_logging
from app.middlewares.access_log import AccessLogMiddleware
from app.middlewares.error_handler import ErrorHandlerMiddleware
from app.routers import voz, reporte_ia, riesgo, consulta_natural, alertas

logger = logging.getLogger(__name__)

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("FastAPI started — environment=%s port=%d model=%s",
                settings.environment, settings.port, settings.openai_model)
    yield
    logger.info("FastAPI shutting down")


app = FastAPI(
    title="SI2 G2 — Backend IA",
    description="Servicios de Inteligencia Artificial para el Sistema de Gestión Académica SaaS",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
)

# CORS: permite peticiones desde el frontend Angular y el backend Spring Boot
_cors_origins = [
    "http://localhost:4200",
    "http://localhost:2026",
    "https://d32gr4vkubb6g5.cloudfront.net",
    settings.backend_spring_url,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(ErrorHandlerMiddleware)

app.include_router(voz.router)
app.include_router(reporte_ia.router)
app.include_router(riesgo.router)
app.include_router(consulta_natural.router)
app.include_router(alertas.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "si2-g2-backend-fastapi"}
