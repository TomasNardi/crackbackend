"""
Products Models
================
Catálogo de productos: slabs, sellados, singles, accesorios, mystery packs.

Decisiones de diseño:
- ProductType y CardCondition son tablas de lookup editables desde el admin.
- Product usa slug auto-generado para URLs amigables.
- Las imágenes son URLs externas (Cloudinary, S3, etc.) — sin uploads locales.
- Discount se maneja a nivel de producto (porcentaje) y a nivel de orden (código).
"""

from django.db import models
from django.utils.text import slugify
from django.core.exceptions import ValidationError


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


class Expansion(models.Model):
    """Expansión / set de un TCG. Ej: 'Base Set', 'Scarlet & Violet'."""

    tcg = models.ForeignKey(TCG, on_delete=models.CASCADE, related_name="expansions")
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True, blank=True)

    class Meta:
        verbose_name = "Expansión"
        verbose_name_plural = "Expansiones"
        ordering = ["tcg", "name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f"{self.tcg.name}-{self.name}")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.tcg.name} — {self.name}"


class ProductType(models.Model):
    """
    Tipo de producto. Valores esperados:
    - Slab (carta certificada)
    - Sellado (booster box, ETB, etc.)
    - Single (carta suelta)
    - Accesorio
    - Mystery Pack
    """

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "Tipo de producto"
        verbose_name_plural = "Tipos de producto"

    def __str__(self):
        return self.name


class CardCondition(models.Model):
    """
    Estado / condición de la carta.
    Ej: PSA 10, BGS 9.5, NM, LP, MP, HP, DMG.
    """

    name = models.CharField(max_length=100, unique=True)
    abbreviation = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = "Condición"
        verbose_name_plural = "Condiciones"

    def __str__(self):
        return self.name


class Product(models.Model):
    """
    Producto del catálogo.

    Campos clave:
    - product_type: slab / sellado / single / accesorio / mystery pack
    - is_single: True si es una carta suelta (no tiene cantidad, es 1 unidad)
    - stock_quantity: solo para productos no-single (sellados, accesorios, etc.)
    - discount_percent: descuento directo sobre el precio (0 = sin descuento)
    """

    # Clasificación
    tcg = models.ForeignKey(
        TCG, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    expansion = models.ForeignKey(
        Expansion, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    product_type = models.ForeignKey(
        ProductType, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    condition = models.ForeignKey(
        CardCondition, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )

    # Identificación
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True, blank=True)
    description = models.TextField(blank=True)

    # Precio
    price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_percent = models.PositiveSmallIntegerField(
        default=0,
        help_text="Porcentaje de descuento directo (0 = sin descuento).",
    )

    # Stock
    is_single = models.BooleanField(
        default=True,
        help_text="True = carta suelta (1 unidad). False = producto con cantidad.",
    )
    stock_quantity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Solo para productos no-single. Dejar vacío si es single.",
    )
    in_stock = models.BooleanField(default=True)

    # Imágenes (URLs externas — Cloudinary, S3, etc.)
    image_url = models.URLField(max_length=600, blank=True)
    image_url_2 = models.URLField(max_length=600, blank=True)
    image_url_3 = models.URLField(max_length=600, blank=True)

    # Referencia externa (PriceCharting, etc.)
    pricecharting_url = models.URLField(max_length=600, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Producto"
        verbose_name_plural = "Productos"
        ordering = ["-created_at"]

    def clean(self):
        if not self.is_single and self.in_stock and self.stock_quantity is None:
            raise ValidationError(
                f"'{self.name}' no es single — ingresá la cantidad disponible."
            )
        if self.is_single and self.stock_quantity is not None:
            raise ValidationError("Un producto single no puede tener cantidad.")

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
    def final_price(self):
        """Precio final aplicando descuento."""
        if self.discount_percent:
            from decimal import Decimal
            factor = (100 - self.discount_percent) / Decimal("100")
            return round(self.price * factor, 2)
        return self.price

    def __str__(self):
        return self.name
