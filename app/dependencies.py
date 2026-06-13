"""
Dependencias de inyección: verificación JWT compatible con Spring Boot.
El token debe ser el mismo JWT emitido por el backend Spring Boot.
"""
import base64
import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt  # type: ignore

from app.config import settings

logger = logging.getLogger(__name__)

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
        logger.info("verify_jwt: OK user_id=%s id_institucion=%s roles=%s",
                    payload.get("sub"), payload.get("id_institucion"), payload.get("roles"))
        return payload
    except JWTError as exc:
        logger.warning("verify_jwt: token invalido o expirado — %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
