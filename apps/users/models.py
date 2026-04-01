"""
Users Models
=============
Extiende el User de Django con un perfil custom.
Preparado para el showroom de cartas en fases futuras.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Usuario custom. Hereda todo de AbstractUser (username, email, password, etc.)
    y agrega campos propios del negocio.
    """

    email = models.EmailField(unique=True)

    # Datos de contacto
    phone = models.CharField(max_length=30, blank=True)

    # Dirección de envío por defecto (para agilizar el checkout)
    default_address = models.TextField(blank=True)
    default_city = models.CharField(max_length=100, blank=True)
    default_province = models.CharField(max_length=100, blank=True)
    default_zip = models.CharField(max_length=20, blank=True)

    # Showroom / colección (fase 2)
    # Cuando se active el showroom, estos campos cobran vida.
    is_collector = models.BooleanField(
        default=False,
        help_text="Habilita el acceso al showroom personal de cartas.",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    def __str__(self):
        return self.email
