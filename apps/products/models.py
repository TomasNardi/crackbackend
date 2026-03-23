"""
Products Models
================
Catálogo de productos: slabs, sellados, singles, accesorios, mystery packs.

Categorías soportadas:
  - Single       → lleva condition (FK)
  - Slab         → lleva certification_entity + certification_grade (FK)
  - Sellado      → sin campos extra
  - Accesorio    → sin campos extra (tcg opcional)
  - Mystery Pack → sin campos extra
"""

from django.db import models
from django.utils.text import slugify


class TCG(models.Model):
    """Juego de cartas: Pokémon, Lorcana, One Piece, Yu-Gi-Oh!, etc."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)

    class Meta:
        verbose_name = "TCG"
        verbose_name_plural = "TCGs"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ProductCategory(models.Model):
    """
    Categoría de producto.
    Valores base: Single, Slab, Sellado, Accesorio, Mystery Pack.
    """

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)

    class Meta:
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class CardCondition(models.Model):
    """
    Estado de una carta suelta.
    Ej: NM (Near Mint), LP (Lightly Played), MP, HP, DMG.
    """

    name = models.CharField(max_length=100, unique=True)
    abbreviation = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = "Condición"
        verbose_name_plural = "Condiciones"
        ordering = ["name"]

    def __str__(self):
        return f"{self.abbreviation} — {self.name}" if self.abbreviation else self.name


class CertificationEntity(models.Model):
    """
    Entidad certificadora de slabs.
    Ej: PSA, BGS (Beckett), CGC, SGC.
    """

    name = models.CharField(max_length=100, unique=True)
    abbreviation = models.CharField(max_length=20, unique=True)

    class Meta:
        verbose_name = "Entidad certificadora"
        verbose_name_plural = "Entidades certificadoras"
        ordering = ["name"]

    def __str__(self):
        return self.abbreviation


class CertificationGrade(models.Model):
    """
    Nota de certificación. Ej: 10, 9.5, 9, 8.5, ...
    Se carga una vez desde el admin y se reutiliza en todos los slabs.
    """

    grade = models.DecimalField(max_digits=4, decimal_places=1, unique=True)

    class Meta:
        verbose_name = "Nota de certificación"
        verbose_name_plural = "Notas de certificación"
        ordering = ["-grade"]

    def __str__(self):
        return str(self.grade)


class Product(models.Model):
    """
    Producto del catálogo.

    Campos condicionales según categoría:
      - Single:  condition
      - Slab:    certification_entity + certification_grade
      - Resto:   ninguno extra
    """

    # Clasificación
    tcg = models.ForeignKey(
        TCG, on_delete=models.SET_NULL, null=True, blank=True, related_name="products",
        help_text="Obligatorio para Singles, Slabs y Sellados. Opcional para Accesorios.",
    )
    category = models.ForeignKey(
        ProductCategory, on_delete=models.PROTECT, related_name="products",
    )

    # Identificación
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True, blank=True)
    description = models.TextField(blank=True)

    # Precio en USD (el admin lo carga en dólares)
    price_usd = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Precio en dólares. El sistema convierte a ARS automáticamente.",
    )
    discount_percent = models.PositiveSmallIntegerField(
        default=0,
        help_text="Porcentaje de descuento (0 = sin descuento).",
    )

    # Stock
    stock_quantity = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Dejar vacío si es un producto único (slab, single).",
    )
    in_stock = models.BooleanField(default=True)

    # Imágenes (URLs externas — Cloudinary, S3, etc.)
    image_url = models.URLField(max_length=600, blank=True)
    image_url_2 = models.URLField(max_length=600, blank=True)
    image_url_3 = models.URLField(max_length=600, blank=True)

    # Referencia externa
    pricecharting_url = models.URLField(max_length=600, blank=True)

    # --- Campos exclusivos de Singles ---
    condition = models.ForeignKey(
        CardCondition, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="products",
        help_text="Solo para Singles.",
    )

    # --- Campos exclusivos de Slabs ---
    certification_entity = models.ForeignKey(
        CertificationEntity, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="products",
        help_text="Solo para Slabs.",
    )
    certification_grade = models.ForeignKey(
        CertificationGrade, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="products",
        help_text="Solo para Slabs.",
    )

    # Timestamps (auto)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Producto"
        verbose_name_plural = "Productos"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:260]
            slug, counter = base, 1
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def price_ars(self):
        """Precio en ARS según el tipo de cambio actual."""
        from apps.core.models import ExchangeRate
        from decimal import Decimal
        rate = ExchangeRate.get().usd_to_ars
        return round(self.price_usd * rate, 2)

    @property
    def final_price(self):
        """Precio final en ARS aplicando descuento."""
        from decimal import Decimal
        price = self.price_ars
        if self.discount_percent:
            factor = (100 - self.discount_percent) / Decimal("100")
            return round(price * factor, 2)
        return price

    def __str__(self):
        return self.name
