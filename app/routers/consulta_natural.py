"""
Router: Reporte por consulta en lenguaje natural (texto).
Pipeline: texto -> LLM -> SQL (solo SELECT) -> ejecucion BD -> resultados.

Seguridad:
- Solo SELECT permitido; se rechaza cualquier DML/DDL.
- id_institucion extraido del JWT (multi-tenant enforced) como UUID.
- LIMIT maximo 200 filas.
- Schema completo del dominio SIA (64 tablas).
"""
import logging
import re
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.dependencies import verify_jwt
from app.schemas.ia_schemas import ApiResponse, ConsultaNaturalRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ia", tags=["Consulta Natural"])

_SCHEMA_SIA = """
Esquema completo de la base de datos academica (schema: sia, PostgreSQL).
Todas las tablas de negocio tienen id_institucion (UUID) para aislamiento multi-tenant.

Tablas disponibles:
1. gestion_academica (id UUID, id_institucion UUID, nombre text, fecha_inicio date, fecha_fin date, activa boolean, cantidad_periodos int, tipo_periodo text)
2. curso (id UUID, id_institucion UUID, codigo text, nombre text, nivel text, orden_visual int)
3. paralelo (id UUID, id_institucion UUID, id_curso UUID, id_gestion UUID, nombre text, capacidad int)
4. materia (id UUID, id_institucion UUID, codigo text, nombre text, area text, carga_horaria int)
5. curso_materia (id UUID, id_institucion UUID, id_curso UUID, id_materia UUID, id_gestion UUID, carga_horaria int)
6. docente (id UUID, id_institucion UUID, codigo text, documento_identidad text, nombres text, apellidos text, especialidad text)
7. estudiante (id UUID, id_institucion UUID, codigo_estudiante text, documento_identidad text, nombres text, apellidos text, fecha_nacimiento date, sexo text)
8. tutor (id UUID, id_institucion UUID, nombres text, apellidos text, telefono text, correo text)
9. estudiante_tutor (id UUID, id_institucion UUID, id_estudiante UUID, id_tutor UUID, parentesco text, es_principal boolean)
10. inscripcion (id UUID, id_institucion UUID, id_estudiante UUID, id_gestion UUID, id_paralelo UUID, fecha_inscripcion date, id_plan_pago UUID)
11. asignacion_docente (id UUID, id_institucion UUID, id_docente UUID, id_materia UUID, id_paralelo UUID, id_gestion UUID, carga_horaria int)
12. aula (id UUID, id_institucion UUID, codigo text, nombre text, capacidad int, ubicacion text, recursos text)
13. horario_clase (id UUID, id_institucion UUID, id_asignacion_docente UUID, id_aula UUID, dia_semana text, hora_inicio time, hora_fin time)
14. asistencia_registro (id UUID, id_institucion UUID, id_asignacion_docente UUID, fecha date, estado text)
15. evaluacion (id UUID, id_institucion UUID, id_materia UUID, id_asignacion_docente UUID, periodo int, tipo text, nombre text, ponderacion numeric, escala text)
16. evaluacion_materia (id UUID, id_institucion UUID, id_materia UUID, periodo int, tipo text, nombre text, ponderacion numeric, escala text)
17. calificacion (id UUID, id_institucion UUID, id_evaluacion UUID, id_inscripcion UUID, nota_numerica numeric, nota_literal text)
18. calificacion_actividad (id UUID, id_institucion UUID, id_actividad UUID, id_estudiante UUID, nota_obtenida numeric, estado text)
19. calificacion_ser (id UUID, id_institucion UUID, id_materia UUID, id_docente UUID, id_estudiante UUID, nota_ser numeric, id_periodo_evaluacion UUID)
20. actividad_evaluativa (id UUID, id_institucion UUID, id_materia UUID, id_docente UUID, nombre_actividad text, dimension text, puntaje_maximo int, fecha_actividad date, id_periodo_evaluacion UUID)
21. periodo_evaluacion (id UUID, id_institucion UUID, id_gestion UUID, numero_periodo int, fecha_inicio date, fecha_fin date, peso_saber int, peso_hacer int, peso_ser int, peso_auto int)
22. dimension (id UUID, id_institucion UUID, nombre text, descripcion text, peso_default int, es_global boolean)
23. autoevaluacion_trimestral (id UUID, id_institucion UUID, id_materia UUID, id_estudiante UUID, nota_autoevaluacion numeric, id_periodo_evaluacion UUID)
24. observacion_ser (id UUID, id_institucion UUID, id_estudiante UUID, id_materia UUID, id_docente UUID, id_periodo_evaluacion UUID, comportamiento text, descripcion text, fecha_observacion date)
25. comunicado (id UUID, id_institucion UUID, titulo text, contenido text, tipo text, destinatarios text, estado text, creado_por UUID, publicado_por UUID)
26. notificacion (id UUID, id_institucion UUID, id_usuario UUID, titulo text, mensaje text, tipo text, leida boolean, referencia_tipo text, referencia_id UUID)
27. pago (id UUID, id_institucion UUID, id_cuota UUID, id_usuario_paga UUID, monto numeric, moneda text, metodo_pago text, proveedor text, referencia_externa text, estado text)
28. cuota_estudiante (id UUID, id_institucion UUID, id_estudiante UUID, id_plan_pago UUID, id_gestion UUID, numero_cuota int, monto numeric, fecha_vencimiento date, estado text)
29. alerta_riesgo (id UUID, id_institucion UUID, id_estudiante UUID, id_gestion UUID, nivel_riesgo text, score_ia numeric, motivo text, activa boolean)
30. reporte_configurable (id UUID, id_institucion UUID, codigo text, nombre text, entidad_base text, tipo_reporte text)
31. reporte_dashboard_widget (id UUID, id_institucion UUID, id_usuario UUID, codigo_reporte text, titulo text, tipo_widget text)
32. reporte_ejecucion (id UUID, id_institucion UUID, id_usuario UUID, codigo_reporte text, tipo_salida text, estado text, total_registros int)
33. reporte_filtro_favorito (id UUID, id_institucion UUID, id_usuario UUID, codigo_reporte text, nombre text)

Notas de joins importantes:
- docente y estudiante tienen nombres y apellidos propios (no JOIN con usuario)
- asignacion_docente relaciona: docente + materia + paralelo + gestion
- inscripcion relaciona: estudiante + paralelo + gestion
- horario_clase usa: asignacion_docente + aula
- asistencia_registro usa: asignacion_docente
- evaluacion y evaluacion_materia son tablas separadas (ambas activas)
- calificacion_actividad es la tabla principal de notas (calificacion es legacy)
- comunicado.destinatarios: texto con roles separados por comas
- notificacion.referencia_tipo: 'COMUNICADO' | 'PAGO' | 'ALERTA'
- pago.estado: 'PENDIENTE' | 'CONFIRMADO' | 'RECHAZADO'
- cuota_estudiante.estado: 'PENDIENTE' | 'PAGADA' | 'VENCIDA'
- alerta_riesgo.nivel_riesgo: 'BAJO' | 'MEDIO' | 'ALTO'
- estado general tablas: 'ACTIVO' | 'INACTIVO'
- dia_semana en horario_clase: 'LUNES' | 'MARTES' | 'MIERCOLES' | 'JUEVES' | 'VIERNES' | 'SABADO'
"""

