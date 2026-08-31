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


class MarkUnlimitedPrintsView(APIView):
    """
    POST /api/v1/catalog/mark-unlimited/

    Body (todo opcional):
        {"sets": ["G2"], "dry_run": true, "revert": false}

    Sin `sets` procesa los ocho de siempre: JU FO TR G1 N1 N2 N3 N4.
    Es idempotente: repetirlo no vuelve a tocar lo ya marcado.
    """

    authentication_classes = [SessionAuthentication, JWTAuthentication]
    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        sets = request.data.get("sets") or None
        if sets is not None and not isinstance(sets, list):
            return Response(
                {"detail": "sets tiene que ser una lista de abreviaturas."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            report = unlimited.mark_unlimited(
                abbreviations=sets,
                revert=bool(request.data.get("revert")),
                dry_run=bool(request.data.get("dry_run")),
            )
        except unlimited.UnknownSetError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(report)
