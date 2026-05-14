from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_resendwebhookevent"),
    ]

    operations = [
        migrations.DeleteModel(name="ResendWebhookEvent"),
        migrations.CreateModel(
            name="EmailDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "email_id",
                    models.CharField(
                        db_index=True,
                        help_text="ID que asigna Resend al envío.",
                        max_length=128,
                        verbose_name="ID del email",
                    ),
                ),
                ("to_email", models.CharField(db_index=True, max_length=512, verbose_name="Para")),
                ("from_email", models.CharField(blank=True, default="", max_length=255, verbose_name="Desde")),
                ("subject", models.CharField(blank=True, default="", max_length=512, verbose_name="Asunto")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("sent", "Enviado"),
                            ("delivery_delayed", "Entrega demorada"),
                            ("delivered", "Entregado"),
                            ("opened", "Abierto"),
                            ("clicked", "Click"),
                            ("complained", "Reportado como spam"),
                            ("bounced", "Rebotado"),
                            ("failed", "Fallido"),
                        ],
                        db_index=True,
                        default="sent",
                        max_length=32,
                        verbose_name="Estado actual",
                    ),
                ),
                ("sent_at", models.DateTimeField(blank=True, null=True, verbose_name="Enviado")),
                ("delivery_delayed_at", models.DateTimeField(blank=True, null=True, verbose_name="Demora")),
                ("delivered_at", models.DateTimeField(blank=True, null=True, verbose_name="Entregado")),
                ("opened_at", models.DateTimeField(blank=True, null=True, verbose_name="Abierto")),
                ("clicked_at", models.DateTimeField(blank=True, null=True, verbose_name="Click")),
                ("bounced_at", models.DateTimeField(blank=True, null=True, verbose_name="Rebotado")),
                ("complained_at", models.DateTimeField(blank=True, null=True, verbose_name="Reportado")),
                ("failed_at", models.DateTimeField(blank=True, null=True, verbose_name="Fallido")),
                ("bounce_reason", models.TextField(blank=True, default="", verbose_name="Motivo rebote")),
                ("failure_reason", models.TextField(blank=True, default="", verbose_name="Motivo fallo")),
                ("first_received_at", models.DateTimeField(auto_now_add=True, verbose_name="Primer evento")),
                (
                    "last_received_at",
                    models.DateTimeField(auto_now=True, db_index=True, verbose_name="Último evento"),
                ),
                (
                    "last_event_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="Timestamp del evento más reciente según Resend.",
                        null=True,
                        verbose_name="Última fecha (Resend)",
                    ),
                ),
                (
                    "processed_event_ids",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="svix-ids ya aplicados — garantiza idempotencia ante reintentos.",
                        verbose_name="IDs de eventos procesados",
                    ),
                ),
                ("last_payload", models.JSONField(blank=True, default=dict, verbose_name="Último payload")),
            ],
            options={
                "verbose_name": "Envío (Resend)",
                "verbose_name_plural": "Envíos (Resend)",
                "ordering": ["-last_received_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="emaildelivery",
            constraint=models.UniqueConstraint(
                fields=("email_id", "to_email"), name="emaildelivery_email_to_unique"
            ),
        ),
        migrations.AddIndex(
            model_name="emaildelivery",
            index=models.Index(fields=["-last_received_at"], name="core_emaildel_last_recv_idx"),
        ),
        migrations.AddIndex(
            model_name="emaildelivery",
            index=models.Index(fields=["status", "-last_received_at"], name="core_emaildel_status_idx"),
        ),
    ]
