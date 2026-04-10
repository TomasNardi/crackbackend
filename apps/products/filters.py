"""
Products Filters
=================
"""

import django_filters
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
    min_price = django_filters.NumberFilter(field_name="price_usd", lookup_expr="gte")
    max_price = django_filters.NumberFilter(field_name="price_usd", lookup_expr="lte")
    in_stock = django_filters.BooleanFilter(field_name="in_stock")
    has_discount = django_filters.BooleanFilter(method="filter_has_discount")

    class Meta:
        model = Product
        fields = ["tcg", "category", "condition", "certification_entity", "min_price", "max_price", "in_stock", "has_discount"]

    def filter_has_discount(self, queryset, name, value):
        if value:
            return queryset.filter(discount_percent__gt=0)
        return queryset.filter(discount_percent=0)

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
