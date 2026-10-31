import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

from .tools import ToolInputError

logger = logging.getLogger(__name__)


class RagServiceError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def ask_campfire(question):
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 1000:
        raise ToolInputError("Enter a question of 1 to 1000 characters.")
    question = question.strip()
    request = Request(
        f"{settings.RAG_SERVICE_URL.rstrip('/')}/ask",
        data=json.dumps({"question": question}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            result = json.load(response)
    except HTTPError as error:
        logger.warning("Campfire RAG service returned HTTP %s", error.code)
        if error.code == 400:
            raise ToolInputError("Enter a valid Campfire question.") from error
        status = error.code if error.code in (403, 429) else 503
        raise RagServiceError(
            "Campfire search is unavailable. Please try again.", status
        ) from error
    except (OSError, URLError, TimeoutError) as error:
        logger.warning("Campfire RAG service could not be reached")
        raise RagServiceError("Campfire search is unavailable. Please try again.") from error
    except (ValueError, UnicodeDecodeError) as error:
        logger.warning("Campfire RAG service returned invalid JSON")
        raise RagServiceError("Campfire search returned an invalid response.", 502) from error

    if (
        not isinstance(result, dict)
        or not isinstance(result.get("text"), str)
        or not isinstance(result.get("sources"), list)
    ):
        logger.warning("Campfire RAG service returned an invalid response shape")
        raise RagServiceError("Campfire search returned an invalid response.", 502)
    return result
