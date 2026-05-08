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

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.text import slugify
from ckeditor.fields import RichTextField


UNIQUE_PRODUCT_CATEGORIES = {"single", "singles", "slab", "slabs"}


def _build_unique_slug(model_class, raw_name, current_pk=None, max_length=280):
    """Genera un slug único y lo recalcula cuando cambia el nombre."""
    base = slugify(raw_name)[:max_length].strip("-")
    if not base:
        base = "item"

    slug = base
    counter = 1
    while model_class.objects.filter(slug=slug).exclude(pk=current_pk).exists():
        suffix = f"-{counter}"
        allowed = max_length - len(suffix)
        slug = f"{base[:allowed].rstrip('-')}{suffix}"
        counter += 1

    return slug


class TCG(models.Model):
    """Juego de cartas: Pokémon, Lorcana, One Piece, Yu-Gi-Oh!, etc."""

    name = models.CharField("Nombre", max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)

    class Meta:
        verbose_name = "TCG"
        verbose_name_plural = "TCGs"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.slug = _build_unique_slug(TCG, self.name, self.pk, max_length=120)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ProductCategory(models.Model):
    """
    Categoría de producto.
    Valores base: Single, Slab, Sellado, Accesorio, Mystery Pack.
    """

    name = models.CharField("Nombre", max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)

    class Meta:
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.slug = _build_unique_slug(ProductCategory, self.name, self.pk, max_length=120)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class CardCondition(models.Model):
    """
    Estado de una carta suelta.
    Ej: NM (Near Mint), LP (Lightly Played), MP, HP, DMG.
    """

    name = models.CharField("Nombre", max_length=100, unique=True)
    abbreviation = models.CharField("Abreviatura", max_length=20, blank=True)

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

    name = models.CharField("Nombre", max_length=100, unique=True)
    abbreviation = models.CharField("Abreviatura", max_length=20, unique=True)

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

    grade = models.DecimalField("Nota", max_digits=4, decimal_places=1, unique=True)

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
        verbose_name="TCG",
        help_text="Obligatorio para Singles, Slabs y Sellados. Opcional para Accesorios.",
    )
    category = models.ForeignKey(
        ProductCategory, on_delete=models.PROTECT, related_name="products",
        verbose_name="Categoría",
    )

    # Identificación
    name = models.CharField("Nombre", max_length=255)
    slug = models.SlugField(max_length=280, unique=True, blank=True)
    description = RichTextField("Descripción", blank=True)

    # Precio en USD (el admin lo carga en dólares)
    price_usd = models.DecimalField(
        "Precio USD", max_digits=10, decimal_places=2,
        help_text="Precio en dólares. El sistema convierte a ARS automáticamente.",
    )
    discount_percent = models.PositiveSmallIntegerField(
        "% Descuento", default=0,
        help_text="Porcentaje de descuento (0 = sin descuento).",
    )

    # Stock
    stock_quantity = models.PositiveIntegerField(
        "Cantidad en stock", null=True, blank=True,
        help_text="Dejar vacío si es un producto único (slab, single). Para Singles y Slabs, el sistema fuerza automáticamente stock = 1 si el producto está en stock.",
    )
    in_stock = models.BooleanField("En stock", default=True)

    # Imágenes (URLs externas — Cloudinary, S3, etc.)
    image_url = models.URLField("Imagen principal", max_length=600, blank=True)
    image_url_2 = models.URLField("Imagen 2", max_length=600, blank=True)
    image_url_3 = models.URLField("Imagen 3", max_length=600, blank=True)

    suggested_products = models.ManyToManyField(
        "self",
        blank=True,
        symmetrical=False,
        related_name="suggested_in",
        verbose_name="Productos sugeridos",
        help_text="Seleccionar hasta 3 productos sugeridos para el carrusel del detalle.",
    )

    # Calificación promedio (0.0 – 5.0)
    rating = models.DecimalField(
        "Calificación", max_digits=3, decimal_places=1, default=0,
        help_text="Calificación promedio del producto (0.0 – 5.0).",
    )
    rating_count = models.PositiveIntegerField(
        "Cant. calificaciones", default=0,
        help_text="Cantidad de calificaciones recibidas.",
    )

    # Referencia externa
    pricecharting_url = models.URLField("URL PriceCharting", max_length=600, blank=True)

    # --- Campos exclusivos de Singles ---
    condition = models.ForeignKey(
        CardCondition, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="products",
        verbose_name="Condición",
        help_text="Solo para Singles.",
    )

    # --- Campos exclusivos de Slabs ---
    certification_entity = models.ForeignKey(
        CertificationEntity, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="products",
        verbose_name="Certificadora",
        help_text="Solo para Slabs.",
    )
    certification_grade = models.ForeignKey(
        CertificationGrade, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="products",
        verbose_name="Nota certificación",
        help_text="Solo para Slabs.",
    )

    # Timestamps (auto)
    created_at = models.DateTimeField("Creado", auto_now_add=True)
    updated_at = models.DateTimeField("Actualizado", auto_now=True)

    class Meta:
        verbose_name = "Producto"
        verbose_name_plural = "Productos"
        ordering = ["-created_at"]

    def is_unique_product(self):
        category_name = self.category.name if self.category_id and self.category else ""
        return category_name.strip().lower() in UNIQUE_PRODUCT_CATEGORIES

    def normalize_stock(self):
        if self.is_unique_product():
            self.stock_quantity = 1 if self.in_stock else 0
            return

        if self.stock_quantity is not None:
            self.in_stock = self.stock_quantity > 0

    def save(self, *args, **kwargs):
        self.normalize_stock()
        self.slug = _build_unique_slug(Product, self.name, self.pk, max_length=280)
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

    def get_ordered_images(self):
        return list(self.images.order_by("order_index", "id")[:3])

    def sync_legacy_images_from_gallery(self, save=True):
        ordered = self.get_ordered_images()
        urls = [img.secure_url for img in ordered]
        while len(urls) < 3:
            urls.append("")

        self.image_url, self.image_url_2, self.image_url_3 = urls[0], urls[1], urls[2]
        if save:
            self.save(update_fields=["image_url", "image_url_2", "image_url_3", "updated_at"])


