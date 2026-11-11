from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from chat import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", views.health, name="health"),
    path("api/csrf/", views.csrf_token, name="csrf"),
    path("api/auth-config/", views.auth_config, name="auth-config"),
    path("api/me/", views.current_user, name="current-user"),
    path("api/register/", views.register, name="register"),
    path("api/login/", views.login_user, name="login"),
    path("api/logout/", views.logout_user, name="logout"),
    path("api/messages/", views.messages, name="messages"),
    path("api/messages/post/", views.post_message, name="post-message"),
    path("api/ask/", views.ask_forum, name="ask-forum"),
    path("api/tools/", views.tool_catalog, name="tool-catalog"),
    path("api/tools/<str:name>/", views.execute_tool, name="execute-tool"),
]

if settings.OIDC_ENABLED:
    urlpatterns += [path("api/oidc/", include("mozilla_django_oidc.urls"))]