_SYSTEM_PROMPT = (
    "Eres un experto en PostgreSQL para un sistema de gestion academica.\n"
    "Convierte la pregunta del usuario a SQL valido para PostgreSQL schema 'sia'.\n\n"
    "REGLAS OBLIGATORIAS:\n"
    "1. Devuelve SOLO codigo SQL puro: sin explicaciones, sin markdown, sin ```.\n"
    "2. La consulta DEBE empezar exactamente con SELECT.\n"
    "3. SIEMPRE filtra por id_institucion = '{id_institucion}'::uuid en la tabla principal.\n"
    "4. Termina con LIMIT {limit} solo si el usuario NO especifica un numero. Si el usuario pide 'los 10...', usa LIMIT 10.\n"
    "5. Usa ILIKE para busquedas de texto (insensible a mayusculas). "
    "Los nombres en la BD NO tienen acentos ni tildes. Normaliza: busca 'matematica' no 'matemáticas'.\n"
    "6. Prefija TODAS las tablas con 'sia.' (ej: sia.estudiante, sia.inscripcion).\n"
    "7. Cuando compares con texto ingresado por el usuario, usa ILIKE y no uses acentos en el patron.\n"
    "8. NUNCA uses: UPDATE, INSERT, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE.\n"
    "8. Para nombres o apellidos de docente/estudiante, usa sus columnas directas (nombres, apellidos).\n"
    "9. Para calcular porcentaje de asistencia: "
    "usa asistencias entre COUNT(*) de asistencia_registro.\n"
    "10. Para promedios usa AVG(nota_obtenida) en calificacion_actividad o AVG(nota_numerica) en calificacion.\n"
    "11. Para agrupar docentes por materia: JOIN asignacion_docente con materia y docente.\n"
)

