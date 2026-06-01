# SI2 G2 — Backend FastAPI (IA)

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab.svg)](https://www.python.org/)
[![OpenAI](https://img.shields.io/badge/OpenAI-API_externa-412991.svg)](https://openai.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-blue.svg)](https://www.postgresql.org/)

Microservicio de Inteligencia Artificial del Sistema de Gestión Académica SaaS.
Todos los modelos de IA usan **APIs externas de OpenAI** — sin modelos locales, sin sklearn.

---

## Stack

| Capa | Tecnología |
|---|---|
| Framework | FastAPI 0.115 |
| Lenguaje | Python 3.11+ |
| Transcripción de voz | OpenAI `whisper-1` (API externa) |
| Lenguaje natural → SQL / filtros | OpenAI `gpt-4o-mini` (API externa) |
| Scoring de riesgo | Heurístico determinista (asistencia + promedio + historial) |
| Base de datos | SQLAlchemy async + asyncpg → mismo PostgreSQL que Spring Boot |
| Auth | JWT (misma clave que Spring Boot, verificación `python-jose`) |

---

## Routers

| Router | Endpoint Spring Boot | Descripción | Estado |
|---|---|---|---|
| `consulta_natural.py` | `POST /api/ia/consulta` | Texto → SQL via gpt-4o-mini → ejecución BD | ✅ Completado |
| `reporte_ia.py` | `POST /api/ia/reporte/interpretar` | NL → filtros estructurados via gpt-4o-mini | ✅ Completado |
| `voz.py` | `POST /api/ia/transcribir` | Audio → texto via OpenAI whisper-1 API (máx 25 MB) | ✅ Completado |
| `riesgo.py` | `POST /api/ia/riesgo/predecir` | Scoring heurístico de riesgo académico por estudiante | ✅ Completado |
| `alertas.py` | `GET /api/ia/alertas/{idInstitucion}` | Alertas tempranas masivas por gestión | ⬜ Sprint 3 |

Spring Boot actúa como proxy: las rutas `/api/ia/...` se reenvían a este servicio desde `ia/` en Spring Boot.

---

## Requisitos previos

- Python 3.11+
- Acceso a la API de OpenAI (`OPENAI_API_KEY`)
- PostgreSQL 17 (el mismo que usa Spring Boot)

---

## Levantar el servidor

```bash
cd si2-g2-backend-fastapi

# 1. Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux / macOS

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar variables de entorno
cp .env.example .env
# Editar .env con las credenciales reales

# 4. Ejecutar
uvicorn app.main:app --reload --port 8001
```

Docs automáticas disponibles en `http://localhost:8001/docs`.

---

## Variables de entorno

```env
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/sia_db
OPENAI_API_KEY=sk-...
JWT_SECRET=<misma clave que Spring Boot>
BACKEND_SPRING_URL=http://localhost:2026
ENVIRONMENT=development
```

---

## Estructura del proyecto

```
si2-g2-backend-fastapi/
├── app/
│   ├── main.py           — entrada, registro de routers, CORS
│   ├── config.py         — variables de entorno (pydantic-settings)
│   ├── dependencies.py   — JWT verify, DB session
│   ├── routers/
│   │   ├── consulta_natural.py  — texto → SQL → resultados
│   │   ├── reporte_ia.py        — NL → filtros de reporte
│   │   ├── voz.py               — audio → texto (whisper-1)
│   │   ├── riesgo.py            — scoring heurístico de riesgo
│   │   └── alertas.py           — alertas masivas (Sprint 3)
│   └── schemas/          — modelos Pydantic request/response
├── requirements.txt
├── .env.example
└── Dockerfile
```

---

## Deploy

El servicio se conteneriza con Docker y se despliega junto al backend Spring Boot.

```bash
docker build -t si2-fastapi .
docker run -p 8001:8001 --env-file .env si2-fastapi
```

| Entorno | Puerto |
|---|---|
| Local | `http://localhost:8001` |
| Accedido vía Spring Boot | `http://localhost:2026/api/ia/...` |
