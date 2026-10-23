from django.contrib import admin
from django.urls import path

from chat import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", views.health, name="health"),
    path("api/csrf/", views.csrf_token, name="csrf"),
    path("api/me/", views.current_user, name="current-user"),
    path("api/register/", views.register, name="register"),
    path("api/login/", views.login_user, name="login"),
    path("api/logout/", views.logout_user, name="logout"),
    path("api/mcp-token/", views.mcp_token_status, name="mcp-token-status"),
    path("api/mcp-token/create/", views.create_mcp_token, name="mcp-token-create"),
    path("api/messages/", views.messages, name="messages"),
    path("api/messages/post/", views.post_message, name="post-message"),
    path(
        "api/mcp/holiday-experiences/send/",
        views.mcp_send_holiday_experience,
        name="mcp-send-holiday-experience",
    ),
    path(
        "api/mcp/holiday-experiences/",
        views.mcp_view_holiday_experiences,
        name="mcp-view-holiday-experiences",
    ),
]
