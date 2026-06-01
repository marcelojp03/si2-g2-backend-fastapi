"""
Dependencias de inyección: verificación JWT compatible con Spring Boot.
El token debe ser el mismo JWT emitido por el backend Spring Boot.
"""
import base64
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt  # type: ignore

from app.config import settings

_bearer = HTTPBearer()


def verify_jwt(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> dict:
    """
    Verifica que el token JWT fue emitido por Spring Boot con el mismo secreto.
    Retorna el payload decodificado (claims).
    """
    try:
        # El secreto en Spring Boot está en Base64; jose necesita los bytes crudos
        secret_bytes = base64.b64decode(settings.jwt_secret)
        payload = jwt.decode(
            credentials.credentials,
            secret_bytes,
            algorithms=["HS256"],
        )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
