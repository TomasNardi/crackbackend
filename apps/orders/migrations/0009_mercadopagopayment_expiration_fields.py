from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0008_alter_order_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="mercadopagopayment",
            name="expired_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Vencido el"),
        ),
        migrations.AddField(
            model_name="mercadopagopayment",
            name="expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="Vence el"),
        ),
    ]
