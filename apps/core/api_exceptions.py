"""
Handler de excepciones de la API.

Lo que sale por acá lo lee el cliente en pantalla, así que ningún mensaje
puede ser jerga técnica ni sonar a error de sistema.

El caso que arregla es el rate limit: `django_ratelimit` levanta `Ratelimited`,
que hereda de `PermissionDenied`, así que DRF por defecto responde 403 con
"Usted no tiene permiso para realizar esta acción" — le dice al cliente que no
tiene permiso cuando en realidad consultó de más, y encima trata de usted en un
sitio que vosea.
"""

from django_ratelimit.exceptions import Ratelimited
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

TOO_MANY_REQUESTS = 429


def api_exception_handler(exc, context):
    if isinstance(exc, Ratelimited):
        return Response(
            {
                "detail": (
                    "Estás haciendo muchas consultas seguidas. "
                    "Esperá unos minutos y volvé a intentar."
                ),
                "code": "rate_limited",
            },
            status=TOO_MANY_REQUESTS,
        )

    return drf_exception_handler(exc, context)
