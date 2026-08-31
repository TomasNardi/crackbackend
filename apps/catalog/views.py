"""
Catalog Views
=============

⚠️  TEMPORAL — BORRAR DESPUÉS DE CORRERLO EN PRODUCCIÓN.

Existe solo para poder correr `mark_unlimited_prints` contra la base de prod sin
entrar al Shell de Render. Una vez marcado el catálogo, borrar:
  1. este archivo,
  2. el import y el `path("catalog/mark-unlimited/", ...)` de crackbackend/api_router.py.

El comando de consola y `import_catalog` siguen funcionando igual sin esto.
"""

from rest_framework import permissions, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.catalog.services import unlimited

TRUTHY = {"1", "true", "t", "yes", "y", "si", "sí"}


def _flag(raw):
    """Lee un booleano de la query string: ?dry_run=1, ?revert=true, etc."""
    return str(raw).strip().lower() in TRUTHY if raw is not None else False


class MarkUnlimitedPrintsView(APIView):
    """
    GET/POST /api/v1/catalog/mark-unlimited/

    El GET está para poder dispararlo desde el navegador, con la sesión del
    admin de Django. Sí, un GET que escribe: es un one-shot que se borra apenas
    esté corrido, y la operación es idempotente y reversible con ?revert=1.

    GET  ?sets=FO,N1&dry_run=1&revert=1
    POST {"sets": ["FO"], "dry_run": true, "revert": false}

    Sin `sets` procesa los nueve afectados: JU FO TR G1 G2 N1 N2 N3 N4.
    Repetirlo no vuelve a tocar lo ya marcado.
    """

    authentication_classes = [SessionAuthentication, JWTAuthentication]
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        raw_sets = (request.query_params.get("sets") or "").strip()
        return self._run(
            sets=[part for part in raw_sets.split(",") if part.strip()] or None,
            revert=_flag(request.query_params.get("revert")),
            dry_run=_flag(request.query_params.get("dry_run")),
        )

    def post(self, request):
        sets = request.data.get("sets") or None
        if sets is not None and not isinstance(sets, list):
            return Response(
                {"detail": "sets tiene que ser una lista de abreviaturas."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return self._run(
            sets=sets,
            revert=bool(request.data.get("revert")),
            dry_run=bool(request.data.get("dry_run")),
        )

    def _run(self, sets, revert, dry_run):
        try:
            report = unlimited.mark_unlimited(
                abbreviations=sets, revert=revert, dry_run=dry_run,
            )
        except unlimited.UnknownSetError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(report)
