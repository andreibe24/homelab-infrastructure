import json
import logging
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)


class GatewayError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def gateway_key():
    if settings.AGENTGATEWAY_API_KEY:
        return settings.AGENTGATEWAY_API_KEY
    if not settings.AGENTGATEWAY_CLIENT_CREDENTIALS:
        raise GatewayError("AI tools are not configured. Contact the administrator.")
    try:
        credentials = json.loads(settings.AGENTGATEWAY_CLIENT_CREDENTIALS)
        if (
            not isinstance(credentials, dict)
            or credentials.get("metadata", {}).get("client_id") != "forum-app"
            or not isinstance(credentials.get("key"), str)
            or not credentials["key"].strip()
        ):
            raise ValueError("Invalid forum-app credentials")
        return credentials["key"]
    except (ValueError, AttributeError) as error:
        logger.error("Invalid agentgateway forum-app credential configuration")
        raise GatewayError("AI tools are not configured correctly.") from error


def generate(instructions, context):
    payload = {
        "model": "gpt-6-luna",
        "instructions": instructions,
        "input": json.dumps(context, ensure_ascii=False),
        "max_output_tokens": 1024,
        "stream": False,
        "store": False,
    }
    request = Request(
        f"{settings.AGENTGATEWAY_BASE_URL.rstrip('/')}/responses",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {gateway_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
    except HTTPError as error:
        logger.warning("Agentgateway rejected a request (HTTP %s)", error.code)
        if error.code == 429:
            raise GatewayError(
                "The shared AI quota is reached. Please try again later.", 429
            ) from error
        if error.code == 403:
            raise GatewayError(
                "The gateway blocked this request. Remove sensitive content and retry.",
                403,
            ) from error
        raise GatewayError("The AI gateway is unavailable. Please try again later.") from error
    except (OSError, HTTPException) as error:
        logger.warning("Agentgateway connection failed")
        raise GatewayError("The AI gateway timed out or could not be reached.") from error
    except (ValueError, UnicodeDecodeError) as error:
        logger.warning("Agentgateway returned invalid JSON")
        raise GatewayError("The AI gateway returned an invalid response.", 502) from error

    try:
        text = "\n".join(
            part["text"]
            for item in result["output"]
            if item.get("type") == "message"
            for part in item["content"]
            if part.get("type") == "output_text"
        ).strip()
        if not text or result.get("status") != "completed":
            raise ValueError("Incomplete response")
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        logger.warning("Agentgateway returned no completed text response")
        raise GatewayError("The AI did not return a complete answer. Please retry.", 502) from error
    return text
