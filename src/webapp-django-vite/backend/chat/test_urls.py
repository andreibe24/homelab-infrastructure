from django.urls import include, path

urlpatterns = [path("api/oidc/", include("mozilla_django_oidc.urls"))]
