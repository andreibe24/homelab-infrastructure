import hashlib

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import SuspiciousOperation, ValidationError
from django.db import IntegrityError, transaction
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from .models import OIDCIdentity


class CampfireOIDCBackend(OIDCAuthenticationBackend):
    def verify_token(self, token, **kwargs):
        claims = super().verify_token(token, **kwargs)
        audience = claims.get("aud")
        audiences = [audience] if isinstance(audience, str) else audience
        if (
            claims.get("iss") != settings.OIDC_ISSUER
            or not isinstance(claims.get("sub"), str)
            or not claims["sub"]
            or not isinstance(claims.get("exp"), (int, float))
            or not isinstance(claims.get("iat"), (int, float))
            or not isinstance(audiences, list)
            or not all(isinstance(item, str) and item for item in audiences)
            or settings.OIDC_RP_CLIENT_ID not in audiences
            or (len(audiences) > 1 and claims.get("azp") != settings.OIDC_RP_CLIENT_ID)
            or (claims.get("azp") is not None and claims["azp"] != settings.OIDC_RP_CLIENT_ID)
        ):
            raise SuspiciousOperation("Invalid OIDC issuer, subject, audience or token lifetime.")
        return claims

    def get_or_create_user(self, access_token, id_token, payload):
        claims = self.get_userinfo(access_token, id_token, payload)
        if claims.get("sub") != payload["sub"]:
            raise SuspiciousOperation("OIDC userinfo subject does not match the ID token.")
        issuer, subject = payload["iss"], payload["sub"]
        if len(issuer) > 255 or len(subject) > 255:
            raise SuspiciousOperation("OIDC identity is too long.")
        identities = OIDCIdentity.objects.using("default").select_related("user")
        identity = identities.filter(issuer=issuer, subject=subject).first()
        if identity:
            return identity.user if identity.user.is_active else None
        digest = hashlib.sha256(f"{issuer}\0{subject}".encode()).hexdigest()
        user_model = get_user_model()
        fallback = f"oidc_{digest}"
        preferred = claims.get("preferred_username")
        if isinstance(preferred, str):
            preferred = preferred.strip()
            try:
                preferred = user_model._meta.get_field("username").clean(preferred, None)
            except ValidationError:
                preferred = None
        else:
            preferred = None
        candidates = [preferred, fallback] if preferred and preferred != fallback else [fallback]
        for username in candidates:
            if username != fallback and user_model.objects.using("default").filter(username=username).exists():
                continue
            try:
                with transaction.atomic(using="default"):
                    user = user_model.objects.db_manager("default").create_user(
                        username=username, password=None
                    )
                    OIDCIdentity.objects.using("default").create(
                        user=user, issuer=issuer, subject=subject
                    )
                    return user
            except IntegrityError:
                identity = identities.filter(issuer=issuer, subject=subject).first()
                if identity:
                    return identity.user if identity.user.is_active else None
                if username == fallback or not user_model.objects.using("default").filter(username=username).exists():
                    raise

    def get_user(self, user_id):
        return get_user_model().objects.using("default").filter(
            pk=user_id, is_active=True
        ).first()
