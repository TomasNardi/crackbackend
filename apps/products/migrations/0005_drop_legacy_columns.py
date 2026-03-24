"""
Elimina columnas legacy de products_product que quedaron de versiones anteriores.
Solo corre en PostgreSQL.
"""

from django.db import migrations


def drop_legacy_columns(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    schema_editor.execute("""
        ALTER TABLE "products_product"
            DROP COLUMN IF EXISTS "is_single",
            DROP COLUMN IF EXISTS "is_slab",
            DROP COLUMN IF EXISTS "is_sealed",
            DROP COLUMN IF EXISTS "expansion_id",
            DROP COLUMN IF EXISTS "product_type_id",
            DROP COLUMN IF EXISTS "price";
    """)


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0004_fix_product_columns'),
    ]

    operations = [
        migrations.RunPython(drop_legacy_columns, migrations.RunPython.noop),
    ]
