"""
Migración de seguridad: crea las tablas de core que pueden faltar en producción.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_exchangerate'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE TABLE IF NOT EXISTS "core_exchangerate" (
                "id" bigserial NOT NULL PRIMARY KEY,
                "usd_to_ars" numeric(10, 2) NOT NULL,
                "updated_at" timestamp with time zone NOT NULL
            );
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
