from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_contactmessage_customer_ack_sent_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="contactmessage",
            name="read_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Leído el"),
        ),
        migrations.AddField(
            model_name="contactmessage",
            name="read_by_email",
            field=models.EmailField(blank=True, default="", max_length=254, verbose_name="Leído por"),
        ),
    ]
