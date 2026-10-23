import asyncio
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

API_URL = os.environ.get(
    "CHAT_API_URL",
    "http://localhost:8000/api/mcp/holiday-experiences/",
).rstrip("/") + "/"
server = MCPServer("Campfire chat")


def _authorization(context: Context) -> str:
    headers = context.headers or {}
    authorization = next(
        (
            value
            for key, value in headers.items()
            if key.lower() == "authorization"
        ),
        "",
    )
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise ValueError("Provide your Campfire MCP bearer token in the Authorization header.")
    return authorization


def _request_api(
    path: str,
    authorization: str,
    payload: dict[str, str] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": authorization}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(API_URL + path, data=body, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read())
    except HTTPError as error:
        try:
            message = json.loads(error.read()).get("error", "Chat API request failed.")
        except (json.JSONDecodeError, AttributeError):
            message = "Chat API request failed."
        raise ValueError(message) from error
    except (URLError, TimeoutError) as error:
        raise ValueError("The chat service is temporarily unavailable.") from error


@server.tool(
    name="send-holidayExperience",
    title="Share a holiday experience",
    description=(
        "Post a structured holiday experience to the shared Campfire channel. "
        "The message is labeled holiday so users can filter it."
    ),
)
async def send_holiday_experience(
    title: str,
    destination: str,
    dates: str,
    highlights: str,
    tips: str,
    context: Context,
) -> dict[str, Any]:
    """Share a holiday using the community's standard message template."""
    authorization = _authorization(context)
    payload = {
        "title": title,
        "destination": destination,
        "dates": dates,
        "highlights": highlights,
        "tips": tips,
    }
    return await asyncio.to_thread(
        _request_api,
        "send/",
        authorization,
        payload,
    )


@server.tool(
    name="view-holidayExperiences",
    title="Browse holiday experiences",
    description="Read recent messages in the Campfire channel labeled holiday.",
)
async def view_holiday_experiences(
    context: Context,
    limit: int = 20,
) -> dict[str, Any]:
    """Read up to 100 recent holiday experiences shared in the channel."""
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")
    authorization = _authorization(context)
    return await asyncio.to_thread(
        _request_api,
        f"?limit={limit}",
        authorization,
    )


if __name__ == "__main__":
    server.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        streamable_http_path="/mcp",
        stateless_http=True,
    )
