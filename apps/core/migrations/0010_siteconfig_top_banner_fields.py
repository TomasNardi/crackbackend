from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_solicitudventa_configuracionnotificaciones"),
    ]

    operations = [
        migrations.AddField(
            model_name="siteconfig",
            name="show_top_banner",
            field=models.BooleanField(
                default=True,
                help_text="Activa o desactiva el banner promocional por encima del navbar.",
                verbose_name="Mostrar banner superior",
            ),
        ),
        migrations.AddField(
            model_name="siteconfig",
            name="top_banner_message",
            field=models.CharField(
                blank=True,
                default="Envíos a todo el país — 15% OFF con código CRACK15",
                help_text="Mensaje visible en el banner superior del sitio.",
                max_length=200,
                verbose_name="Texto del banner superior",
            ),
        ),
    ]
