# Campfire chat MCP server

The Streamable HTTP MCP server provides two authenticated tools:

- `send-holidayExperience` shares a formatted holiday message labeled `holiday`.
- `view-holidayExperiences` lists recent messages with that label.

Create or rotate a personal MCP bearer token from the signed-in Campfire UI.
The token is shown only once and stored hashed by the chat backend. Connect an
MCP client to `https://mcp.localhost/mcp` and provide it in an Authorization header.

For local development, set `CHAT_API_URL` to the Django
`/api/mcp/holiday-experiences/` endpoint and run `python server.py`. The server
listens on `http://localhost:8000/mcp`.
