"""
Router: Predicción de riesgo académico.
Sprint 4 — scoring heurístico determinista sobre métricas académicas.
Estrategia de IA: APIs externas (LLM), sin modelos de ML locales. Cualquier
enriquecimiento futuro (explicaciones / recomendaciones) se delega a la API externa.
"""
from fastapi import APIRouter, Depends

from app.schemas.ia_schemas import (
    ApiResponse,
    EstudianteRiesgoInput,
    EstudianteRiesgoOutput,
    RiesgoInstitucionResponse,
)
from app.dependencies import verify_jwt

router = APIRouter(prefix="/api/ia", tags=["Riesgo Académico"])


def _calcular_nivel(prob: float) -> str:
    if prob >= 0.75:
        return "CRITICO"
    if prob >= 0.50:
        return "ALTO"
    if prob >= 0.25:
        return "MEDIO"
    return "BAJO"


def _predecir_individual(est: EstudianteRiesgoInput) -> EstudianteRiesgoOutput:
    """
    Scoring heurístico determinista basado en asistencia, promedio, historial de
    reprobación y evaluaciones pendientes. No usa modelos locales; para análisis
    cualitativo más rico se delega a la API externa de LLM.
    """
    score = 0.0
    factores = []

    if est.porcentaje_asistencia < 60:
        score += 0.40
        factores.append(f"Asistencia crítica ({est.porcentaje_asistencia:.1f}%)")
    elif est.porcentaje_asistencia < 75:
        score += 0.20
        factores.append(f"Asistencia baja ({est.porcentaje_asistencia:.1f}%)")

    if est.promedio_calificaciones < 51:
        score += 0.35
        factores.append(f"Promedio reprobatorio ({est.promedio_calificaciones:.1f})")
    elif est.promedio_calificaciones < 65:
        score += 0.15
        factores.append(f"Promedio bajo ({est.promedio_calificaciones:.1f})")

    if est.materias_reprobadas_historial >= 3:
        score += 0.15
        factores.append(f"Historial de reprobación ({est.materias_reprobadas_historial} materias)")

    if est.evaluaciones_pendientes >= 2:
        score += 0.10
        factores.append(f"{est.evaluaciones_pendientes} evaluaciones pendientes")

    prob = min(score, 1.0)
    return EstudianteRiesgoOutput(
        id_estudiante=est.id_estudiante,
        nivel_riesgo=_calcular_nivel(prob),
        probabilidad_riesgo=round(prob, 3),
        factores_principales=factores,
    )


@router.post("/riesgo/predecir", response_model=ApiResponse)
async def predecir_riesgo(
    estudiantes: list[EstudianteRiesgoInput],
    _user: dict = Depends(verify_jwt),
):
    """
    Predice el nivel de riesgo académico para una lista de estudiantes.
    Devuelve nivel (BAJO/MEDIO/ALTO/CRITICO), probabilidad y factores principales.
    """
    resultados = [_predecir_individual(e) for e in estudiantes]
    return ApiResponse.ok(
        f"Predicción completada para {len(resultados)} estudiantes",
        [r.model_dump() for r in resultados],
    )
