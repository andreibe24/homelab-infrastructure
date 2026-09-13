"""Tiny CORS middleware.

The SPA is served from `https://webapp.<domain>` while the HTTP/3 API listener is
reachable at `https://api.webapp.<domain>` (UDP/443, bypassing ingress), so the
browser treats API calls as cross-origin. A dependency-free middleware keeps the
image small; swap in django-cors-headers if the policy ever grows.
"""
from __future__ import annotations

from django.conf import settings
from django.http import HttpResponse


class CorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.allowed = set(getattr(settings, "CORS_ALLOWED_ORIGINS", []))

    def __call__(self, request):
        if request.method == "OPTIONS" and "HTTP_ACCESS_CONTROL_REQUEST_METHOD" in request.META:
            response: HttpResponse = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        origin = request.META.get("HTTP_ORIGIN")
        if origin and (origin in self.allowed or "*" in self.allowed):
            response["Access-Control-Allow-Origin"] = origin
            response["Vary"] = "Origin"
            response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type"
            response["Access-Control-Max-Age"] = "600"

        # NOTE: the `alt-svc` header is emitted by Hypercorn itself (see
        # `alt_svc_headers` in hypercorn.toml), not here, so that exactly one
        # advertisement reaches the browser.
        return response
