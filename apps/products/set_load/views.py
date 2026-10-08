"""
Adaptador HTTP de la carga masiva. Traduce request → caso de uso → JSON.

Se cuelgan de ProductAdmin.get_urls() envueltas en `admin_site.admin_view`
(staff + CSRF en el POST) y en `requires_add_permission` (poder crear productos).
"""

import json
import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from ..bulk_load import requires_add_permission
from ..services.cloudinary_service import CloudinaryValidationError
from . import services
from .domain import BatchInvalid

logger = logging.getLogger(__name__)


@require_GET
@requires_add_permission
def set_view(request, set_id):
    """GET carga-stock/set/<id>/ → el set completo para la grilla."""
    try:
        return JsonResponse(services.view_set(set_id))
    except services.SetNotFound:
        return JsonResponse({"error": "Esa expansión no existe."}, status=404)


@require_POST
@requires_add_permission
def save_view(request):
    """POST carga-stock/guardar-masivo/ con {request_id, items: [...]}"""
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "No se pudo leer la carga."}, status=400)

    try:
        result = services.save(data.get("request_id"), data.get("items"), request.user)
    except BatchInvalid as exc:
        return JsonResponse({"error": exc.message, "errors": exc.errors}, status=400)
    except DjangoValidationError as exc:
        # La transacción ya se deshizo: no quedó nada a medias.
        return JsonResponse({"error": "No se guardó nada. " + " ".join(exc.messages)}, status=400)
    except CloudinaryValidationError as exc:
        return JsonResponse({"error": f"No se guardó nada. {exc}"}, status=400)

    logger.info(
        "Carga masiva de %s: %s creados, %s actualizados, %s unidades%s",
        request.user, result["created"], result["updated"], result["units"],
        " (reintento)" if result["repeated"] else "",
    )
    return JsonResponse(result)
