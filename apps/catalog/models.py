"""
Catalog Models
==============
Catálogo de referencia de cartas, importado desde el dump público de TCGplayer
(tcgcsv.com). Es solo material de consulta: NO es stock ni se vende.

El flujo es:
    CatalogCard  →  se busca en el admin  →  autocompleta un Product (tu stock)

Un CatalogCard existe aunque nunca lo vendas. Un Product es lo que la gente compra.

Las imágenes se descargan una vez del CDN de TCGplayer, se convierten a WebP en
tres tamaños y se suben a Cloudflare R2 (ver services/images.py).
"""

from django.db import models
from django.utils.text import slugify


class CardSet(models.Model):
    """
    Expansión / set. Equivale a un "group" de TCGplayer.

    Un mismo set puede existir en inglés y japonés como dos registros distintos,
    porque TCGplayer los publica en categorías separadas (3 = EN, 85 = JP).
    """

    LANGUAGE_EN = "en"
    LANGUAGE_JA = "ja"
    LANGUAGE_CHOICES = (
        (LANGUAGE_EN, "Inglés"),
        (LANGUAGE_JA, "Japonés"),
    )

    tcg = models.ForeignKey(
        "products.TCG",
        on_delete=models.CASCADE,
        related_name="card_sets",
        verbose_name="TCG",
    )

    # ID del "group" en TCGplayer. Es la clave para reimportar sin duplicar.
    external_id = models.BigIntegerField("ID externo", unique=True, db_index=True)

    name = models.CharField("Nombre", max_length=255)
    abbreviation = models.CharField(
        "Abreviatura", max_length=50, blank=True, db_index=True,
        help_text='Código corto del set. Ej: "SV9a", "s12a".',
    )
    slug = models.SlugField(max_length=280, unique=True, blank=True)
    language = models.CharField(
        "Idioma", max_length=5, choices=LANGUAGE_CHOICES, default=LANGUAGE_EN, db_index=True,
    )

    released_at = models.DateField("Fecha de salida", null=True, blank=True)
    is_supplemental = models.BooleanField(
        "Suplementario", default=False,
        help_text="Promos, decks y productos fuera de las expansiones principales.",
    )

    # Última modificación según la fuente. Permite saltear en cada refresco las
    # expansiones que no cambiaron, en vez de rebajar las 672 todas las veces.
    source_modified_at = models.DateTimeField(
        "Modificado en origen", null=True, blank=True,
    )

    imported_at = models.DateTimeField("Importado", auto_now=True)

    class Meta:
        verbose_name = "Expansión"
        verbose_name_plural = "Expansiones"
        ordering = ["-released_at", "name"]
        indexes = [
            models.Index(fields=["language", "name"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f"{self.name}-{self.language}")[:270] or f"set-{self.external_id}"
            self.slug = base
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        """Nombre con la bandera del idioma, para los desplegables del admin."""
        flag = "🇯🇵" if self.language == self.LANGUAGE_JA else "🇺🇸"
        return f"{flag} {self.name}"

    def __str__(self):
        return self.display_name


class CatalogCard(models.Model):
    """
    Una carta del catálogo. Equivale a un "product" de TCGplayer.

    Ojo: acá no hay precio, stock ni condición. Todo eso vive en Product.
    """

    IMAGE_PENDING = "pending"
    IMAGE_READY = "ready"
    IMAGE_FAILED = "failed"
    IMAGE_STATUS_CHOICES = (
        (IMAGE_PENDING, "Pendiente"),
        (IMAGE_READY, "Lista"),
        (IMAGE_FAILED, "Fallida"),
    )

    card_set = models.ForeignKey(
        CardSet, on_delete=models.CASCADE, related_name="cards", verbose_name="Expansión",
    )

    # ID del "product" en TCGplayer. Clave para reimportar sin duplicar.
    external_id = models.BigIntegerField("ID externo", unique=True, db_index=True)

    name = models.CharField("Nombre", max_length=255, db_index=True)
    number = models.CharField("Número", max_length=50, blank=True, db_index=True)
    rarity = models.CharField("Rareza", max_length=100, blank=True, db_index=True)

    # Texto denormalizado para el buscador del admin: nombre + número + set + abreviatura.
    # Se recalcula en save(); evita hacer joins y LIKEs sobre varias tablas.
    search_text = models.CharField("Texto de búsqueda", max_length=600, blank=True, db_index=True)

    # --- Origen ---
    source_url = models.URLField("URL de origen", max_length=600, blank=True)
    source_image_url = models.URLField("Imagen de origen", max_length=600, blank=True)

    # --- Imágenes propias (Cloudflare R2) ---
    image_url = models.URLField("Imagen", max_length=600, blank=True)
    image_url_medium = models.URLField("Imagen media", max_length=600, blank=True)
    image_url_thumb = models.URLField("Miniatura", max_length=600, blank=True)
    image_status = models.CharField(
        "Estado de imagen", max_length=20, choices=IMAGE_STATUS_CHOICES,
        default=IMAGE_PENDING, db_index=True,
    )
    image_error = models.TextField("Error de imagen", blank=True)

    extended_data = models.JSONField("Datos extra", default=dict, blank=True)

    created_at = models.DateTimeField("Creado", auto_now_add=True)
    updated_at = models.DateTimeField("Actualizado", auto_now=True)

    class Meta:
        verbose_name = "Carta del catálogo"
        verbose_name_plural = "Catálogo de cartas"
        ordering = ["card_set", "number"]
        indexes = [
            models.Index(fields=["card_set", "number"]),
            models.Index(fields=["image_status"]),
        ]

    def build_search_text(self):
        parts = [self.name, self.number, self.rarity]
        if self.card_set_id:
            parts.extend([self.card_set.name, self.card_set.abbreviation])
        return " ".join(p for p in parts if p)[:600]

    def save(self, *args, **kwargs):
        self.search_text = self.build_search_text()
        super().save(*args, **kwargs)

    @property
    def has_image(self):
        return self.image_status == self.IMAGE_READY and bool(self.image_url)

    @property
    def display_name(self):
        """Ej: 'Charizard - 4/102 · Base Set'"""
        head = f"{self.name}"
        if self.number and self.number not in self.name:
            head = f"{head} - {self.number}"
        return f"{head} · {self.card_set.name}" if self.card_set_id else head

    def __str__(self):
        return self.display_name
