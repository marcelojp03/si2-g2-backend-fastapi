"""
Router: Transcripción de voz a texto.
Sprint 3/4 — usa la API de transcripción externa de OpenAI (modelo whisper-1).
No se cargan modelos locales: toda la inferencia ocurre en el proveedor externo.
"""
import io

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException

from app.schemas.ia_schemas import ApiResponse, TranscripcionResponse
from app.dependencies import verify_jwt
from app.config import settings

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
    if not settings.openai_api_key:
        raise HTTPException(status_code=501, detail="OPENAI_API_KEY no configurado en FastAPI")

    contenido = await archivo.read()
    if len(contenido) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el límite de 25 MB")

    from openai import AsyncOpenAI  # type: ignore

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    buffer = io.BytesIO(contenido)
    buffer.name = archivo.filename or "audio.wav"

    try:
        resultado = await client.audio.transcriptions.create(
            model="whisper-1",
            file=buffer,
            response_format="verbose_json",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Error al transcribir con OpenAI: {exc}")

    texto = getattr(resultado, "text", "").strip()
    idioma = getattr(resultado, "language", None)
    duracion = getattr(resultado, "duration", None)

    data = TranscripcionResponse(
        texto=texto,
        idioma=idioma,
        duracion_segundos=float(duracion) if duracion is not None else None,
    )
    return ApiResponse.ok("Transcripción completada", data.model_dump())
