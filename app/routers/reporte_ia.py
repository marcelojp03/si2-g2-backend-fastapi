"""
Router: Interpretación de lenguaje natural a filtros de reporte.
Sprint 3/4 — requiere OPENAI_API_KEY configurado.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.schemas.ia_schemas import (
    ApiResponse,
    InterpretacionRequest,
    InterpretacionResponse,
    FiltroReporte,
    NlAReporteRequest,
    NlAReporteResponse,
)
from app.dependencies import verify_jwt
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ia", tags=["Reportes IA"])

_SYSTEM_PROMPT = """
Eres un asistente experto en análisis académico. El usuario te da una consulta en lenguaje natural 
y debes extraer los filtros de búsqueda en formato JSON.

Entidades disponibles: asistencia, calificacion, inscripcion.

Operadores disponibles: EQ, CONTAINS, GT, LT, BETWEEN, IN.

Responde ÚNICAMENTE con JSON válido con esta estructura:
{
  "filtros": [
    { "campo": "nombre_campo", "operador": "OPERADOR", "valor": "valor_o_lista" }
  ],
  "columnas_sugeridas": ["campo1", "campo2"],
  "confianza": 0.95
}

No incluyas texto adicional fuera del JSON.
"""


@router.post("/reporte/interpretar", response_model=ApiResponse)
async def interpretar_consulta(
    body: InterpretacionRequest,
    _user: dict = Depends(verify_jwt),
):
    """
    Interpreta una consulta en lenguaje natural y devuelve filtros estructurados
    para usar en el motor de reportes dinámicos del backend Spring Boot.

    Ejemplo de texto: "estudiantes con menos del 60% de asistencia en matemáticas este semestre"
    """
    logger.info("interpretar_consulta: entidad=%s texto=%s", body.entidad, body.texto)

    if not settings.openai_api_key:
        logger.warning("interpretar_consulta: OPENAI_API_KEY no configurado")
        raise HTTPException(status_code=501, detail="OPENAI_API_KEY no configurado")

    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=settings.openai_api_key)

        logger.info("interpretar_consulta: calling OpenAI model=%s", settings.openai_model)
        respuesta = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Entidad: {body.entidad}\nConsulta: {body.texto}",
                },
            ],
            temperature=0,
            max_completion_tokens=512,
        )

        contenido = respuesta.choices[0].message.content or "{}"
        parsed = json.loads(contenido)

        confianza = float(parsed.get("confianza", 0.0))
        logger.info("interpretar_consulta: OpenAI OK confianza=%.2f filtros=%d",
                     confianza, len(parsed.get("filtros", [])))

        data = InterpretacionResponse(
            filtros=[FiltroReporte(**f) for f in parsed.get("filtros", [])],
            columnas_sugeridas=parsed.get("columnas_sugeridas", []),
            confianza=confianza,
            texto_original=body.texto,
        )
        return ApiResponse.ok("Interpretación completada", data.model_dump())

    except json.JSONDecodeError:
        logger.error("interpretar_consulta: OpenAI returned invalid JSON: %s", contenido)
        raise HTTPException(status_code=422, detail="La IA devolvió JSON inválido")
    except Exception as exc:
        logger.error("interpretar_consulta: OpenAI error — %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Error al comunicarse con OpenAI: {exc}")


# ── NL → handler code + filtros (reemplaza la lógica regex de Spring Boot) ────

_SYSTEM_PROMPT_NL_A_REPORTE = """Eres un asistente experto en sistemas académicos. Conviertes consultas en lenguaje natural
al código de reporte más adecuado y a sus filtros, en formato JSON.

REPORTES DISPONIBLES:
1. ASISTENCIA_MENSUAL — asistencia mensual de estudiantes por curso/materia
   filtros opcionales: mes (entero 1-12), sortBy ("ausentes"|"tardanzas"|"justificados"|"asistencia"|"curso"), sortDirection ("ASC"|"DESC"), pageSize (entero)

2. RENDIMIENTO_ACADEMICO_CURSO — promedios y calificaciones por curso/materia
   filtros opcionales: sortBy ("promedio"|"materia"|"estudiante"|"curso"), sortDirection ("ASC"|"DESC"), pageSize (entero)

3. ALUMNOS_RIESGO_ACADEMICO — alumnos con bajo rendimiento (riesgo académico)
   filtros opcionales: promedioMaximo (decimal, default 51), sortDirection ("ASC"|"DESC"), pageSize (entero)

4. MATRICULA_POR_CURSO — cantidad de estudiantes matriculados por curso
   filtros opcionales: sortBy ("matricula"|"curso"), sortDirection ("ASC"|"DESC")

