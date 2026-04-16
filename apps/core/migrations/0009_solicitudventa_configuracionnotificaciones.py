from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_paymentsettings_alter_emailsubscription_options_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConfiguracionNotificaciones",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("emails", models.TextField(blank=True, help_text="Separá múltiples emails con comas o saltos de línea.", verbose_name="Emails de notificación")),
            ],
            options={
                "verbose_name": "Configuración de notificaciones",
                "verbose_name_plural": "Configuraciones de notificaciones",
            },
        ),
        migrations.CreateModel(
            name="SolicitudVenta",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre_completo", models.CharField(max_length=255, verbose_name="Nombre y Apellido")),
                ("email", models.EmailField(max_length=254, verbose_name="Email")),
                ("celular", models.CharField(max_length=50, verbose_name="Celular")),
                ("tipo_coleccion", models.CharField(choices=[("sellado", "Sellado"), ("cartas", "Cartas"), ("slabs", "Slabs")], max_length=20, verbose_name="Tipo de colección")),
                ("imagenes", models.JSONField(blank=True, default=list, help_text="Lista de imágenes subidas a Cloudinary con secure_url y public_id.", verbose_name="Imágenes")),
                ("estado", models.CharField(choices=[("pendiente", "Pendiente"), ("rechazado", "Rechazado"), ("aceptado", "Aceptado")], default="pendiente", max_length=20, verbose_name="Estado")),
                ("fecha_creacion", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
            ],
            options={
                "verbose_name": "Solicitud de venta",
                "verbose_name_plural": "Solicitudes de venta",
                "ordering": ["-fecha_creacion"],
            },
        ),
    ]