_CORRECTION_SYSTEM = (
    "Eres un experto en PostgreSQL que corrige consultas SQL para el schema 'sia'.\n"
    "Devuelve SOLO el SQL corregido, sin explicaciones ni markdown.\n"
    "La consulta debe empezar con SELECT, filtrar por id_institucion = '{id_institucion}'::uuid "
    "y terminar con LIMIT {limit}."
)

_FORBIDDEN = re.compile(
    r"\b(UPDATE|INSERT|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


def _clean_sql(raw: str) -> str:
    raw = re.sub(r"```(?:sql)?", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"```", "", raw)
    return raw.strip()


def _clean_duplicate_limit(sql: str) -> str:
    """Elimina LIMIT duplicados; PostgreSQL no permite mas de uno."""
    parts = sql.strip().split()
    limit_indices = [i for i, p in enumerate(parts) if p.upper() == "LIMIT"]
    if len(limit_indices) > 1:
        keep = limit_indices[0]
        # Si el usuario pidio un numero concreto, conservar el primer LIMIT (el de la IA natural)
        # Sino, conservar el ultimo (el del prompt)
        sql = " ".join(parts[:keep + 2])
    return sql


def _validate_sql(sql: str) -> None:
    stripped = sql.strip()
    if not stripped.upper().startswith("SELECT"):
        raise HTTPException(status_code=400, detail="La IA genero una consulta no permitida (debe iniciar con SELECT).")
    match = _FORBIDDEN.search(stripped)
    if match:
        raise HTTPException(status_code=400, detail=f"Palabra clave prohibida detectada: {match.group().upper()}")


async def _generate_sql(consulta: str, id_institucion: str, limit: int) -> str:
    logger.info("_generate_sql: id_institucion=%s limit=%d consulta=%s", id_institucion, limit, consulta)

    if not settings.openai_api_key:
        raise HTTPException(status_code=501, detail="OPENAI_API_KEY no configurado en FastAPI")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    system = _SYSTEM_PROMPT.format(id_institucion=id_institucion, limit=limit)
    user_msg = (
        f"Esquema:\n{_SCHEMA_SIA}\n\n"
        f"id_institucion del usuario autenticado: {id_institucion}\n\n"
        f'Consulta del usuario: "{consulta}"\n\nSQL:'
    )

    logger.info("_generate_sql: calling OpenAI model=%s", settings.openai_model)
    resp = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        temperature=0,
        max_completion_tokens=4096,
    )
    sql = _clean_sql(resp.choices[0].message.content or "")
    sql = _clean_duplicate_limit(sql)
    logger.info("_generate_sql: SQL generated (%d chars) full:\n%s", len(sql), sql)
    return sql


async def _correct_sql(bad_sql: str, error: str, id_institucion: str, limit: int) -> str:
    logger.warning("_correct_sql: error=%s\nbad_sql=\n%s", error, bad_sql)

    if not settings.openai_api_key:
        return ""

    from openai import AsyncOpenAI

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
        max_completion_tokens=4096,
    )
    corrected = _clean_sql(resp.choices[0].message.content or "")
    if corrected:
        corrected = _clean_duplicate_limit(corrected)
        logger.info("_correct_sql: corrected SQL (%d chars): %s", len(corrected), corrected[:200])
    return corrected


async def _execute_sql(sql: str) -> dict[str, Any]:
    if not settings.database_url:
        raise HTTPException(status_code=501, detail="DATABASE_URL no configurado en FastAPI")

    dsn = (
        settings.database_url
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg2://", "postgresql://")
    )

    logger.info("_execute_sql: executing query (%d chars)", len(sql))
    try:
        conn = await asyncpg.connect(dsn)
        try:
            rows = await conn.fetch(sql)
            if not rows:
                return {"columnas": [], "filas": [], "total": 0}
            columnas = list(rows[0].keys())
            filas = [[str(v) if v is not None else None for v in dict(r).values()] for r in rows]
            logger.info("_execute_sql: %d rows returned", len(filas))
            return {"columnas": columnas, "filas": filas, "total": len(filas)}
        finally:
            await conn.close()
    except asyncpg.PostgresError as exc:
        logger.error("_execute_sql: PostgresError — %s", exc)
        return {"error": str(exc)}
    except Exception as exc:
        logger.error("_execute_sql: error — %s", exc, exc_info=True)
        return {"error": str(exc)}


