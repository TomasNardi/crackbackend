"""
Management command: seed_products
Carga datos de prueba: TCGs, categorías, condiciones, entidades, notas y productos.
Uso: python manage.py seed_products
"""

from decimal import Decimal
from django.core.management.base import BaseCommand
from apps.products.models import (
    TCG, ProductCategory, CardCondition,
    CertificationEntity, CertificationGrade, Product,
)
from apps.core.models import ExchangeRate


class Command(BaseCommand):
    help = "Carga productos de prueba en la base de datos."

    def handle(self, *args, **options):
        self.stdout.write("Seeding database...")

        # Exchange rate
        ExchangeRate.objects.update_or_create(pk=1, defaults={"usd_to_ars": Decimal("1450")})
        self.stdout.write("  ✓ Exchange rate: 1 USD = $1450 ARS")

        # TCGs
        pokemon, _ = TCG.objects.get_or_create(name="Pokémon", defaults={"slug": "pokemon"})
        lorcana, _ = TCG.objects.get_or_create(name="Lorcana", defaults={"slug": "lorcana"})
        one_piece, _ = TCG.objects.get_or_create(name="One Piece", defaults={"slug": "one-piece"})
        self.stdout.write("  ✓ TCGs")

        # Categorías
        cat_single, _ = ProductCategory.objects.get_or_create(name="Single", defaults={"slug": "single"})
        cat_slab, _ = ProductCategory.objects.get_or_create(name="Slab", defaults={"slug": "slab"})
        cat_sellado, _ = ProductCategory.objects.get_or_create(name="Sellado", defaults={"slug": "sellado"})
        cat_accesorio, _ = ProductCategory.objects.get_or_create(name="Accesorio", defaults={"slug": "accesorio"})
        cat_mystery, _ = ProductCategory.objects.get_or_create(name="Mystery Pack", defaults={"slug": "mystery-pack"})
        self.stdout.write("  ✓ Categorías")

        # Condiciones
        nm, _ = CardCondition.objects.get_or_create(name="Near Mint", defaults={"abbreviation": "NM"})
        lp, _ = CardCondition.objects.get_or_create(name="Lightly Played", defaults={"abbreviation": "LP"})
        mp, _ = CardCondition.objects.get_or_create(name="Moderately Played", defaults={"abbreviation": "MP"})
        hp, _ = CardCondition.objects.get_or_create(name="Heavily Played", defaults={"abbreviation": "HP"})
        dmg, _ = CardCondition.objects.get_or_create(name="Damaged", defaults={"abbreviation": "DMG"})
        self.stdout.write("  ✓ Condiciones")

        # Entidades certificadoras
        psa, _ = CertificationEntity.objects.get_or_create(name="PSA", defaults={"abbreviation": "PSA"})
        bgs, _ = CertificationEntity.objects.get_or_create(name="Beckett", defaults={"abbreviation": "BGS"})
        cgc, _ = CertificationEntity.objects.get_or_create(name="CGC", defaults={"abbreviation": "CGC"})
        self.stdout.write("  ✓ Entidades certificadoras")

        # Notas de certificación
        for grade_val in ["10", "9.5", "9", "8.5", "8", "7", "6", "5", "4", "3", "2", "1"]:
            CertificationGrade.objects.get_or_create(grade=Decimal(grade_val))
        grade_10 = CertificationGrade.objects.get(grade=Decimal("10"))
        grade_9 = CertificationGrade.objects.get(grade=Decimal("9"))
        grade_95 = CertificationGrade.objects.get(grade=Decimal("9.5"))
        self.stdout.write("  ✓ Notas de certificación")

        # Productos
        products_data = [
            # Singles Pokémon
            {
                "name": "Charizard VMAX Rainbow Secret",
                "description": "Charizard VMAX en su variante Rainbow Secret Rare. Carta en condición Near Mint, ideal para coleccionistas exigentes.",
                "tcg": pokemon, "category": cat_single, "condition": nm,
                "price_usd": Decimal("120"), "discount_percent": 0,
                "stock_quantity": None, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/swsh3/189_hires.png",
            },
            {
                "name": "Pikachu VMAX Climax CHR",
                "description": "Pikachu VMAX de la colección VMAX Climax. Character Rare con ilustración especial.",
                "tcg": pokemon, "category": cat_single, "condition": nm,
                "price_usd": Decimal("30"), "discount_percent": 15,
                "stock_quantity": None, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/swsh12pt5/44_hires.png",
            },
            {
                "name": "Umbreon VMAX Alt Art",
                "description": "La codiciada Umbreon VMAX en su arte alternativo del set Evolving Skies.",
                "tcg": pokemon, "category": cat_single, "condition": nm,
                "price_usd": Decimal("220"), "discount_percent": 0,
                "stock_quantity": None, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/swsh7/215_hires.png",
            },
            {
                "name": "Rayquaza VMAX Alt Art",
                "description": "Rayquaza VMAX Alt Art del set Evolving Skies. Una de las cartas más espectaculares de la era Sword & Shield.",
                "tcg": pokemon, "category": cat_single, "condition": nm,
                "price_usd": Decimal("180"), "discount_percent": 10,
                "stock_quantity": None, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/swsh7/218_hires.png",
            },
            {
                "name": "Lugia V Alt Art",
                "description": "Lugia V en su arte alternativo del set Silver Tempest. Ilustración épica.",
                "tcg": pokemon, "category": cat_single, "condition": lp,
                "price_usd": Decimal("85"), "discount_percent": 0,
                "stock_quantity": None, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/swsh11/186_hires.png",
            },
            {
                "name": "Mewtwo V Alt Art",
                "description": "Mewtwo V en su arte alternativo del set Pokemon GO. Condición Near Mint.",
                "tcg": pokemon, "category": cat_single, "condition": nm,
                "price_usd": Decimal("45"), "discount_percent": 0,
                "stock_quantity": None, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/pgo/71_hires.png",
            },
            # Slabs
            {
                "name": "Moonbreon PSA 10",
                "description": "Umbreon VMAX Alt Art gradeada PSA 10 Gem Mint. La pieza más exclusiva de nuestra colección.",
                "tcg": pokemon, "category": cat_slab,
                "certification_entity": psa, "certification_grade": grade_10,
                "price_usd": Decimal("650"), "discount_percent": 0,
                "stock_quantity": None, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/swsh7/215_hires.png",
            },
            {
                "name": "Charizard Base Set PSA 9",
                "description": "Charizard Holo de la Base Set original gradeado PSA 9 Mint. Pieza vintage de colección.",
                "tcg": pokemon, "category": cat_slab,
                "certification_entity": psa, "certification_grade": grade_9,
                "price_usd": Decimal("1200"), "discount_percent": 0,
                "stock_quantity": None, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/base1/4_hires.png",
            },
            {
                "name": "Pikachu Illustrator BGS 9.5",
                "description": "Pikachu Illustrator gradeado BGS 9.5 Gem Mint. Una de las cartas más raras del mundo.",
                "tcg": pokemon, "category": cat_slab,
                "certification_entity": bgs, "certification_grade": grade_95,
                "price_usd": Decimal("3500"), "discount_percent": 0,
                "stock_quantity": None, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/promo/30_hires.png",
            },
            # Sellados
            {
                "name": "Scarlet & Violet 151 ETB",
                "description": "Elite Trainer Box del set Scarlet & Violet 151. Incluye 9 booster packs y accesorios.",
                "tcg": pokemon, "category": cat_sellado,
                "price_usd": Decimal("55"), "discount_percent": 10,
                "stock_quantity": 8, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/sv3pt5/198_hires.png",
            },
            {
                "name": "Prismatic Evolutions ETB",
                "description": "Elite Trainer Box de Evoluciones Prismáticas. El set más esperado del año.",
                "tcg": pokemon, "category": cat_sellado,
                "price_usd": Decimal("75"), "discount_percent": 0,
                "stock_quantity": 5, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/sv8pt5/161_hires.png",
            },
            {
                "name": "Surging Sparks Booster Box",
                "description": "Booster Box de Surging Sparks. 36 sobres del set más reciente de Pokémon TCG.",
                "tcg": pokemon, "category": cat_sellado,
                "price_usd": Decimal("140"), "discount_percent": 5,
                "stock_quantity": 3, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/sv8/221_hires.png",
            },
            {
                "name": "One Piece OP-09 Booster Box",
                "description": "Booster Box del set OP-09 de One Piece TCG. 24 sobres con las últimas cartas.",
                "tcg": one_piece, "category": cat_sellado,
                "price_usd": Decimal("90"), "discount_percent": 0,
                "stock_quantity": 4, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/sv8/221_hires.png",
            },
            # Accesorios
            {
                "name": "Ultra Pro Sleeves Pokéball (100u)",
                "description": "Sleeves oficiales de Ultra Pro con diseño Pokéball. Pack de 100 unidades.",
                "tcg": None, "category": cat_accesorio,
                "price_usd": Decimal("12"), "discount_percent": 0,
                "stock_quantity": 25, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/base1/4_hires.png",
            },
            {
                "name": "Dragon Shield Matte Black (100u)",
                "description": "Los mejores sleeves del mercado. Dragon Shield Matte Black, pack de 100 unidades.",
                "tcg": None, "category": cat_accesorio,
                "price_usd": Decimal("18"), "discount_percent": 0,
                "stock_quantity": 20, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/base1/4_hires.png",
            },
            {
                "name": "Ultra Pro 9-Pocket Binder",
                "description": "Carpeta de 9 bolsillos para organizar tu colección. Capacidad para 360 cartas.",
                "tcg": None, "category": cat_accesorio,
                "price_usd": Decimal("22"), "discount_percent": 15,
                "stock_quantity": 12, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/base1/4_hires.png",
            },
            # Mystery Pack
            {
                "name": "Mystery Pack Pokémon — $50 USD",
                "description": "Mystery Pack con cartas Pokémon por valor mínimo de $50 USD. Puede incluir singles, slabs o sellados.",
                "tcg": pokemon, "category": cat_mystery,
                "price_usd": Decimal("50"), "discount_percent": 0,
                "stock_quantity": 10, "in_stock": True,
                "image_url": "https://images.pokemontcg.io/swsh12pt5/44_hires.png",
            },
        ]

        created = 0
        for data in products_data:
            cert_entity = data.pop("certification_entity", None)
            cert_grade = data.pop("certification_grade", None)
            name = data["name"]

            product, was_created = Product.objects.get_or_create(
                name=name,
                defaults={**data, "certification_entity": cert_entity, "certification_grade": cert_grade},
            )
            if was_created:
                created += 1

        self.stdout.write(f"  ✓ {created} productos creados ({len(products_data) - created} ya existían)")
        self.stdout.write(self.style.SUCCESS("✅ Seed completado."))
