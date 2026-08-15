"""
Importa el catálogo de cartas desde tcgcsv.com.

Solo trae datos (nombre, número, rareza, set): las imágenes se bajan aparte con
`sync_catalog_images`, porque eso sí tarda. Este comando corre en minutos.

Es idempotente: se puede volver a correr cuando sale un set nuevo y solo agrega
o actualiza lo que cambió.

Uso:
    python manage.py import_catalog                  # Pokémon inglés + japonés
    python manage.py import_catalog --language en    # solo inglés
    python manage.py import_catalog --sets-only      # solo expansiones, sin cartas
    python manage.py import_catalog --dry-run        # muestra qué haría
"""

from datetime import datetime
from datetime import timezone as dt_timezone

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.catalog.models import CardSet, CatalogCard
from apps.catalog.services import tcgcsv
from apps.products.models import TCG

BATCH_SIZE = 500


class Command(BaseCommand):
    help = "Importa expansiones y cartas de Pokémon desde tcgcsv.com"

    def add_arguments(self, parser):
        parser.add_argument(
            "--language", choices=["en", "ja", "all"], default="all",
            help="Idioma a importar. Por defecto los dos.",
        )
        parser.add_argument(
            "--sets-only", action="store_true",
            help="Importa solo las expansiones, sin las cartas.",
        )
        parser.add_argument(
            "--limit-sets", type=int, default=0,
            help="Corta después de N expansiones. Útil para probar.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="No escribe en la base; solo informa.",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Rebaja todas las expansiones, incluso las que no cambiaron.",
        )

    def handle(self, *args, **options):
        language = options["language"]
        dry_run = options["dry_run"]
        limit_sets = options["limit_sets"]

        categories = []
        if language in ("en", "all"):
            categories.append(tcgcsv.CATEGORY_POKEMON_EN)
        if language in ("ja", "all"):
            categories.append(tcgcsv.CATEGORY_POKEMON_JA)

        tcg = self._get_pokemon_tcg(dry_run)

        totals = {"sets": 0, "cards": 0, "skipped": 0}

        for category_id in categories:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\nCategoría {category_id} ({tcgcsv.CATEGORY_LANGUAGES[category_id]})"
            ))

            try:
                groups = tcgcsv.fetch_groups(category_id)
            except tcgcsv.TcgCsvError as exc:
                raise CommandError(str(exc)) from exc

            if limit_sets:
                groups = groups[:limit_sets]

            for index, group in enumerate(groups, start=1):
                unchanged = self._is_unchanged(group) and not options["force"]

                card_set, created = self._upsert_set(tcg, group, category_id, dry_run)
                totals["sets"] += 1

                label = "nueva" if created else "ok"
                prefix = f"  [{index}/{len(groups)}] {group.get('name')}"

                if options["sets_only"]:
                    self.stdout.write(f"{prefix} — {label}")
                    continue

                # Traer las cartas es una request por expansión. Si la fuente dice
                # que no cambió, no tiene sentido volver a pedirla.
                if unchanged and not created:
                    totals["skipped"] += 1
                    continue

                count = self._import_cards(card_set, category_id, group, dry_run)
                totals["cards"] += count
                self.stdout.write(f"{prefix} — {label}, {count} cartas")

        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {totals['sets']} expansiones, {totals['cards']} cartas."
        ))
        if totals["skipped"]:
            self.stdout.write(
                f"Se saltearon {totals['skipped']} expansiones sin cambios "
                f"(usá --force para rebajarlas igual)."
            )
        if dry_run:
            self.stdout.write(self.style.WARNING("(dry-run: no se escribió nada)"))
        elif not options["sets_only"]:
            pending = CatalogCard.objects.filter(image_status=CatalogCard.IMAGE_PENDING).count()
            self.stdout.write(
                f"Faltan bajar {pending} imágenes. "
                f"Corré: python manage.py sync_catalog_images"
            )

    # ------------------------------------------------------------------ #

    def _get_pokemon_tcg(self, dry_run):
        tcg = TCG.objects.filter(name__iexact="Pokémon").first() or \
            TCG.objects.filter(name__iexact="Pokemon").first()

        if tcg:
            return tcg

        if dry_run:
            self.stdout.write(self.style.WARNING("No existe el TCG 'Pokémon'; se crearía."))
            return TCG(name="Pokémon", slug="pokemon")

        tcg = TCG.objects.create(name="Pokémon")
        self.stdout.write(self.style.SUCCESS("Se creó el TCG 'Pokémon'."))
        return tcg

    def _is_unchanged(self, group):
        """
        True si la expansión ya está importada y la fuente no la tocó desde entonces.

        Las expansiones recién salidas se revisan igual: TCGplayer les sigue
        sumando cartas durante semanas y `modifiedOn` no siempre lo refleja.
        """
        stored = CardSet.objects.filter(external_id=group["groupId"]).values(
            "source_modified_at", "released_at",
        ).first()

        if not stored or not stored["source_modified_at"]:
            return False

        released = stored["released_at"]
        if released and (timezone.now().date() - released).days < 90:
            return False

        modified = self._parse_datetime(group.get("modifiedOn"))
        if not modified:
            return False

        return modified <= stored["source_modified_at"]

    def _upsert_set(self, tcg, group, category_id, dry_run):
        external_id = group["groupId"]
        published = self._parse_date(group.get("publishedOn"))

        defaults = {
            "tcg": tcg,
            "name": group.get("name") or f"Set {external_id}",
            "abbreviation": (group.get("abbreviation") or "").strip()[:50],
            "language": tcgcsv.CATEGORY_LANGUAGES[category_id],
            "released_at": published,
            "is_supplemental": bool(group.get("isSupplemental")),
            "source_modified_at": self._parse_datetime(group.get("modifiedOn")),
        }

        if dry_run:
            exists = CardSet.objects.filter(external_id=external_id).exists()
            return CardSet(external_id=external_id, **defaults), not exists

        # El slug se calcula solo la primera vez, para no romper URLs ya publicadas.
        card_set = CardSet.objects.filter(external_id=external_id).first()
        if card_set:
            for field, value in defaults.items():
                setattr(card_set, field, value)
            card_set.save()
            return card_set, False

        defaults["slug"] = self._unique_set_slug(defaults["name"], defaults["language"], external_id)
        card_set = CardSet.objects.create(external_id=external_id, **defaults)
        return card_set, True

    def _unique_set_slug(self, name, language, external_id):
        base = slugify(f"{name}-{language}")[:270] or f"set-{external_id}"
        slug = base
        counter = 1
        while CardSet.objects.filter(slug=slug).exists():
            suffix = f"-{counter}"
            slug = f"{base[:270 - len(suffix)]}{suffix}"
            counter += 1
        return slug

    def _import_cards(self, card_set, category_id, group, dry_run):
        try:
            products = tcgcsv.fetch_products(category_id, group["groupId"])
        except tcgcsv.TcgCsvError as exc:
            self.stderr.write(self.style.ERROR(f"    {exc}"))
            return 0

        if dry_run:
            return len(products)

        rows = []
        for product in products:
            number = tcgcsv.extended_value(product, "Number")
            rarity = tcgcsv.extended_value(product, "Rarity")
            name = (product.get("name") or "").strip()[:255]

            card = CatalogCard(
                card_set=card_set,
                external_id=product["productId"],
                name=name,
                number=number[:50],
                rarity=rarity[:100],
                source_url=(product.get("url") or "")[:600],
                source_image_url=tcgcsv.high_res_image_url(product["productId"]),
                extended_data=tcgcsv.flatten_extended_data(product),
            )
            # bulk_create no dispara save(), así que el texto de búsqueda se arma acá.
            card.search_text = card.build_search_text()
            rows.append(card)

        with transaction.atomic():
            CatalogCard.objects.bulk_create(
                rows,
                batch_size=BATCH_SIZE,
                update_conflicts=True,
                unique_fields=["external_id"],
                update_fields=[
                    "card_set", "name", "number", "rarity",
                    "search_text", "source_url", "extended_data", "updated_at",
                ],
            )

        return len(rows)

    @classmethod
    def _parse_date(cls, raw):
        parsed = cls._parse_datetime(raw)
        return parsed.date() if parsed else None

    @staticmethod
    def _parse_datetime(raw):
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
        # La fuente manda fechas sin zona; las tratamos como UTC.
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, dt_timezone.utc)
        return parsed