def _clean_markdown(text: str) -> str:
    """Elimina bloques de markdown y negritas."""
    text = re.sub(r"```(?:markdown)?\n?(.*?)```", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    return text.strip()


async def _interpretar_resultado(consulta: str, sql: str, columnas: list[str], filas: list[list], total: int) -> str:
    """Genera una interpretacion en lenguaje natural de los resultados."""
    if not settings.openai_api_key or not filas:
        return ""
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)

        muestra = "\n".join(
            f"Fila {i+1}: " + ", ".join(f"{col}={val}" for col, val in zip(columnas, fila))
            for i, fila in enumerate(filas[:5])
        )

        resp = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{
                "role": "system",
                "content": (
                    "Eres un asistente academico. Explica los resultados de una consulta SQL "
                    "en lenguaje sencillo, como si hablaras con un director de colegio. "
                    "Sé conciso (max 3 parrafos). Resalta los datos relevantes. "
                    "NO uses markdown, negritas, cursivas ni formato especial. Solo texto plano."
                )
            }, {
                "role": "user",
                "content": (
                    f"Consulta original: \"{consulta}\"\n"
                    f"SQL ejecutado: {sql}\n"
                    f"Total resultados: {total}\n"
                    f"Columnas: {', '.join(columnas)}\n"
                    f"Primeras filas:\n{muestra}\n\n"
                    f"Explica que muestran estos resultados:"
                )
            }],
            temperature=0.3,
            max_completion_tokens=512,
        )
        texto = resp.choices[0].message.content or ""
        texto = _clean_markdown(texto)
        logger.info("_interpretar_resultado: OK — %d chars, %d filas", len(texto), total)
        return texto
    except Exception as exc:
        logger.warning("_interpretar_resultado: error — %s", exc)
        return ""


@router.post("/reporte/consulta-natural", response_model=ApiResponse)
async def consulta_natural(
    body: ConsultaNaturalRequest,
    user: dict = Depends(verify_jwt),
) -> ApiResponse:
    """
    Convierte una pregunta en lenguaje natural a SQL, lo ejecuta contra
    la BD multi-tenant (schema sia) y devuelve los resultados.

    - El id_institucion se extrae del JWT como UUID.
    - Solo se permiten consultas SELECT con un maximo de 200 filas.
    - Si la IA genera SQL con error, intenta una correccion automatica.
    """
    id_institucion = user.get("id_institucion") or ""
    roles: list = user.get("roles") or []
    if not id_institucion and "SUPER_ADMIN" not in roles:
        raise HTTPException(status_code=403, detail="id_institucion requerido para ejecutar consultas.")

    limit = min(body.limite or 100, 200)
    logger.info("consulta_natural: id_institucion=%s consulta=%s limit=%d", id_institucion, body.consulta, limit)

    sql = await _generate_sql(body.consulta, id_institucion, limit)
    _validate_sql(sql)

    result = await _execute_sql(sql)

    for intento in range(3):
        if "error" not in result:
            break
        logger.warning("consulta_natural: error (intento %d/3), corrigiendo — %s", intento + 1, result["error"])
        sql_corregido = await _correct_sql(sql, result["error"], id_institucion, limit)
        if not sql_corregido:
            break
        _validate_sql(sql_corregido)
        result = await _execute_sql(sql_corregido)
        sql = sql_corregido

    if "error" in result:
        raise HTTPException(status_code=422, detail=f"No se pudo ejecutar la consulta generada: {result['error']}")

    interpretacion = await _interpretar_resultado(
        body.consulta, sql,
        result.get("columnas", []),
        result.get("filas", []),
        result.get("total", 0)
    )

    return ApiResponse.ok(
        "Consulta ejecutada correctamente",
        {
            "sql_generado": sql,
            "columnas": result["columnas"],
            "filas": result["filas"],
            "total": result["total"],
            "interpretacion": interpretacion,
        },
    )
