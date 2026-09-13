from django.urls import include, path

from api import views

urlpatterns = [
    path("api/health", views.health, name="health"),
    path("api/info", views.info, name="info"),
    # Liveness/readiness target for kubelet (TCP 8000, plaintext, in-mesh).
    path("healthz", views.health, name="healthz"),
    # django-prometheus exposes /metrics here for topic 5's ServiceMonitor.
    path("", include("django_prometheus.urls")),
]
