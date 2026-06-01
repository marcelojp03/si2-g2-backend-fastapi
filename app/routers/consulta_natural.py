"""
Router: Reporte por consulta en lenguaje natural (texto).
Pipeline: texto -> LLM (gpt-4o-mini) -> SQL (solo SELECT) -> ejecucion BD -> resultados.

Seguridad:
- Solo SELECT permitido; se rechaza cualquier DML/DDL.
- id_institucion extraido del JWT (multi-tenant enforced).
- LIMIT maximo 200 filas.
- Schema hardcodeado (no se expone estructura de otras instituciones).
"""
import re
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.dependencies import verify_jwt
from app.schemas.ia_schemas import ApiResponse, ConsultaNaturalRequest

router = APIRouter(prefix="/api/ia", tags=["Consulta Natural"])

# ── Esquema fijo del dominio SIA (multi-tenant) ────────────────────────────────

_SCHEMA_SIA = """
Tablas disponibles (schema: sia, PostgreSQL):
1.  sia.institucion         (id, nombre, codigo, estado, creado_en)
2.  sia.usuario             (id, id_institucion, nombre, apellido, correo, estado, creado_en)
3.  sia.rol                 (id, nombre, codigo, es_global)
4.  sia.usuario_rol         (id_usuario, id_rol, id_institucion)
5.  sia.gestion_academica   (id, id_institucion, nombre, anio, periodo, fecha_inicio, fecha_fin, estado)
6.  sia.curso               (id, id_institucion, nombre, nivel, turno, estado)
7.  sia.paralelo            (id, id_institucion, id_curso, id_gestion_academica, nombre, capacidad, estado)
8.  sia.materia             (id, id_institucion, nombre, codigo, horas_semana, estado)
9.  sia.curso_materia       (id, id_institucion, id_curso, id_materia)
10. sia.docente             (id, id_institucion, id_usuario, especialidad, estado)
11. sia.estudiante          (id, id_institucion, id_usuario, codigo_estudiante, estado)
12. sia.tutor               (id, id_institucion, id_usuario, relacion, estado)
13. sia.inscripcion         (id, id_institucion, id_estudiante, id_paralelo, id_gestion_academica, fecha_inscripcion, estado)
14. sia.asignacion_docente  (id, id_institucion, id_docente, id_paralelo, id_materia, id_gestion_academica, estado)
15. sia.aula                (id, id_institucion, codigo, nombre, tipo_aula, capacidad, ubicacion, estado)
16. sia.horario             (id, id_institucion, id_gestion_academica, id_paralelo, id_materia, id_docente, id_aula, dia_semana, hora_inicio, hora_fin, estado)
17. sia.sesion_asistencia   (id, id_institucion, id_paralelo, id_materia, id_docente, id_gestion_academica, id_horario, fecha, hora_inicio, hora_fin, estado, observacion)
18. sia.registro_asistencia (id, id_institucion, id_sesion_asistencia, id_estudiante, estado_asistencia, observacion, creado_en)
19. sia.tipo_evaluacion     (id, id_institucion, nombre, descripcion, porcentaje, estado)
20. sia.evaluacion          (id, id_institucion, id_paralelo, id_materia, id_docente, id_tipo_evaluacion, id_gestion_academica, nombre, fecha, nota_maxima, estado)
21. sia.registro_calificacion (id, id_institucion, id_evaluacion, id_estudiante, nota, estado, creado_en)

Notas:
- Todas las tablas tienen id_institucion para aislamiento multi-tenant.
- estado_asistencia: 'PRESENTE' | 'AUSENTE' | 'TARDE' | 'JUSTIFICADO'
- estado general: 'ACTIVO' | 'INACTIVO' | 'ABIERTA' | 'CERRADA' | 'PENDIENTE' | 'REGISTRADA'
- Para nombres de personas usa JOIN con sia.usuario (nombre, apellido).
- dia_semana en horario: 'LUNES' | 'MARTES' | 'MIERCOLES' | 'JUEVES' | 'VIERNES' | 'SABADO'
"""

_SYSTEM_PROMPT = (
    "Eres un experto en PostgreSQL para un sistema de gestion academica universitaria.\n"
    "Convierte la pregunta del usuario a SQL valido para PostgreSQL schema 'sia'.\n\n"
    "REGLAS OBLIGATORIAS:\n"
    "1. Devuelve SOLO codigo SQL puro: sin explicaciones, sin markdown, sin ```.\n"
    "2. La consulta DEBE empezar exactamente con SELECT.\n"
    "3. SIEMPRE filtra por id_institucion = {id_institucion} en la tabla principal.\n"
    "4. SIEMPRE termina con LIMIT {limit}.\n"
    "5. Usa ILIKE para busquedas de texto (insensible a mayusculas).\n"
    "6. Prefija TODAS las tablas con 'sia.' (ej: sia.estudiante, sia.inscripcion).\n"
    "7. NUNCA uses: UPDATE, INSERT, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE.\n"
    "8. Si necesitas nombre/apellido del estudiante o docente, haz JOIN con sia.usuario.\n"
    "9. Para calcular porcentaje de asistencia: "
    "COUNT(CASE WHEN estado_asistencia='PRESENTE' THEN 1 END) * 100.0 / COUNT(*).\n"
)

