"""
Fix columnas faltantes en products_product en producción (PostgreSQL).
La tabla existía del deploy original pero le faltan las FKs y columnas nuevas.
Solo corre en PostgreSQL — en SQLite (desarrollo) se saltea.
"""

from django.db import migrations


def fix_product_table(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    schema_editor.execute("""
        CREATE TABLE IF NOT EXISTS "products_productcategory" (
            "id" bigserial NOT NULL PRIMARY KEY,
            "name" varchar(100) NOT NULL UNIQUE,
            "slug" varchar(120) NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS "products_tcg" (
            "id" bigserial NOT NULL PRIMARY KEY,
            "name" varchar(100) NOT NULL UNIQUE,
            "slug" varchar(120) NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS "products_cardcondition" (
            "id" bigserial NOT NULL PRIMARY KEY,
            "name" varchar(100) NOT NULL UNIQUE,
            "abbreviation" varchar(20) NOT NULL
        );
        CREATE TABLE IF NOT EXISTS "products_certificationentity" (
            "id" bigserial NOT NULL PRIMARY KEY,
            "name" varchar(100) NOT NULL UNIQUE,
            "abbreviation" varchar(20) NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS "products_certificationgrade" (
            "id" bigserial NOT NULL PRIMARY KEY,
            "grade" numeric(4, 1) NOT NULL UNIQUE
        );

        ALTER TABLE "products_product"
            ADD COLUMN IF NOT EXISTS "description" text NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS "price_usd" numeric(10, 2) NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS "image_url_2" varchar(600) NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS "image_url_3" varchar(600) NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS "pricecharting_url" varchar(600) NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS "tcg_id" bigint NULL,
            ADD COLUMN IF NOT EXISTS "category_id" bigint NULL,
            ADD COLUMN IF NOT EXISTS "condition_id" bigint NULL,
            ADD COLUMN IF NOT EXISTS "certification_entity_id" bigint NULL,
            ADD COLUMN IF NOT EXISTS "certification_grade_id" bigint NULL;

        ALTER TABLE "products_product"
            ALTER COLUMN "price_usd" DROP DEFAULT,
            ALTER COLUMN "description" DROP DEFAULT,
            ALTER COLUMN "image_url_2" DROP DEFAULT,
            ALTER COLUMN "image_url_3" DROP DEFAULT,
            ALTER COLUMN "pricecharting_url" DROP DEFAULT;

        ALTER TABLE "products_product" DROP COLUMN IF EXISTS "price";

        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'products_product_category_id_fk') THEN
                ALTER TABLE "products_product" ADD CONSTRAINT "products_product_category_id_fk"
                    FOREIGN KEY ("category_id") REFERENCES "products_productcategory" ("id") DEFERRABLE INITIALLY DEFERRED;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'products_product_tcg_id_fk') THEN
                ALTER TABLE "products_product" ADD CONSTRAINT "products_product_tcg_id_fk"
                    FOREIGN KEY ("tcg_id") REFERENCES "products_tcg" ("id") DEFERRABLE INITIALLY DEFERRED;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'products_product_condition_id_fk') THEN
                ALTER TABLE "products_product" ADD CONSTRAINT "products_product_condition_id_fk"
                    FOREIGN KEY ("condition_id") REFERENCES "products_cardcondition" ("id") DEFERRABLE INITIALLY DEFERRED;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'products_product_certificationentity_id_fk') THEN
                ALTER TABLE "products_product" ADD CONSTRAINT "products_product_certificationentity_id_fk"
                    FOREIGN KEY ("certification_entity_id") REFERENCES "products_certificationentity" ("id") DEFERRABLE INITIALLY DEFERRED;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'products_product_certificationgrade_id_fk') THEN
                ALTER TABLE "products_product" ADD CONSTRAINT "products_product_certificationgrade_id_fk"
                    FOREIGN KEY ("certification_grade_id") REFERENCES "products_certificationgrade" ("id") DEFERRABLE INITIALLY DEFERRED;
            END IF;
        END $$;
    """)


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0003_ensure_tables_exist'),
    ]

    operations = [
        migrations.RunPython(fix_product_table, migrations.RunPython.noop),
    ]
