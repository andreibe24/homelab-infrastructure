import json

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import ChatMessage


def _json_body(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _authenticated(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required."}, status=401)
    return None


@require_GET
def health(request):
    return JsonResponse({"status": "ok"})


@ensure_csrf_cookie
@require_GET
def csrf_token(request):
    return JsonResponse({"csrfToken": get_token(request)})


@require_GET
def current_user(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required."}, status=401)
    return JsonResponse({"username": request.user.get_username()})


@require_POST
def register(request):
    data = _json_body(request)
    if data is not None and (
        not isinstance(data.get("username"), str)
        or not isinstance(data.get("password"), str)
    ):
        return JsonResponse(
            {"error": "Enter a username and password."}, status=400
        )
    username = data.get("username", "").strip() if data else ""
    password = data.get("password", "") if data else ""
    if not username or len(username) > 150 or not password:
        return JsonResponse(
            {"error": "Enter a username and password."}, status=400
        )
    try:
        validate_password(password)
        with transaction.atomic():
            user = get_user_model().objects.create_user(
                username=username, password=password
            )
    except ValidationError as error:
        return JsonResponse({"error": " ".join(error.messages)}, status=400)
    except IntegrityError:
        return JsonResponse({"error": "That username is already taken."}, status=409)

    login(request, user)
    return JsonResponse({"username": user.get_username()}, status=201)


@require_POST
def login_user(request):
    data = _json_body(request)
    if data is not None and (
        not isinstance(data.get("username"), str)
        or not isinstance(data.get("password"), str)
    ):
        return JsonResponse(
            {"error": "Enter a username and password."}, status=400
        )
    username = data.get("username", "").strip() if data else ""
    password = data.get("password", "") if data else ""
    user = authenticate(request, username=username, password=password
    if user is None:
        return JsonResponse({"error": "Invalid username or password."}, status=401)
    login(request, user)
    return JsonResponse({"username": user.get_username()})


@require_POST
def logout_user(request):
    error = _authenticated(request)
    if error:
        return error
    logout(request)
    return JsonResponse({"status": "ok"})


@require_GET
def messages(request):
    error = _authenticated(request)
    if error:
        return error
    rows = list(
        ChatMessage.objects.select_related("author")
        .order_by("-created_at", "-id")[:100]
    )
    rows.reverse()
    return JsonResponse(
        {
            "messages": [
                {
                    "id": row.id,
                    "username": row.author.get_username(),
                    "content": row.content,
                    "createdAt": row.created_at.isoformat(),
                }
                for row in rows
            ]
        }
    )


@require_POST
def post_message(request):
    error = _authenticated(request)
    if error:
        return error
    data = _json_body(request)
    if data is not None and not isinstance(data.get("content"), str):
        return JsonResponse(
            {"error": "Messages must contain 1 to 2000 characters."}, status=400
        )
    content = data.get("content", "").strip() if data else ""
    if not content or len(content) > 2000:
        return JsonResponse(
            {"error": "Messages must contain 1 to 2000 characters."}, status=400
        )
    row = ChatMessage.objects.create(author=request.user, content=content)
    return JsonResponse(
        {
            "id": row.id,
            "username": row.author.get_username(),
            "content": row.content,
            "createdAt": row.created_at.isoformat(),
        },
        status=201,
    )