_CORRECTION_SYSTEM = (
    "Eres un experto en PostgreSQL que corrige consultas SQL para el schema 'sia'.\n"
    "Devuelve SOLO el SQL corregido, sin explicaciones ni markdown.\n"
    "La consulta debe empezar con SELECT, filtrar por id_institucion = {id_institucion} "
    "y terminar con LIMIT {limit}."
)

# ── Helpers ────────────────────────────────────────────────────────────────────

_FORBIDDEN = re.compile(
    r"\b(UPDATE|INSERT|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


def _clean_sql(raw: str) -> str:
    """Elimina markdown code fences y espacios extra."""
    raw = re.sub(r"```(?:sql)?", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"```", "", raw)
    return raw.strip()


def _validate_sql(sql: str) -> None:
    """Valida que sea solo SELECT y sin DML/DDL peligroso."""
    stripped = sql.strip()
    if not stripped.upper().startswith("SELECT"):
        raise HTTPException(
            status_code=400,
            detail="La IA genero una consulta no permitida (debe iniciar con SELECT).",
        )
    match = _FORBIDDEN.search(stripped)
    if match:
        raise HTTPException(
            status_code=400,
            detail=f"Palabra clave prohibida detectada: {match.group().upper()}",
        )


async def _generate_sql(consulta: str, id_institucion: int, limit: int) -> str:
    """Llama a OpenAI para generar el SQL."""
    if not settings.openai_api_key:
        raise HTTPException(status_code=501, detail="OPENAI_API_KEY no configurado en FastAPI")

    from openai import AsyncOpenAI  # type: ignore

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    system = _SYSTEM_PROMPT.format(id_institucion=id_institucion, limit=limit)
    user_msg = (
        f"Esquema:\n{_SCHEMA_SIA}\n\n"
        f"id_institucion del usuario autenticado: {id_institucion}\n\n"
        f'Consulta del usuario: "{consulta}"\n\nSQL:'
    )

    resp = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        temperature=0,
        max_tokens=512,
    )
    return _clean_sql(resp.choices[0].message.content or "")


async def _correct_sql(bad_sql: str, error: str, id_institucion: int, limit: int) -> str:
    """Pide a la IA que corrija el SQL con error."""
    if not settings.openai_api_key:
        return ""

    from openai import AsyncOpenAI  # type: ignore

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    system = _CORRECTION_SYSTEM.format(id_institucion=id_institucion, limit=limit)
    user_msg = (
        f"SQL con error:\n{bad_sql}\n\n"
        f"Error recibido:\n{error}\n\n"
        f"Esquema:\n{_SCHEMA_SIA}"
    )

    resp = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        temperature=0,
        max_tokens=512,
    )
    return _clean_sql(resp.choices[0].message.content or "")


async def _execute_sql(sql: str) -> dict[str, Any]:
    """Ejecuta el SELECT contra PostgreSQL con asyncpg."""
    if not settings.database_url:
        raise HTTPException(status_code=501, detail="DATABASE_URL no configurado en FastAPI")

    # asyncpg usa dsn postgresql:// (sin sufijos de driver)
    dsn = (
        settings.database_url
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg2://", "postgresql://")
    )

    try:
        conn: asyncpg.Connection = await asyncpg.connect(dsn)
        try:
            rows = await conn.fetch(sql)
            if not rows:
                return {"columnas": [], "filas": [], "total": 0}
            columnas = list(rows[0].keys())
            # asyncpg.Record -> list de valores serializables
            filas = [[str(v) if v is not None else None for v in dict(r).values()] for r in rows]
            return {"columnas": columnas, "filas": filas, "total": len(filas)}
        finally:
            await conn.close()
    except asyncpg.PostgresError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": str(exc)}


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("/reporte/consulta-natural", response_model=ApiResponse)
async def consulta_natural(
    body: ConsultaNaturalRequest,
    user: dict = Depends(verify_jwt),
) -> ApiResponse:
    """
    Convierte una pregunta en lenguaje natural a SQL, lo ejecuta contra
    la BD multi-tenant (schema sia) y devuelve los resultados.

    - El id_institucion se extrae del JWT (no del cuerpo de la peticion).
    - Solo se permiten consultas SELECT con un maximo de 200 filas.
    - Si la IA genera SQL con error, intenta una correccion automatica.
    """
    id_institucion = int(user.get("id_institucion") or 0)
    roles: list = user.get("roles") or []
    if id_institucion == 0 and "SUPER_ADMIN" not in roles:
        raise HTTPException(
            status_code=403,
            detail="id_institucion requerido para ejecutar consultas.",
        )

    limit = min(body.limite or 100, 200)

    # 1. Generar SQL con LLM
    sql = await _generate_sql(body.consulta, id_institucion, limit)
    _validate_sql(sql)

    # 2. Ejecutar SQL
    result = await _execute_sql(sql)

    # 3. Si hay error, intentar autocorreccion una vez
    if "error" in result:
        sql_corregido = await _correct_sql(sql, result["error"], id_institucion, limit)
        if sql_corregido:
            _validate_sql(sql_corregido)
            result = await _execute_sql(sql_corregido)
            sql = sql_corregido

    if "error" in result:
        raise HTTPException(
            status_code=422,
            detail=f"No se pudo ejecutar la consulta generada: {result['error']}",
        )

    return ApiResponse.ok(
        "Consulta ejecutada correctamente",
        {
            "sql_generado": sql,
            "columnas": result["columnas"],
            "filas": result["filas"],
            "total": result["total"],
        },
    )
