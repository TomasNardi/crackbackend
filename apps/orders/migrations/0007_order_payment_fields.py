from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0006_order_paqar_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="cash_discount_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name="Monto desc. efectivo"),
        ),
        migrations.AddField(
            model_name="order",
            name="cash_discount_percent",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5, verbose_name="% desc. efectivo aplicado"),
        ),
        migrations.AddField(
            model_name="order",
            name="mp_preference_id",
            field=models.CharField(blank=True, db_index=True, max_length=150, verbose_name="MP Preference ID"),
        ),
        migrations.AddField(
            model_name="order",
            name="payment_method",
            field=models.CharField(
                choices=[("mercadopago", "Mercado Pago"), ("cash", "Efectivo")],
                default="mercadopago",
                max_length=20,
                verbose_name="Método de pago",
            ),
        ),
        migrations.AddField(
            model_name="mercadopagopayment",
            name="date_approved",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Fecha aprobación"),
        ),
        migrations.AddField(
            model_name="mercadopagopayment",
            name="external_reference",
            field=models.CharField(blank=True, db_index=True, max_length=40, verbose_name="External reference"),
        ),
        migrations.AddField(
            model_name="mercadopagopayment",
            name="last_validated_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Última validación"),
        ),
        migrations.AddField(
            model_name="mercadopagopayment",
            name="net_received_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name="Monto neto recibido"),
        ),
        migrations.AddField(
            model_name="mercadopagopayment",
            name="transaction_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name="Monto transacción"),
        ),
    ]
