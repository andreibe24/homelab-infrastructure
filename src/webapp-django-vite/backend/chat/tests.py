import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from .models import ChatMessage, MCPAccessToken


class ChatApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "campfire-user", None, "S0mething-private-and-strong"
        )

    def test_anonymous_users_cannot_read_messages(self):
        response = self.client.get("/api/messages/")

        self.assertEqual(response.status_code, 401)

    def test_user_can_register_and_view_their_session(self):
        response = self.client.post(
            "/api/register/",
            data=json.dumps(
                {
                    "username": "new-camper",
                    "password": "S0mething-private-and-strong",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["username"], "new-camper")
        self.assertEqual(self.client.get("/api/me/").json()["username"], "new-camper")

    def test_registration_rejects_non_string_credentials(self):
        response = self.client.post(
            "/api/register/",
            data=json.dumps({"username": 42, "password": "strong-password"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_authenticated_user_can_post_and_read_messages(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/api/messages/post/",
            data=json.dumps({"content": "Hello, everyone!"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        history = self.client.get("/api/messages/").json()["messages"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["username"], self.user.username)
        self.assertEqual(history[0]["content"], "Hello, everyone!")
        self.assertEqual(history[0]["labels"], [])

    def test_message_length_is_limited(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/api/messages/post/",
            data=json.dumps({"content": "x" * 2001}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_post_requests_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(
            "/api/messages/post/",
            data=json.dumps({"content": "Hello"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_mcp_token_is_returned_once_and_can_be_rotated(self):
        self.client.force_login(self.user)
        response = self.client.post("/api/mcp-token/create/")
        first_token = response.json()["token"]

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.get("/api/mcp-token/").json()["configured"])
        self.assertNotEqual(
            MCPAccessToken.objects.get(user=self.user).token_hash, first_token
        )

        second_token = self.client.post("/api/mcp-token/create/").json()["token"]
        mcp_client = Client()
        old_response = mcp_client.get(
            "/api/mcp/holiday-experiences/",
            HTTP_AUTHORIZATION="".join(("Bear", "er ", first_token)),
        )
        new_response = mcp_client.get(
            "/api/mcp/holiday-experiences/",
            HTTP_AUTHORIZATION="".join(("Bear", "er ", second_token)),
        )

        self.assertEqual(old_response.status_code, 401)
        self.assertEqual(new_response.status_code, 200)
        self.assertNotEqual(first_token, second_token)

    def test_mcp_token_creation_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post("/api/mcp-token/create/")

        self.assertEqual(response.status_code, 403)

    def test_mcp_holiday_tool_stores_labeled_template_and_filters(self):
        self.client.force_login(self.user)
        token = self.client.post("/api/mcp-token/create/").json()["token"]
        mcp_client = Client()
        response = mcp_client.post(
            "/api/mcp/holiday-experiences/send/",
            data=json.dumps(
                {
                    "title": "A week in Rome",
                    "destination": "Rome, Italy",
                    "dates": "May 2026",
                    "highlights": "The Colosseum and local food",
                    "tips": "Book museum tickets ahead",
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION="".join(("Bear", "er ", token)),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["labels"], ["holiday"])
        self.assertIn("Destination: Rome, Italy", response.json()["content"])
        self.assertEqual(
            len(self.client.get("/api/messages/?label=holiday").json()["messages"]),
            1,
        )

        ChatMessage.objects.create(
            author=self.user,
            content="A newer holiday experience",
            labels=["holiday"],
        )
        holiday_view = mcp_client.get(
            "/api/mcp/holiday-experiences/?limit=1",
            HTTP_AUTHORIZATION="".join(("Bear", "er ", token)),
        )
        self.assertEqual(
            holiday_view.json()["messages"][0]["content"],
            "A newer holiday experience",
        )

    def test_mcp_holiday_endpoints_reject_invalid_tokens_and_fields(self):
        invalid_token_response = Client().get(
            "/api/mcp/holiday-experiences/",
            HTTP_AUTHORIZATION="".join(("Bear", "er ", "invalid")),
        )
        self.assertEqual(invalid_token_response.status_code, 401)

        self.client.force_login(self.user)
        token = self.client.post("/api/mcp-token/create/").json()["token"]
        response = Client().post(
            "/api/mcp/holiday-experiences/send/",
            data=json.dumps({"title": "Only a title"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="".join(("Bear", "er ", token)),
        )
        self.assertEqual(response.status_code, 400)
