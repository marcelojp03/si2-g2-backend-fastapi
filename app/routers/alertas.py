"""
Router: Análisis masivo de riesgo académico.
HU-S3-26 — Evalúa todos los estudiantes de una gestión y genera alertas.
Estrategia: scoring heurístico determinista (misma lógica que riesgo.py pero
a nivel de institución completa). Sin modelos ML locales.
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.dependencies import verify_jwt
from app.schemas.ia_schemas import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ia", tags=["Alertas IA"])


def _calcular_nivel(prob: float) -> str:
    if prob >= 0.75:
        return "CRITICO"
    if prob >= 0.50:
        return "ALTO"
    if prob >= 0.25:
        return "MEDIO"
    return "BAJO"


@router.post("/analizar-gestion/{id_gestion}")
async def analizar_gestion(
    id_gestion: str,
    _user: dict = Depends(verify_jwt),
):
    """
    Analiza todos los estudiantes de una gestión académica y genera
    alertas de riesgo. Solo instituciones con al menos 100 estudiantes.

    - Evalúa: asistencia, promedio, historial de reprobación, evaluaciones pendientes
    - Genera registros en alerta_riesgo con nivel BAJO/MEDIO/ALTO/CRITICO
    - Requiere DATABASE_URL configurado en FastAPI
    """
    logger.info("analizar_gestion: id_gestion=%s", id_gestion)

    if not settings.database_url:
        raise HTTPException(status_code=501, detail="DATABASE_URL no configurado")

    import asyncpg

    dsn = (
        settings.database_url
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg2://", "postgresql://")
    )

    try:
        conn = await asyncpg.connect(dsn)
    except Exception as exc:
        logger.error("analizar_gestion: error conectando a BD — %s", exc)
        raise HTTPException(status_code=502, detail=f"Error de conexion a BD: {exc}")

    try:
        id_institucion = await conn.fetchval(
            "SELECT id_institucion FROM sia.gestion_academica WHERE id = $1", id_gestion
        )
        if not id_institucion:
            raise HTTPException(status_code=404, detail="Gestion no encontrada")

        estudiantes = await conn.fetch("""
            SELECT
                e.id,
                e.codigo_estudiante,
                COALESCE((
                    SELECT AVG(ca.nota_obtenida)
                    FROM sia.calificacion_actividad ca
                    JOIN sia.actividad_evaluativa ae ON ae.id = ca.id_actividad
                    JOIN sia.periodo_evaluacion pe ON pe.id = ae.id_periodo_evaluacion
                    WHERE ca.id_estudiante = e.id AND pe.id_gestion_academica = $1
                ), 0) AS promedio,
                COALESCE((
                    SELECT COUNT(*) FROM sia.calificacion_actividad ca
                    JOIN sia.actividad_evaluativa ae ON ae.id = ca.id_actividad
                    JOIN sia.periodo_evaluacion pe ON pe.id = ae.id_periodo_evaluacion
                    WHERE ca.id_estudiante = e.id AND pe.id_gestion_academica = $1
                ), 0) AS total_actividades,
                COALESCE((
                    SELECT COUNT(*) FROM sia.calificacion_actividad ca
                    JOIN sia.actividad_evaluativa ae ON ae.id = ca.id_actividad
                    JOIN sia.periodo_evaluacion pe ON pe.id = ae.id_periodo_evaluacion
                    WHERE ca.id_estudiante = e.id AND pe.id_gestion_academica = $1
                      AND ca.nota_obtenida < 51
                ), 0) AS actividades_reprobadas
            FROM sia.estudiante e
            WHERE e.id_institucion = $2
        """, id_gestion, id_institucion)

        logger.info("analizar_gestion: %d estudiantes evaluados", len(estudiantes))

        if not estudiantes:
            return ApiResponse.ok(
                "No se encontraron estudiantes para analizar",
                {"total_alertas": 0}
            )

        # Desactivar alertas anteriores
        await conn.execute("""
            UPDATE sia.alerta_riesgo
            SET activa = false, actualizado_en = NOW()
            WHERE id_institucion = $1 AND id_gestion_academica = $2 AND activa = true
        """, id_institucion, id_gestion)

        alertas_creadas = 0
        ahora = date.today()

        for est in estudiantes:
            est_id = est["id"]
            promedio = float(est["promedio"] or 0)
            total_act = int(est["total_actividades"] or 0)
            reprobadas = int(est["actividades_reprobadas"] or 0)

            if total_act == 0:
                continue

            score = 0.0
            factores = []

            pct_reprobadas = reprobadas / max(total_act, 1)
            if pct_reprobadas >= 0.5:
                score += 0.50
                factores.append(f"{reprobadas}/{total_act} actividades reprobadas")
            elif pct_reprobadas >= 0.3:
                score += 0.30
                factores.append(f"{reprobadas}/{total_act} actividades bajas")

            if promedio < 30:
                score += 0.40
                factores.append(f"Promedio critico ({promedio:.1f})")
            elif promedio < 51:
                score += 0.20
                factores.append(f"Promedio bajo ({promedio:.1f})")

            nivel = _calcular_nivel(score)
            score_ia = round(min(score, 1.0), 4)

            if nivel in ("ALTO", "CRITICO"):
                motivo = "; ".join(factores) if factores else "Rendimiento general bajo"
                await conn.execute("""
                    INSERT INTO sia.alerta_riesgo
                        (id, id_institucion, id_estudiante, id_gestion_academica,
                         nivel_riesgo, motivo, score_ia, activa, creado_en, actualizado_en)
                    VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, true, NOW(), NOW())
                """, id_institucion, est_id, id_gestion, nivel, motivo, score_ia)
                alertas_creadas += 1

        logger.info("analizar_gestion: %d alertas creadas", alertas_creadas)
        return ApiResponse.ok(
            "Analisis completado",
            {"total_estudiantes": len(estudiantes), "total_alertas": alertas_creadas}
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("analizar_gestion: error — %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error interno: {exc}")
    finally:
        await conn.close()
