from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from mcp.server.fastmcp import FastMCP

from chat import tools


@sync_to_async
def call_forum_tool(name, arguments):
    close_old_connections()
    try:
        return tools.run_tool(name, arguments)
    finally:
        close_old_connections()


def create_server():
    server = FastMCP("Campfire forum")

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
        parser.add_argument("--username", required=True)

    def handle(self, *args, **options):
        if not get_user_model().objects.filter(
            username=options["username"], is_active=True
        ).exists():
            raise CommandError("Choose an existing active forum username.")
        create_server().run(transport="stdio")
