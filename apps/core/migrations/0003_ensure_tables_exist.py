"""
Migración de seguridad: crea las tablas de core que pueden faltar en producción.
Solo corre en PostgreSQL.
"""

from django.db import migrations


def ensure_tables(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute("""
        CREATE TABLE IF NOT EXISTS "core_exchangerate" (
            "id" bigserial NOT NULL PRIMARY KEY,
            "usd_to_ars" numeric(10, 2) NOT NULL,
            "updated_at" timestamp with time zone NOT NULL
        );
    """)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_exchangerate'),
    ]

    operations = [
        migrations.RunPython(ensure_tables, migrations.RunPython.noop),
    ]
