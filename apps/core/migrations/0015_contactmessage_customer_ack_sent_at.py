from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_emaildelivery_order_traceability"),
    ]

    operations = [
        migrations.AddField(
            model_name="contactmessage",
            name="customer_ack_sent_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Acuse enviado al cliente"),
        ),
    ]
