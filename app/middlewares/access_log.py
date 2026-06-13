import logging
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("app.access")

_SKIP_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            client_ip = request.client.host if request.client else "-"
            level = logging.WARNING if status >= 400 else logging.INFO
            logger.log(
                level,
                "%s %s %d | %.1fms | ip=%s",
                request.method, request.url.path, status, duration_ms, client_ip,
            )
        return response