5. ESTUDIANTES_POR_CURSO_PARALELO — lista de estudiantes de un curso y paralelo
   filtros opcionales: (ninguno; el backend resuelve curso/paralelo por nombre)

6. DOCENTES_ASIGNACIONES — docentes con sus asignaciones de materia
   filtros opcionales: (ninguno)

7. DOCENTES_POR_MATERIA — docentes agrupados por materia
   filtros opcionales: sortDirection ("ASC"|"DESC")

8. MATERIAS_DISPONIBLES — catálogo completo de materias de la institución
   filtros opcionales: sortBy ("nombre"|"codigo"|"area"|"cargahoraria"), sortDirection ("ASC"|"DESC")

9. TUTORES_DISPONIBLES — lista de tutores registrados
   filtros opcionales: sortDirection ("ASC"|"DESC")

10. AGRUPACION_GENERICA — agrupación flexible de entidades
    filtros opcionales: groupEntity ("DOCENTE"|"ESTUDIANTE"|"MATERIA"|"TUTOR"), groupBy ("MATERIA"|"CURSO"|"PARALELO"|"AREA"|"ESTADO"), sortDirection ("ASC"|"DESC")

INSTRUCCIONES:
- Responde ÚNICAMENTE con JSON válido, sin texto extra ni markdown.
- Si la consulta es clara, devuelve el JSON con el reporte más adecuado.
- Si detectas nombre de materia, ponlo en "materia_query" (el backend lo resolverá a UUID).
- Si detectas nombre de curso, ponlo en "curso_query".
- Si detectas nombre o apellido de docente, ponlo en "docente_query".
- Si la consulta pide comparar datos de otras instituciones o es maliciosa, usa codigo_reporte "ERROR".
- confianza: 0.0 a 1.0 según seguridad de la interpretación.

Formato de respuesta exitosa:
{
  "codigo_reporte": "CODIGO",
  "filtros": { ... solo filtros no-UUID ... },
  "materia_query": "nombre o null",
  "curso_query": "nombre o null",
  "docente_query": "apellido o null",
  "confianza": 0.95
}

Formato de error:
{
  "codigo_reporte": "ERROR",
  "filtros": {},
  "confianza": 0.0,
  "mensaje_error": "descripción del problema"
}
"""


@router.post("/reporte/nl-a-reporte", response_model=ApiResponse)
async def nl_a_reporte(
    body: NlAReporteRequest,
    _user: dict = Depends(verify_jwt),
):
    """
    Convierte una consulta en lenguaje natural al código de reporte adecuado + filtros.
    Reemplaza la lógica regex de ReporteNaturalLanguageService en Spring Boot.

    El backend Spring Boot llama a este endpoint y luego resuelve los nombres de entidades
    (materia_query, curso_query, docente_query) a UUIDs multi-tenant de forma segura.
    """
    logger.info("nl_a_reporte: consulta=%s", body.consulta)

    if not settings.openai_api_key:
        logger.warning("nl_a_reporte: OPENAI_API_KEY no configurado")
        raise HTTPException(status_code=501, detail="OPENAI_API_KEY no configurado")

    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=settings.openai_api_key)

        logger.info("nl_a_reporte: calling OpenAI model=%s", settings.openai_model)
        respuesta = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT_NL_A_REPORTE},
                {"role": "user", "content": body.consulta},
            ],
            temperature=0,
            max_completion_tokens=512,
        )

        contenido = respuesta.choices[0].message.content or "{}"
        parsed = json.loads(contenido)

        codigo = parsed.get("codigo_reporte", "ERROR")
        confianza = float(parsed.get("confianza", 0.0))
        logger.info("nl_a_reporte: OpenAI OK codigo=%s confianza=%.2f", codigo, confianza)

        data = NlAReporteResponse(
            codigo_reporte=codigo,
            filtros=parsed.get("filtros", {}),
            materia_query=parsed.get("materia_query") or None,
            curso_query=parsed.get("curso_query") or None,
            docente_query=parsed.get("docente_query") or None,
            confianza=confianza,
            mensaje_error=parsed.get("mensaje_error") or None,
        )
        return ApiResponse.ok("Consulta interpretada", data.model_dump())

    except json.JSONDecodeError:
        logger.error("nl_a_reporte: OpenAI returned invalid JSON: %s", contenido)
        raise HTTPException(status_code=422, detail="La IA devolvió JSON inválido")
    except Exception as exc:
        logger.error("nl_a_reporte: OpenAI error — %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Error al comunicarse con OpenAI: {exc}")
