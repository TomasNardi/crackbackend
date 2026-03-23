"""
Migración de seguridad: crea las tablas que pueden faltar en producción
usando CREATE TABLE IF NOT EXISTS — idempotente, no rompe nada si ya existen.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0002_remove_product_price_product_price_usd'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
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

            CREATE TABLE IF NOT EXISTS "products_product" (
                "id" bigserial NOT NULL PRIMARY KEY,
                "name" varchar(255) NOT NULL,
                "slug" varchar(280) NOT NULL UNIQUE,
                "description" text NOT NULL,
                "price_usd" numeric(10, 2) NOT NULL,
                "discount_percent" smallint NOT NULL,
                "stock_quantity" integer NULL,
                "in_stock" boolean NOT NULL,
                "image_url" varchar(600) NOT NULL,
                "image_url_2" varchar(600) NOT NULL,
                "image_url_3" varchar(600) NOT NULL,
                "pricecharting_url" varchar(600) NOT NULL,
                "created_at" timestamp with time zone NOT NULL,
                "updated_at" timestamp with time zone NOT NULL,
                "category_id" bigint NOT NULL REFERENCES "products_productcategory" ("id"),
                "tcg_id" bigint NULL REFERENCES "products_tcg" ("id"),
                "condition_id" bigint NULL REFERENCES "products_cardcondition" ("id"),
                "certification_entity_id" bigint NULL REFERENCES "products_certificationentity" ("id"),
                "certification_grade_id" bigint NULL REFERENCES "products_certificationgrade" ("id")
            );
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
