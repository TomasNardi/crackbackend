"""
Velocidad del admin (Unfold)
============================
Ajustes al render del admin que no cambian ni un byte del HTML; solo evitan
trabajo repetido. En Render cada milisegundo de CPU local son varios en el
servidor, y cada consulta es un viaje a la base. Es lo mismo que se hizo en
Delta Old (tareas/admin_rendimiento.py), que bajó las páginas de 8 s a 1 s.

1. Encabezados por fila. `items_for_result` recalcula TODOS los encabezados
   (`result_headers`) para cada fila, solo para leer el texto que va en
   `data-label`. Dependen del listado, no de la fila: se calculan una vez por
   request y se reusan.

2. Checkbox de selección. `action_checkbox` pasa por el motor de templates de
   los widgets en cada fila. El HTML es idéntico salvo el pk: se renderiza una
   vez (por idioma, porque lleva un aria-label traducido) y se reemplaza el pk.

3. Filas editables (`list_editable`). El stock, el "en stock" y el descuento
   de cada fila de Productos también pasaban por el motor de templates uno por
   uno. Se renderiza uno por variante y se reemplazan name/id/valor.

4. `/admin/jsi18n/` (un <script> que bloquea cada listado y formulario) pasa a
   cachearse en el navegador: ver `_cache_jsi18n`.

5. `singleton_exists`: las configuraciones de fila única (tipo de cambio,
   estado del sitio, eBay) preguntan "¿ya existe?" en cada página del admin
   para decidir si se muestra "Agregar". Una vez creada no se borra.

Se aplica desde `CoreConfig.ready()`. Si una versión futura de Unfold cambia
estas funciones, el parche no se aplica y todo sigue andando como antes.
"""

from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import get_language

_PK_MARK = "__crack_pk__"

# ---------------------------------------------------------------- singletons
_CREATED_SINGLETONS = set()


def singleton_exists(model):
    """¿Ya existe la fila única? El menú lo pregunta en cada página del admin.

    Una vez creada no se borra (el admin no deja), así que alcanza con
    preguntarle a la base hasta la primera vez que dice que sí.
    """
    if model in _CREATED_SINGLETONS:
        return True
    if model.objects.exists():
        _CREATED_SINGLETONS.add(model)
        return True
    return False


# ---------------------------------------------------------------- listados
def _patch_headers(unfold_list):
    original = unfold_list.result_headers
    if getattr(original, "_crack_cached", False):
        return

    def result_headers(cl):
        # Se guarda en el ChangeList, que vive lo que dura el request.
        cache = cl.__dict__.get("_crack_result_headers")
        if cache is None:
            cache = list(original(cl))
            cl._crack_result_headers = cache
        return iter(cache)

    result_headers._crack_cached = True
    unfold_list.result_headers = result_headers


def _patch_checkbox(unfold_admin):
    original = unfold_admin.ModelAdmin.action_checkbox
    if getattr(original, "_crack_cached", False):
        return

    widget = unfold_admin.checkbox
    name = unfold_admin.helpers.ACTION_CHECKBOX_NAME
    templates = {}

    def action_checkbox(self, obj):
        language = get_language()
        template = templates.get(language)
        if template is None:
            template = str(widget.render(name, _PK_MARK))
            templates[language] = template
        return mark_safe(template.replace(_PK_MARK, escape(str(obj.pk))))

    # El encabezado (el "seleccionar todo") se mantiene tal cual.
    action_checkbox.short_description = original.short_description
    action_checkbox._crack_cached = True
    unfold_admin.ModelAdmin.action_checkbox = action_checkbox


_NAME_MARK = "__crack_name__"
_ID_MARK = "__crack_id__"
_VALUE_MARK = "__crack_value__"


