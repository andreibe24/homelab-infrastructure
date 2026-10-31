import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.exceptions import SuspiciousOperation
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from config.db_router import PrimaryReplicaRouter

from .models import OIDCIdentity
from .oidc import CampfireOIDCBackend

ISSUER = "https://identity.example/realms/homelab"


@override_settings(
    OIDC_ENABLED=True,
    OIDC_ISSUER=ISSUER,
    OIDC_RP_CLIENT_ID="campfire",
    OIDC_RP_CLIENT_SECRET="client-secret",
    OIDC_RP_SIGN_ALGO="RS256",
    OIDC_OP_TOKEN_ENDPOINT="https://internal/token",
    OIDC_OP_USER_ENDPOINT="https://internal/userinfo",
    OIDC_OP_JWKS_ENDPOINT="https://internal/certs",
    OIDC_OP_AUTHORIZATION_ENDPOINT="https://identity.example/auth",
    OIDC_USE_PKCE=True,
)
class OIDCBackendTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.backend = CampfireOIDCBackend()
        self.claims = {
            "iss": ISSUER,
            "sub": "subject-1",
            "aud": "campfire",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
            "nonce": "nonce-1",
        }

    def verify(self, changes=None, key=None, nonce="nonce-1"):
        token = jwt.encode({**self.claims, **(changes or {})}, key or self.key, algorithm="RS256")
        with patch.object(self.backend, "retrieve_matching_jwk", return_value=self.key.public_key()):
            return self.backend.verify_token(token, nonce=nonce)

    def test_signed_token_requires_expected_issuer_audience_lifetime_and_nonce(self):
        self.assertEqual(self.verify()["sub"], "subject-1")
        for changes in [
            {"iss": "https://wrong.example"},
            {"aud": "another-client"},
            {"aud": ["campfire", "another-client"]},
            {"azp": "another-client"},
            {"sub": ""},
            {"exp": None},
            {"iat": None},
        ]:
            with self.subTest(changes=changes), self.assertRaises((SuspiciousOperation, jwt.PyJWTError, TypeError)):
                self.verify(changes)
        with self.assertRaises(SuspiciousOperation):
            self.verify(nonce="wrong")
        with self.assertRaises(jwt.PyJWTError):
            self.verify({"exp": int(time.time()) - 60})
        with self.assertRaises(SuspiciousOperation):
            self.verify(key=rsa.generate_private_key(public_exponent=65537, key_size=2048))

    def test_stable_subject_creates_one_user_without_linking_existing_name_or_email(self):
        local = get_user_model().objects.create_user("camper", email="camper@example.com")
        claims = {"sub": "subject-1", "preferred_username": "camper", "email": local.email}
        with patch.object(self.backend, "get_userinfo", return_value=claims):
            user = self.backend.get_or_create_user("access", "id", self.claims)
            self.assertNotEqual(user.pk, local.pk)
            self.assertFalse(user.has_usable_password())
            self.assertEqual(self.backend.get_or_create_user("access", "id", self.claims), user)
        self.assertEqual(OIDCIdentity.objects.count(), 1)

    def test_new_user_uses_available_valid_preferred_username(self):
        with patch.object(self.backend, "get_userinfo", return_value={
            "sub": "subject-1", "preferred_username": "new-camper"
        }):
            user = self.backend.get_or_create_user("access", "id", self.claims)
        self.assertEqual(user.username, "new-camper")

    def test_subject_mismatch_and_disabled_user_are_rejected(self):
        with (
            patch.object(self.backend, "get_userinfo", return_value={"sub": "other"}),
            self.assertRaises(SuspiciousOperation),
        ):
            self.backend.get_or_create_user("access", "id", self.claims)
        user = get_user_model().objects.create_user("disabled", is_active=False)
        OIDCIdentity.objects.create(user=user, issuer=ISSUER, subject="subject-1")
        with patch.object(self.backend, "get_userinfo", return_value={"sub": "subject-1"}):
            self.assertIsNone(self.backend.get_or_create_user("access", "id", self.claims))
        self.assertIsNone(self.backend.get_user(user.pk))

    def test_local_credentials_are_disabled(self):
        self.assertEqual(self.client.post("/api/login/").status_code, 403)
        self.assertEqual(self.client.post("/api/register/").status_code, 403)
        self.assertTrue(self.client.get("/api/auth-config/").json()["oidc"])

    def test_explicit_migration_links_existing_account_only_once(self):
        user = get_user_model().objects.create_user("existing")
        call_command("link_oidc_user", username="existing", issuer=ISSUER, subject="subject-1")
        with patch.object(self.backend, "get_userinfo", return_value={"sub": "subject-1"}):
            self.assertEqual(self.backend.get_or_create_user("access", "id", self.claims), user)
        with self.assertRaises(CommandError):
            call_command("link_oidc_user", username="existing", issuer=ISSUER, subject="other")

    @override_settings(ROOT_URLCONF="chat.test_urls")
    def test_authorization_uses_state_nonce_and_pkce_and_rejects_bad_state(self):
        response = self.client.get("/api/oidc/authenticate/")
        self.assertEqual(response.status_code, 302)
        params = parse_qs(urlparse(response["Location"]).query)
        self.assertEqual(params["client_id"], ["campfire"])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertTrue(params["state"][0])
        self.assertTrue(params["nonce"][0])
        self.assertEqual(
            self.client.get("/api/oidc/callback/?code=code&state=bad").status_code,
            400,
        )

    @override_settings(
        ROOT_URLCONF="chat.test_urls",
        AUTHENTICATION_BACKENDS=["chat.oidc.CampfireOIDCBackend"],
    )
    def test_authorization_callback_creates_session_and_cannot_replay_state(self):
        response = self.client.get("/api/oidc/authenticate/")
        params = parse_qs(urlparse(response["Location"]).query)
        state = params["state"][0]
        token = jwt.encode(
            {**self.claims, "nonce": params["nonce"][0]}, self.key, algorithm="RS256"
        )
        with (
            patch.object(CampfireOIDCBackend, "get_token", return_value={
                "id_token": token, "access_token": "access"
            }) as exchange,
            patch.object(CampfireOIDCBackend, "retrieve_matching_jwk", return_value=self.key.public_key()),
            patch.object(CampfireOIDCBackend, "get_userinfo", return_value={
                "sub": "subject-1", "preferred_username": "new-camper"
            }),
        ):
            callback = f"/api/oidc/callback/?code=code&state={state}"
            self.assertEqual(self.client.get(callback).status_code, 302)
            self.assertTrue(exchange.call_args.args[0]["code_verifier"])
            self.assertEqual(
                self.client.session["_auth_user_id"],
                str(get_user_model().objects.get(username="new-camper").pk),
            )
            self.assertEqual(self.client.get(callback).status_code, 400)

    def test_identity_and_sessions_read_from_primary(self):
        router = PrimaryReplicaRouter()
        self.assertEqual(router.db_for_read(Session), "default")
        self.assertEqual(router.db_for_read(get_user_model()), "default")
        self.assertEqual(router.db_for_read(OIDCIdentity), "default")
