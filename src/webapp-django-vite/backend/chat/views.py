import hashlib
import json
import secrets

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import ChatMessage, MCPAccessToken


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


def _mcp_user(request):
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    access_token = (
        MCPAccessToken.objects.select_related("user")
        .filter(token_hash=token_hash)
        .first()
    )
    if access_token is None or not access_token.user.is_active:
        return None
    MCPAccessToken.objects.filter(pk=access_token.pk).update(
        last_used_at=timezone.now()
    )
    return access_token.user


def _message_data(message):
    return {
        "id": message.id,
        "username": message.author.get_username(),
        "content": message.content,
        "labels": message.labels,
        "createdAt": message.created_at.isoformat(),
    }


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


@require_GET
def mcp_token_status(request):
    error = _authenticated(request)
    if error:
        return error
    return JsonResponse(
        {"configured": MCPAccessToken.objects.filter(user=request.user).exists()}
    )


@require_POST
def create_mcp_token(request):
    error = _authenticated(request)
    if error:
        return error
    token = secrets.token_urlsafe(32)
    MCPAccessToken.objects.update_or_create(
        user=request.user,
        defaults={"token_hash": hashlib.sha256(token.encode()).hexdigest()},
    )
    return JsonResponse({"token": token})


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
        user_model = get_user_model()
        user_model._meta.get_field("username").clean(username, None)
        validate_password(password, user=user_model(username=username))
        with transaction.atomic():
            user = user_model.objects.create_user(
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
    user = authenticate(request, **{"username": username, "password": password})
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
    queryset = ChatMessage.objects.select_related("author")
    label = request.GET.get("label", "").strip()
    if label:
        queryset = queryset.filter(labels__icontains=json.dumps(label))
    rows = list(queryset.order_by("-created_at", "-id")[:100])
    rows.reverse()
    return JsonResponse({"messages": [_message_data(row) for row in rows]})


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
    return JsonResponse(_message_data(row), status=201)


@csrf_exempt
@require_POST
def mcp_send_holiday_experience(request):
    user = _mcp_user(request)
    if user is None:
        return JsonResponse(
            {"error": "A valid MCP bearer token is required."}, status=401
        )

    data = _json_body(request)
    field_limits = {
        "title": 120,
        "destination": 200,
        "dates": 100,
        "highlights": 600,
        "tips": 600,
    }
    if data is None or any(
        not isinstance(data.get(field), str)
        or not data[field].strip()
        or len(data[field].strip()) > limit
        for field, limit in field_limits.items()
    ):
        return JsonResponse(
            {
                "error": (
                    "Provide title, destination, dates, highlights, and tips "
                    "as non-empty strings within their field limits."
                )
            },
            status=400,
        )

    content = "\n".join(
        (
            f"Holiday experience: {data['title'].strip()}",
            f"Destination: {data['destination'].strip()}",
            f"When: {data['dates'].strip()}",
            f"Highlights: {data['highlights'].strip()}",
            f"Tips: {data['tips'].strip()}",
        )
    )
    if len(content) > 2000:
        return JsonResponse(
            {"error": "The formatted holiday message exceeds 2000 characters."},
            status=400,
        )
    message = ChatMessage.objects.create(
        author=user,
        content=content,
        labels=["holiday"],
    )
    return JsonResponse(_message_data(message), status=201)


@csrf_exempt
@require_GET
def mcp_view_holiday_experiences(request):
    if _mcp_user(request) is None:
        return JsonResponse(
            {"error": "A valid MCP bearer token is required."}, status=401
        )
    try:
        limit = int(request.GET.get("limit", "20"))
    except ValueError:
        return JsonResponse({"error": "Limit must be an integer."}, status=400)
    if not 1 <= limit <= 100:
        return JsonResponse({"error": "Limit must be between 1 and 100."}, status=400)
    rows = (
        ChatMessage.objects.select_related("author")
        .filter(labels__icontains=json.dumps("holiday"))
        .order_by("-created_at", "-id")[:limit]
    )
    return JsonResponse({"messages": [_message_data(row) for row in rows]})
