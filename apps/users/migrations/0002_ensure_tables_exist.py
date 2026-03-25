"""
Migración de seguridad: crea las tablas de users que pueden faltar en producción.
Solo corre en PostgreSQL.
"""

from django.db import migrations


def ensure_tables(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute("""
        CREATE TABLE IF NOT EXISTS "users_wishlist" (
            "id" bigserial NOT NULL PRIMARY KEY,
            "created_at" timestamp with time zone NOT NULL,
            "user_id" bigint NOT NULL UNIQUE REFERENCES "users_user" ("id")
        );

        CREATE TABLE IF NOT EXISTS "users_wishlistitem" (
            "id" bigserial NOT NULL PRIMARY KEY,
            "added_at" timestamp with time zone NOT NULL,
            "wishlist_id" bigint NOT NULL REFERENCES "users_wishlist" ("id"),
            "product_id" bigint NOT NULL REFERENCES "products_product" ("id"),
            UNIQUE ("wishlist_id", "product_id")
        );
    """)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
        ('products', '0003_ensure_tables_exist'),
    ]

    operations = [
        migrations.RunPython(ensure_tables, migrations.RunPython.noop),
    ]
