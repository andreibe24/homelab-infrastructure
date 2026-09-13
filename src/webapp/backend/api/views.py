"""Demo API views.

`/api/health` is the JSON endpoint the Vite frontend calls; it echoes back which
HTTP version carried the request so an HTTP/3 upgrade is visible in the browser.
"""
from __future__ import annotations

import os
import platform
import time

from django.http import HttpRequest, JsonResponse

BOOT_TIME = time.time()


def _protocol(request: HttpRequest) -> str:
    # Hypercorn reports "HTTP/3" for QUIC connections, "HTTP/2" for h2 and
    # "HTTP/1.1" otherwise, via the ASGI scope's http_version.
    return request.META.get("SERVER_PROTOCOL", "unknown")


def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {
            "status": "ok",
            "protocol": _protocol(request),
            "secure": request.is_secure(),
            "uptime_seconds": round(time.time() - BOOT_TIME, 3),
        }
    )


def info(request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {
            "app": "webapp-backend",
            "version": os.environ.get("APP_VERSION", "dev"),
            "python": platform.python_version(),
            "protocol": _protocol(request),
            "http3_alt_svc": os.environ.get("HTTP3_ALT_SVC", ""),
            "pod": os.environ.get("POD_NAME", ""),
            "node": os.environ.get("NODE_NAME", ""),
        }
    )
