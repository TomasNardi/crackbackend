"""
Verificación de los JWT de Supabase Auth.

Supabase firma el access token de una de dos maneras, según el proyecto:

  - Claves asimétricas (ES256/RS256): lo que traen los proyectos nuevos. Se
    valida con la clave pública de `/auth/v1/.well-known/jwks.json`, así que el
    servidor no guarda ningún secreto.
  - Secreto compartido (HS256): el esquema "legacy". Hace falta el JWT secret
    del proyecto en SUPABASE_JWT_SECRET.

Se mira el `alg` del encabezado y se valida con lo que corresponda; así una
rotación de HS256 a ES256 en Supabase no corta las sesiones abiertas.

Además de la firma se controla que no esté vencido, que lo haya emitido ESTE
proyecto (`iss`), que sea de un usuario logueado (`aud`) y que no sea anónimo.
"""

from dataclasses import dataclass
from functools import lru_cache

import jwt
from django.conf import settings

AUDIENCE = "authenticated"
CLOCK_LEEWAY_SECONDS = 30


class InvalidToken(Exception):
    """El token no lo firmó Supabase, venció o no es de este proyecto."""


class AuthNotConfigured(Exception):
    """Falta SUPABASE_URL: las cuentas de clientes están apagadas."""


@dataclass(frozen=True)
class Identity:
    uid: str
    email: str
    email_verified: bool
    provider: str
    name: str
    avatar_url: str


def identity_from_claims(claims) -> Identity:
    if claims.get("is_anonymous"):
        raise InvalidToken("Las sesiones anónimas no tienen cuenta.")
    if claims.get("role") != "authenticated":
        raise InvalidToken("El token no es de un usuario logueado.")

    meta = claims.get("user_metadata") or {}
    app = claims.get("app_metadata") or {}
    provider = str(app.get("provider") or "email")
    email = str(claims.get("email") or "").strip().lower()
    if not email:
        raise InvalidToken("La cuenta no tiene email.")

    # Google informa `email_verified`. Con email, Supabase solo entrega sesión
    # después de que el comprador puso el código que le llegó al mail, así que
    # el email ya está probado (ver SUPABASE_TRUST_EMAIL_PROVIDER en settings).
    verified = meta.get("email_verified") is True or (
        provider == "email" and settings.SUPABASE_TRUST_EMAIL_PROVIDER
    )
    return Identity(
        uid=str(claims["sub"]),
        email=email,
        email_verified=verified,
        provider=provider,
        name=str(meta.get("full_name") or meta.get("name") or "").strip()[:240],
        avatar_url=str(meta.get("avatar_url") or meta.get("picture") or "")[:500],
    )


class SupabaseVerifier:
    def __init__(self, project_url: str, jwt_secret: str = ""):
        self._issuer = f"{project_url.rstrip('/')}/auth/v1"
        self._secret = jwt_secret
        # PyJWKClient cachea las claves: el JWKS se baja una vez cada
        # `lifespan` segundos, no en cada request.
        self._jwks = jwt.PyJWKClient(
            f"{self._issuer}/.well-known/jwks.json", cache_keys=True, lifespan=600, timeout=5
        )

    def _key_and_algorithms(self, token):
        try:
            alg = jwt.get_unverified_header(token).get("alg")
        except jwt.PyJWTError as exc:
            raise InvalidToken("El token está mal formado.") from exc

        if alg == "HS256":
            if not self._secret:
                raise InvalidToken("Este servidor no acepta tokens HS256 (falta SUPABASE_JWT_SECRET).")
            return self._secret, ["HS256"]
        try:
            return self._jwks.get_signing_key_from_jwt(token).key, ["ES256", "RS256"]
        except jwt.PyJWKClientError as exc:
            raise InvalidToken(f"No se pudo obtener la clave pública: {exc}") from exc

    def verify(self, token: str) -> Identity:
        if not token:
            raise InvalidToken("Falta el token.")
        key, algorithms = self._key_and_algorithms(token)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=algorithms,
                audience=AUDIENCE,
                issuer=self._issuer,
                leeway=CLOCK_LEEWAY_SECONDS,
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise InvalidToken("La sesión venció.") from exc
        except jwt.PyJWTError as exc:
            raise InvalidToken(f"Token rechazado: {exc}") from exc
        return identity_from_claims(claims)


@lru_cache(maxsize=1)
def get_verifier() -> SupabaseVerifier:
    """Uno por proceso: guarda en memoria las claves públicas de Supabase."""
    if not settings.SUPABASE_URL:
        raise AuthNotConfigured("Las cuentas de clientes no están disponibles por ahora.")
    return SupabaseVerifier(settings.SUPABASE_URL, settings.SUPABASE_JWT_SECRET)
