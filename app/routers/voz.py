"""
Router: Transcripción de voz a texto.
Sprint 3/4 — usa la API de transcripción externa de OpenAI (modelo whisper-1).
No se cargan modelos locales: toda la inferencia ocurre en el proveedor externo.
"""
import io
import logging

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException

from app.schemas.ia_schemas import ApiResponse, TranscripcionResponse
from app.dependencies import verify_jwt
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ia", tags=["Voz"])

_MAX_BYTES = 25 * 1024 * 1024  # 25 MB (límite de la API de OpenAI)


@router.post("/transcribir", response_model=ApiResponse)
async def transcribir_audio(
    archivo: UploadFile = File(...),
    _user: dict = Depends(verify_jwt),
):
    """
    Transcribe un archivo de audio (wav, mp3, m4a, ogg) a texto usando la API
    externa de OpenAI. El resultado puede enviarse a /api/ia/reporte/interpretar
    para construir filtros de reporte de forma conversacional.
    """
    filename = archivo.filename or "audio.wav"
    logger.info("transcribir_audio: file=%s", filename)

    if not settings.openai_api_key:
        logger.warning("transcribir_audio: OPENAI_API_KEY no configurado")
        raise HTTPException(status_code=501, detail="OPENAI_API_KEY no configurado en FastAPI")

    contenido = await archivo.read()
    if len(contenido) > _MAX_BYTES:
        logger.warning("transcribir_audio: file too large — %d bytes", len(contenido))
        raise HTTPException(status_code=413, detail="El archivo supera el límite de 25 MB")

    logger.info("transcribir_audio: sending %d bytes to Whisper (model=whisper-1)", len(contenido))

    from openai import AsyncOpenAI  # type: ignore

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    buffer = io.BytesIO(contenido)
    buffer.name = filename

    try:
        resultado = await client.audio.transcriptions.create(
            model="whisper-1",
            file=buffer,
            response_format="verbose_json",
        )
    except Exception as exc:
        logger.error("transcribir_audio: OpenAI API error — %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Error al transcribir con OpenAI: {exc}")

    texto = getattr(resultado, "text", "").strip()
    idioma = getattr(resultado, "language", None)
    duracion = getattr(resultado, "duration", None)

    logger.info("transcribir_audio: transcribed %d chars (lang=%s, duration=%ss)",
                len(texto), idioma, duracion)

    data = TranscripcionResponse(
        texto=texto,
        idioma=idioma,
        duracion_segundos=float(duracion) if duracion is not None else None,
    )
    return ApiResponse.ok("Transcripción completada", data.model_dump())
