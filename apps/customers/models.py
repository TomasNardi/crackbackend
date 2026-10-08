"""
Customers Models
=================
Comprador con cuenta. La identidad (login, email, Google) vive en Supabase;
acá queda el perfil y lo que se usa para comprar.
"""

from django.db import models


class Customer(models.Model):
    supabase_uid = models.CharField(
        "ID en Supabase", max_length=64, unique=True,
        help_text="`sub` del JWT. Es lo único que une esta fila con Supabase.",
    )
    email = models.EmailField("Email", db_index=True)
    email_verified = models.BooleanField("Email verificado", default=False)
    provider = models.CharField("Entró con", max_length=30, blank=True, help_text="google, email…")

    first_name = models.CharField("Nombre", max_length=120, blank=True)
    last_name = models.CharField("Apellido", max_length=120, blank=True)
    phone = models.CharField("Teléfono", max_length=30, blank=True)
    avatar_url = models.URLField("Avatar", max_length=500, blank=True)

    created_at = models.DateTimeField("Creado", auto_now_add=True)
    last_login_at = models.DateTimeField("Último ingreso", null=True, blank=True)

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ["-created_at"]

    def __str__(self):
        return self.full_name or self.email

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p).strip()


class CustomerAddress(models.Model):
    """Un domicilio, o la sucursal de correo donde retira (envíos a sucursal por
    Paq.ar / Correo Argentino). Cada tipo tiene su propia predeterminada: el
    checkout completa con la que corresponde al método de envío elegido."""

    KIND_HOME = "home"
    KIND_BRANCH = "branch"
    KIND_CHOICES = [
        (KIND_HOME, "Domicilio"),
        (KIND_BRANCH, "Sucursal de correo"),
    ]

    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="addresses", verbose_name="Cliente"
    )
    kind = models.CharField("Tipo", max_length=10, choices=KIND_CHOICES, default=KIND_HOME)
    branch_name = models.CharField(
        "Sucursal", max_length=150, blank=True, help_text="Nombre de la sucursal de correo (opcional)."
    )
    first_name = models.CharField("Nombre", max_length=120, blank=True)
    last_name = models.CharField("Apellido", max_length=120, blank=True)
    phone = models.CharField("Teléfono", max_length=30, blank=True)
    address = models.CharField("Dirección", max_length=255)
    city = models.CharField("Ciudad", max_length=100)
    province = models.CharField("Provincia", max_length=100)
    zip_code = models.CharField("Código postal", max_length=20)
    is_default = models.BooleanField(
        "Predeterminada", default=False, help_text="Predeterminada dentro de su tipo."
    )
    created_at = models.DateTimeField("Creada", auto_now_add=True)

    class Meta:
        verbose_name = "Dirección"
        verbose_name_plural = "Direcciones"
        ordering = ["-is_default", "-created_at"]

    def __str__(self):
        return ", ".join(p for p in (self.address, self.city, self.province) if p)
