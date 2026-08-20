"""
TEMPORAL — rutas para consolidar los duplicados viejos desde el navegador.

Existen solo porque correr el comando contra la base de Render desde una
conexión doméstica se corta a mitad. Corren en el servidor, donde la base está
al lado, y devuelven texto plano.

Para borrarlas cuando termines: eliminá este archivo y las dos entradas
`duplicados/` de `ProductAdmin.get_urls`. No hay nada más enganchado.

    /admin/products/product/duplicados/          → simulacro, no toca nada
    /admin/products/product/duplicados/?aplicar=SI-JUNTAR-DUPLICADOS  → lo hace
"""

from functools import wraps

from django.http import HttpResponse

from .services.merge_duplicates import merge_duplicate_products

# Sin esto en la URL no se borra nada: evita que un prefetch del navegador o un
# link mal clickeado dispare la consolidación.
CONFIRM_TOKEN = "SI-JUNTAR-DUPLICADOS"


def requires_delete_permission(view):
    """`admin_view` ya exige staff; esto además exige poder borrar productos."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.has_perm("products.delete_product"):
            return HttpResponse("No tenés permiso para borrar productos.", status=403)
        return view(request, *args, **kwargs)

    return wrapper


@requires_delete_permission
def merge_view(request):
    apply_changes = request.GET.get("aplicar") == CONFIRM_TOKEN
    report = merge_duplicate_products(apply=apply_changes)

    lines = []
    if apply_changes:
        lines.append("MODO APLICAR — los cambios quedaron guardados.")
    else:
        lines.append("SIMULACRO — no se tocó nada.")
        lines.append(f"Para aplicarlo: agregá ?aplicar={CONFIRM_TOKEN} a esta URL.")
    lines.append("")

    if not report["lines"] and not report["skipped"]:
        lines.append("No hay publicaciones duplicadas.")
        return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")

    lines.extend(report["lines"])
    lines.append("")

    verbo = "Consolidadas" if apply_changes else "Se consolidarían"
    lines.append(
        f"{verbo} {report['merged']} publicaciones · "
        f"{report['removed']} duplicados eliminados."
    )

    if report["skipped"]:
        lines.append("")
        lines.append("Quedaron sin tocar (revisalas a mano):")
        lines.extend(f"- {warning}" for warning in report["skipped"])

    return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")
