from django.db import migrations, models


_DEFAULT_RECIPIENTS = [
    ("cracktcg@gmail.com", "CRACK TCG (correo principal)"),
    ("martin@martingrobas.com", "Martin Grobas"),
    ("tomas.nardi@hotmail.com", "Tomás Nardi"),
]


def seed_recipients(apps, schema_editor):
    """Migra emails desde ConfiguracionNotificaciones + agrega los 3 default."""
    NotificationRecipient = apps.get_model("core", "NotificationRecipient")
    ConfiguracionNotificaciones = apps.get_model("core", "ConfiguracionNotificaciones")

    seen = set()

    # 1) Default hardcoded (ahora dejan de estar en código).
    for email, name in _DEFAULT_RECIPIENTS:
        key = email.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        NotificationRecipient.objects.update_or_create(
            email=key,
            defaults={"name": name, "is_active": True},
        )

    # 2) Lo que el admin ya hubiese cargado en el TextField viejo.
    try:
        config = ConfiguracionNotificaciones.objects.first()
    except Exception:
        config = None

    if config and config.emails:
        raw = config.emails.replace("\n", ",").split(",")
        for value in raw:
            email = value.strip().lower()
            if not email or email in seen:
                continue
            seen.add(email)
            NotificationRecipient.objects.update_or_create(
                email=email,
                defaults={"is_active": True},
            )


def unseed_recipients(apps, schema_editor):
    NotificationRecipient = apps.get_model("core", "NotificationRecipient")
    NotificationRecipient.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_emaildelivery"),
    ]

    operations = [
        migrations.CreateModel(
            name="NotificationRecipient",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=254, unique=True, verbose_name="Email")),
                (
                    "name",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Opcional. Solo para identificarlo en el listado.",
                        max_length=120,
                        verbose_name="Nombre",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Si está desactivado, no recibe notificaciones.",
                        verbose_name="Activo",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Creado")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Modificado")),
            ],
            options={
                "verbose_name": "Destinatario",
                "verbose_name_plural": "Destinatarios",
                "ordering": ["email"],
            },
        ),
        migrations.RunPython(seed_recipients, reverse_code=unseed_recipients),
        migrations.DeleteModel(name="ConfiguracionNotificaciones"),
    ]
