from typing import Any
from pydantic import BaseModel


class ApiResponse(BaseModel):
    codigo: int
    mensaje: str
    data: Any = None

    @classmethod
    def ok(cls, mensaje: str, data: Any = None) -> "ApiResponse":
        return cls(codigo=200, mensaje=mensaje, data=data)

    @classmethod
    def created(cls, mensaje: str, data: Any = None) -> "ApiResponse":
        return cls(codigo=201, mensaje=mensaje, data=data)


# ── Voz ────────────────────────────────────────────────────────────────────────

class TranscripcionResponse(BaseModel):
    texto: str
    idioma: str | None = None
    duracion_segundos: float | None = None


# ── Reportes IA ────────────────────────────────────────────────────────────────

class FiltroReporte(BaseModel):
    campo: str
    operador: str          # EQ | CONTAINS | GT | LT | BETWEEN | IN
    valor: str | list[str]


class InterpretacionRequest(BaseModel):
    texto: str             # consulta en lenguaje natural del usuario
    entidad: str           # "asistencia" | "calificacion" | "inscripcion"


# ── Consulta natural -> SQL -> resultados ──────────────────────────────────────

class ConsultaNaturalRequest(BaseModel):
    consulta: str          # pregunta en lenguaje natural del usuario
    limite: int | None = 100   # max filas (el servidor limita a 200)


class InterpretacionResponse(BaseModel):
    filtros: list[FiltroReporte]
    columnas_sugeridas: list[str] = []
    confianza: float = 0.0
    texto_original: str


# ── Riesgo académico ───────────────────────────────────────────────────────────

class EstudianteRiesgoInput(BaseModel):
    id_estudiante: str
    porcentaje_asistencia: float
    promedio_calificaciones: float
    evaluaciones_pendientes: int
    materias_reprobadas_historial: int


class EstudianteRiesgoOutput(BaseModel):
    id_estudiante: str
    nivel_riesgo: str      # BAJO | MEDIO | ALTO | CRITICO
    probabilidad_riesgo: float
    factores_principales: list[str]


class RiesgoInstitucionResponse(BaseModel):
    id_institucion: str
    total_estudiantes: int
    en_riesgo_alto: int
    en_riesgo_critico: int
    estudiantes: list[EstudianteRiesgoOutput]


# ── NL → Reporte handler ───────────────────────────────────────────────────────

class NlAReporteRequest(BaseModel):
    consulta: str          # pregunta en lenguaje natural del usuario


class NlAReporteResponse(BaseModel):
    codigo_reporte: str                   # código del handler (ej: ASISTENCIA_MENSUAL) o "ERROR"
    filtros: dict[str, Any] = {}          # filtros no-UUID: mes, sortBy, promedioMaximo, etc.
    materia_query: str | None = None      # nombre de materia mencionado (Java lo resuelve a UUID)
    curso_query: str | None = None        # nombre de curso mencionado
    docente_query: str | None = None      # nombre/apellido de docente mencionado
    confianza: float = 0.0
    mensaje_error: str | None = None      # solo si codigo_reporte == "ERROR"
