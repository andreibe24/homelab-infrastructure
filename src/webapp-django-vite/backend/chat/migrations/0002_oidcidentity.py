from typing import ClassVar

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies: ClassVar[list] = [
        ("chat", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations: ClassVar[list] = [
        migrations.CreateModel(
            name="OIDCIdentity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("issuer", models.CharField(max_length=255)),
                ("subject", models.CharField(max_length=255)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("issuer", "subject"), name="oidc_issuer_subject")],
            },
        ),
    ]
