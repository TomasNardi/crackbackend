"""
Products Filters
=================
"""

from decimal import Decimal, InvalidOperation

import django_filters
from django.db.models import DecimalField, ExpressionWrapper, F, Value
from django.db.models.functions import Cast

from .models import Product


class MultiValueCharFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    """Acepta un único valor o varios separados por coma: ?tcg=pokemon,lorcana"""
    pass


class ProductFilter(django_filters.FilterSet):
    tcg = MultiValueCharFilter(field_name="tcg__slug", lookup_expr="in")
    category = MultiValueCharFilter(field_name="category__slug", lookup_expr="in")
    condition = MultiValueCharFilter(field_name="condition__abbreviation", lookup_expr="in", method="filter_condition")
    certification_entity = MultiValueCharFilter(
        field_name="certification_entity__abbreviation",
        lookup_expr="in",
        method="filter_certification_entity",
    )
    # Los precios llegan en ARS (es lo que ve el usuario en la tienda), no en USD.
    min_price = django_filters.NumberFilter(method="filter_min_price")
    max_price = django_filters.NumberFilter(method="filter_max_price")
    in_stock = django_filters.BooleanFilter(field_name="in_stock")
    has_discount = django_filters.BooleanFilter(method="filter_has_discount")

    class Meta:
        model = Product
        fields = ["tcg", "category", "condition", "certification_entity", "min_price", "max_price", "in_stock", "has_discount"]

    def filter_has_discount(self, queryset, name, value):
        if value:
            return queryset.filter(discount_percent__gt=0)
        return queryset.filter(discount_percent=0)

    def _annotate_final_price_ars(self, queryset):
        """
        Anota el precio final en ARS —el mismo número que ve el usuario en la card—
        multiplicado por 100: price_usd * cotización * (100 - descuento).

        Se trabaja escalado x100 para no dividir dentro del SQL: en SQLite una
        división entre enteros ((100 - descuento) / 100) trunca a 0 y anularía
        el precio de todo producto con descuento.
        """
        if "final_price_ars_x100" in queryset.query.annotations:
            return queryset

        from apps.core.models import ExchangeRate

        rate = ExchangeRate.get().usd_to_ars
        price_ars = ExpressionWrapper(
            F("price_usd") * Value(rate),
            output_field=DecimalField(max_digits=14, decimal_places=4),
        )
        remaining = Cast(
            Value(100) - F("discount_percent"),
            DecimalField(max_digits=5, decimal_places=2),
        )
        return queryset.annotate(
            final_price_ars_x100=ExpressionWrapper(
                price_ars * remaining,
                output_field=DecimalField(max_digits=16, decimal_places=4),
            )
        )

    def _price_value(self, value):
        """Convierte el valor recibido (ARS) a la escala x100 de la anotación."""
        try:
            return Decimal(str(value)) * 100
        except (InvalidOperation, TypeError, ValueError):
            return None

    def filter_min_price(self, queryset, name, value):
        amount = self._price_value(value)
        if amount is None:
            return queryset
        return self._annotate_final_price_ars(queryset).filter(final_price_ars_x100__gte=amount)

    def filter_max_price(self, queryset, name, value):
        amount = self._price_value(value)
        if amount is None:
            return queryset
        return self._annotate_final_price_ars(queryset).filter(final_price_ars_x100__lte=amount)

    def _normalize_multi_values(self, value):
        if value is None:
            return []
        if isinstance(value, str):
            raw_values = value.split(",")
        else:
            raw_values = value
        return [item.strip().upper() for item in raw_values if item and item.strip()]

    def filter_condition(self, queryset, name, value):
        abbreviations = self._normalize_multi_values(value)
        if not abbreviations:
            return queryset
        return queryset.filter(condition__abbreviation__in=abbreviations)

    def filter_certification_entity(self, queryset, name, value):
        abbreviations = self._normalize_multi_values(value)
        if not abbreviations:
            return queryset
        return queryset.filter(certification_entity__abbreviation__in=abbreviations)
