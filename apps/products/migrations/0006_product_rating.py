from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0005_drop_legacy_columns'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='rating',
            field=models.DecimalField(decimal_places=1, default=0, help_text='Calificación promedio del producto (0.0 – 5.0).', max_digits=3),
        ),
        migrations.AddField(
            model_name='product',
            name='rating_count',
            field=models.PositiveIntegerField(default=0, help_text='Cantidad de calificaciones recibidas.'),
        ),
    ]