class _FastRenderMixin:
    """Widget que pasa por el motor de templates una sola vez por "forma".

    Las filas editables del listado (`list_editable`) repiten el mismo widget
    con distinto name/id/valor. Se renderiza uno con marcas en esos lugares y
    para el resto se reemplazan las marcas, escapadas igual que el template.
    """

    _templates = {}

    def render(self, name, value, attrs=None, renderer=None):
        from django.forms import CheckboxInput

        attrs = dict(attrs or {})
        id_attr = attrs.pop("id", None)
        if id_attr is not None:
            attrs["id"] = _ID_MARK

        if isinstance(self, CheckboxInput):
            # El checkbox no lleva value cuando el valor es booleano; lo que
            # cambia entre filas es si va tildado.
            if self.format_value(value) is not None:
                return super().render(name, value, attrs=_with_id(attrs, id_attr), renderer=renderer)
            formatted = None
            variant = bool(self.check_test(value))
            template_value = value
        else:
            formatted = self.format_value(value)
            variant = formatted is None
            template_value = None if formatted is None else _VALUE_MARK

        key = (
            type(self), self.template_name, get_language(), type(renderer),
            tuple(sorted((k, str(v)) for k, v in self.build_attrs(self.attrs, attrs).items())),
            variant,
        )
        template = self._templates.get(key)
        if template is None:
            template = str(super().render(_NAME_MARK, template_value, attrs=attrs, renderer=renderer))
            marks = [_NAME_MARK] + ([_ID_MARK] if id_attr is not None else []) + (
                [_VALUE_MARK] if formatted is not None else []
            )
            if any(template.count(m) != 1 for m in marks):
                # Forma inesperada: se renderiza normal y no se cachea.
                return super().render(name, value, attrs=_with_id(attrs, id_attr), renderer=renderer)
            self._templates[key] = template

        html = template.replace(_NAME_MARK, escape(name))
        if id_attr is not None:
            html = html.replace(_ID_MARK, escape(id_attr))
        if formatted is not None:
            html = html.replace(_VALUE_MARK, escape(formatted))
        return mark_safe(html)


def _with_id(attrs, id_attr):
    attrs = dict(attrs)
    if id_attr is None:
        attrs.pop("id", None)
    else:
        attrs["id"] = id_attr
    return attrs


_fast_classes = {}


def _speed_up_widget(widget):
    from django.forms import CheckboxInput, HiddenInput, NumberInput

    cls = type(widget)
    if isinstance(widget, _FastRenderMixin) or not isinstance(widget, (CheckboxInput, HiddenInput, NumberInput)):
        return
    fast = _fast_classes.get(cls)
    if fast is None:
        fast = type(f"Fast{cls.__name__}", (_FastRenderMixin, cls), {})
        _fast_classes[cls] = fast
    widget.__class__ = fast


def _patch_editable_formset(unfold_admin):
    original = unfold_admin.ModelAdmin.get_changelist_formset
    if getattr(original, "_crack_cached", False):
        return

    def get_changelist_formset(self, request, **kwargs):
        base = original(self, request, **kwargs)

        class FastFormset(base):
            def add_fields(self, form, index):
                # Acá ya están todos los campos, incluido el pk oculto.
                super().add_fields(form, index)
                for field in form.fields.values():
                    _speed_up_widget(field.widget)

        FastFormset.__name__ = base.__name__
        return FastFormset

    get_changelist_formset._crack_cached = True
    unfold_admin.ModelAdmin.get_changelist_formset = get_changelist_formset


def _cache_jsi18n():
    """El catálogo de traducciones JS del admin (/admin/jsi18n/).

    Es un <script> que bloquea el render de cada listado y cada formulario, y
    Django lo sirve sin caché: un viaje entero al servidor por página. Solo
    cambia si se actualiza Django, así que el navegador puede guardarlo un día.
    Tiene que correr antes de que se arme el URLconf (lo garantiza `ready()`).
    """
    from django.contrib import admin
    from django.utils.cache import patch_cache_control

    original = admin.site.i18n_javascript
    if getattr(original, "_crack_cached", False):
        return

    def i18n_javascript(request, extra_context=None):
        response = original(request, extra_context)
        if response.status_code == 200:
            patch_cache_control(response, private=True, max_age=60 * 60 * 24)
        return response

    i18n_javascript._crack_cached = True
    admin.site.i18n_javascript = i18n_javascript


def apply():
    _cache_jsi18n()

    try:
        from unfold import admin as unfold_admin
        from unfold.templatetags import unfold_list
    except ImportError:
        return

    if callable(getattr(unfold_list, "result_headers", None)) and hasattr(unfold_list, "items_for_result"):
        _patch_headers(unfold_list)

    if (
        hasattr(unfold_admin, "checkbox")
        and hasattr(unfold_admin.ModelAdmin, "action_checkbox")
        and hasattr(unfold_admin.ModelAdmin.action_checkbox, "short_description")
    ):
        _patch_checkbox(unfold_admin)

    if hasattr(unfold_admin.ModelAdmin, "get_changelist_formset"):
        _patch_editable_formset(unfold_admin)
