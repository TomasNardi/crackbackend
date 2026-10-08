"""
Autenticación DRF con el token de Supabase.

¿Por qué un header propio (`X-Customer-Token`) y no `Authorization: Bearer`?
La autenticación global del proyecto es `JWTAuthentication` de SimpleJWT (la
del staff). Si el token de Supabase viajara en `Authorization`, SimpleJWT
intentaría validarlo en todos los endpoints —incluido el que crea la orden— y
respondería 401: el comprador logueado no podría comprar.
"""

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from .services import get_or_create_customer, token_from_request
from .supabase_auth import AuthNotConfigured, InvalidToken, get_verifier


class CustomerUser:
    """Lo que queda en `request.user` cuando entra un comprador.

    No es un `User` de Django —los compradores no están en `users_user` ni
    pueden entrar al admin— pero cumple lo que DRF le pide a un usuario.
    """

    is_authenticated = True
    is_anonymous = False
    is_staff = False
    is_superuser = False

    def __init__(self, customer, identity):
        self.customer = customer
        self.identity = identity
        # El throttle agrupa por `pk`: el prefijo evita compartir cupo con el
        # usuario de staff que tenga el mismo número.
        self.pk = f"customer-{customer.pk}"

    def get_username(self):
        return self.customer.email


class CustomerAuthentication(BaseAuthentication):
    def authenticate(self, request):
        token = token_from_request(request)
        if not token:
            return None
        try:
            identity = get_verifier().verify(token)
        except (InvalidToken, AuthNotConfigured) as exc:
            raise AuthenticationFailed(str(exc)) from exc
        return CustomerUser(get_or_create_customer(identity), identity), token

    def authenticate_header(self, request):
        # Con esto DRF responde 401 (y no 403) cuando falta la sesión.
        return 'Bearer realm="customers"'


class IsCustomer(BasePermission):
    message = "Iniciá sesión para ver esto."

    def has_permission(self, request, view):
        return isinstance(request.user, CustomerUser)
