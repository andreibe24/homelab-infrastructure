from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from chat.models import OIDCIdentity


class Command(BaseCommand):
    help = "Link an existing Campfire account to a verified OIDC issuer and subject."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--issuer", required=True)
        parser.add_argument("--subject", required=True)

    def handle(self, *args, **options):
        issuer = options["issuer"]
        subject = options["subject"]
        if not issuer or not subject or len(issuer) > 255 or len(subject) > 255:
            raise CommandError("Issuer and subject must be nonempty and at most 255 characters.")
        user = get_user_model().objects.using("default").filter(
            username=options["username"]
        ).first()
        if user is None:
            raise CommandError("Campfire user not found.")
        try:
            with transaction.atomic(using="default"):
                OIDCIdentity.objects.using("default").create(
                    user=user, issuer=issuer, subject=subject
                )
        except IntegrityError as error:
            raise CommandError("This user or identity is already linked.") from error
        self.stdout.write(self.style.SUCCESS("OIDC identity linked."))
