"""
Migración de seguridad: crea las tablas de users que pueden faltar en producción.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
        ('products', '0003_ensure_tables_exist'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
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
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
