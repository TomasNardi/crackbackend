from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0005_global_suggested_carousel"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="paqar_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("pending", "Sin generar"),
                    ("created", "Generado en Correo Argentino"),
                    ("error", "Error al generar"),
                    ("cancelled", "Cancelado en Correo Argentino"),
                ],
                default="pending",
                max_length=20,
                verbose_name="Estado Paq.ar",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="paqar_tracking_number",
            field=models.CharField(blank=True, max_length=50, verbose_name="Tracking Number"),
        ),
        migrations.AddField(
            model_name="order",
            name="paqar_error",
            field=models.TextField(blank=True, verbose_name="Error Paq.ar"),
        ),
    ]
