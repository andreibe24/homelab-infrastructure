"""ASGI entrypoint.

Hypercorn serves this callable over three listeners at once (see hypercorn.toml):

  * TCP  8000  plaintext HTTP/1.1 + h2c  -- in-mesh traffic, probes, /metrics
  * TCP  8443  TLS  HTTP/1.1 + h2        -- edge fallback when HTTP/3 is blocked
  * UDP  8443  QUIC HTTP/3 (aioquic)     -- the HTTP/3 listener

Django's ASGI application is protocol agnostic: aioquic terminates QUIC and
Hypercorn's H3 protocol converts the stream into ordinary ASGI `http` scope events,
so no Django code is HTTP/3 specific.
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
