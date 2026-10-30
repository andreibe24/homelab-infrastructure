from typing import ClassVar

from django.conf import settings
from django.db import models


class ChatMessage(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    content = models.CharField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["created_at", "id"]
