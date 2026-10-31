import hmac
import os

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

from chat import tools


class StaticTokenVerifier:
    def __init__(self, expected_token):
        self.expected_token = expected_token

    async def verify_token(self, token):
        if not hmac.compare_digest(token, self.expected_token):
            return None
        return AccessToken(
            token=token,
            client_id="campfire-operator",
            scopes=["campfire"],
        )


@sync_to_async
def call_forum_tool(name, arguments):
    close_old_connections()
    try:
        return tools.run_tool(name, arguments)
    finally:
        close_old_connections()


def create_server(auth_token=None):
    auth = {}
    if auth_token:
        auth = {
            "auth": AuthSettings(
                issuer_url="https://campfire.localhost",
                resource_server_url="https://campfire.localhost/mcp",
                validate_token_resource=False,
            ),
            "token_verifier": StaticTokenVerifier(auth_token),
        }
    server = MCPServer("Campfire forum", **auth)

    @server.tool()
    async def recent_messages() -> dict:
        """Read the latest 20 shared forum messages without calling an LLM."""
        return await call_forum_tool("recent_messages", {})

    @server.tool()
    async def summarize_forum() -> dict:
        """Summarize the latest forum messages using the forum-app AI gateway."""
        return await call_forum_tool("summarize_forum", {})

    @server.tool()
    async def draft_reply(idea: str) -> dict:
        """Draft a reply from an idea using AI. Does not publish to the forum."""
        return await call_forum_tool("draft_reply", {"idea": idea})

    return server


class Command(BaseCommand):
    help = "Run the local stdio MCP server with access to the shared forum."

    def add_arguments(self, parser):
        parser.add_argument("--username")
        parser.add_argument(
            "--transport", choices=("stdio", "streamable-http"), default="stdio"
        )
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8000)

    def handle(self, *args, **options):
        username = options["username"]
        transport = options["transport"]
        if transport == "stdio":
            if not username:
                raise CommandError("The stdio transport requires --username.")
            if not get_user_model().objects.filter(
                username=username, is_active=True
            ).exists():
                raise CommandError("Choose an existing active forum username.")
            create_server().run(transport="stdio")
            return

        auth_token = os.environ.get("MCP_AUTH_TOKEN", "")
        if not auth_token:
            raise CommandError("MCP_AUTH_TOKEN is required for the HTTP transport.")
        if username and not get_user_model().objects.filter(
            username=username, is_active=True
        ).exists():
            raise CommandError("Choose an existing active forum username.")
        create_server(auth_token).run(
            transport="streamable-http",
            host=options["host"],
            port=options["port"],
            streamable_http_path="/mcp",
            stateless_http=True,
        )