class ProductImage(models.Model):
    SOURCE_CLOUDINARY = "cloudinary"
    SOURCE_URL = "url"
    SOURCE_CHOICES = (
        (SOURCE_CLOUDINARY, "Cloudinary"),
        (SOURCE_URL, "URL externa"),
    )

    STATUS_PENDING = "pending"
    STATUS_UPLOADED = "uploaded"
    STATUS_CONFIRMED = "confirmed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pendiente"),
        (STATUS_UPLOADED, "Subida"),
        (STATUS_CONFIRMED, "Confirmada"),
        (STATUS_FAILED, "Fallida"),
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="images",
        verbose_name="Producto",
    )
    draft_token = models.CharField(
        "Draft token",
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Permite persistir imágenes antes de guardar el producto.",
    )
    secure_url = models.URLField("Secure URL", max_length=800)
    public_id = models.CharField("Public ID", max_length=255, blank=True, db_index=True)
    source = models.CharField("Origen", max_length=20, choices=SOURCE_CHOICES, default=SOURCE_CLOUDINARY)
    order_index = models.PositiveSmallIntegerField("Orden", default=0)
    width = models.PositiveIntegerField("Ancho", null=True, blank=True)
    height = models.PositiveIntegerField("Alto", null=True, blank=True)
    bytes = models.PositiveIntegerField("Bytes", null=True, blank=True)
    format = models.CharField("Formato", max_length=20, blank=True)
    status = models.CharField("Estado", max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    metadata = models.JSONField("Metadata", default=dict, blank=True)
    upload_error = models.TextField("Error de upload", blank=True)
    uploaded_at = models.DateTimeField("Subido", auto_now_add=True)
    confirmed_at = models.DateTimeField("Confirmado", null=True, blank=True)

    class Meta:
        verbose_name = "Imagen de producto"
        verbose_name_plural = "Imágenes de producto"
        ordering = ["order_index", "id"]
        constraints = [
            models.CheckConstraint(
                check=Q(order_index__gte=0) & Q(order_index__lte=2),
                name="products_img_order_between_0_2",
            ),
            models.CheckConstraint(
                check=Q(product__isnull=False) | ~Q(draft_token=""),
                name="products_img_requires_product_or_draft",
            ),
            models.UniqueConstraint(
                fields=["product", "order_index"],
                condition=Q(product__isnull=False),
                name="products_img_unique_order_per_product",
            ),
        ]

    def clean(self):
        if not self.product_id and not self.draft_token:
            raise ValidationError("La imagen debe estar asociada a un producto o draft token.")

        if self.product_id:
            siblings = ProductImage.objects.filter(product_id=self.product_id).exclude(pk=self.pk)
            if siblings.count() >= 3:
                raise ValidationError("Cada producto admite máximo 3 imágenes.")

    def __str__(self):
        target = self.product_id or self.draft_token
        return f"{target} · {self.order_index}"


class ProductImageWebhookEvent(models.Model):
    EVENT_UPLOAD = "upload"
    EVENT_DELETE = "delete"
    EVENT_EAGER = "eager"
    EVENT_OTHER = "other"
    EVENT_CHOICES = (
        (EVENT_UPLOAD, "Upload"),
        (EVENT_DELETE, "Delete"),
        (EVENT_EAGER, "Eager"),
        (EVENT_OTHER, "Other"),
    )

    event_type = models.CharField("Evento", max_length=30, choices=EVENT_CHOICES, default=EVENT_OTHER)
    public_id = models.CharField("Public ID", max_length=255, blank=True, db_index=True)
    payload = models.JSONField("Payload", default=dict)
    is_valid_signature = models.BooleanField("Firma válida", default=False)
    processed = models.BooleanField("Procesado", default=False)
    error = models.TextField("Error", blank=True)
    created_at = models.DateTimeField("Creado", auto_now_add=True)
    processed_at = models.DateTimeField("Procesado en", null=True, blank=True)

    class Meta:
        verbose_name = "Webhook de imagen"
        verbose_name_plural = "Webhooks de imágenes"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} · {self.public_id or '-'}"
