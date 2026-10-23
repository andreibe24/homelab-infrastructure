import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase


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
