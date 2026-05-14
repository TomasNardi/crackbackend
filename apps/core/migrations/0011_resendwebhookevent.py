from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_siteconfig_top_banner_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="ResendWebhookEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "event_id",
                    models.CharField(
                        help_text="Identificador único del evento — garantiza idempotencia.",
                        max_length=255,
                        unique=True,
                        verbose_name="ID del evento (svix)",
                    ),
                ),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("email.sent", "Enviado"),
                            ("email.delivered", "Entregado"),
                            ("email.delivery_delayed", "Entrega demorada"),
                            ("email.bounced", "Rebotado"),
                            ("email.complained", "Reportado como spam"),
                            ("email.opened", "Abierto"),
                            ("email.clicked", "Click"),
                            ("email.failed", "Fallido"),
                        ],
                        db_index=True,
                        max_length=64,
                        verbose_name="Tipo",
                    ),
                ),
                (
                    "email_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="ID que asigna Resend al email — agrupa todos los eventos de un mismo envío.",
                        max_length=128,
                        verbose_name="ID del email",
                    ),
                ),
                ("from_email", models.CharField(blank=True, default="", max_length=255, verbose_name="Desde")),
                (
                    "to_email",
                    models.CharField(blank=True, db_index=True, default="", max_length=512, verbose_name="Para"),
                ),
                ("subject", models.CharField(blank=True, default="", max_length=512, verbose_name="Asunto")),
                (
                    "event_created_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="Timestamp original que reporta Resend.",
                        null=True,
                        verbose_name="Fecha del evento (Resend)",
                    ),
                ),
                (
                    "received_at",
                    models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Recibido"),
                ),
                ("raw_payload", models.JSONField(blank=True, default=dict, verbose_name="Payload completo")),
            ],
            options={
                "verbose_name": "Log de envío (Resend)",
                "verbose_name_plural": "Logs de envío (Resend)",
                "ordering": ["-received_at"],
            },
        ),
        migrations.AddIndex(
            model_name="resendwebhookevent",
            index=models.Index(fields=["-received_at"], name="core_resend_receive_idx"),
        ),
        migrations.AddIndex(
            model_name="resendwebhookevent",
            index=models.Index(fields=["event_type", "-received_at"], name="core_resend_type_recv_idx"),
        ),
    ]
