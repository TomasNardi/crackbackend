"""
Products Filters
=================
Filtros para el endpoint de productos.
"""

import django_filters
from .models import Product


class ProductFilter(django_filters.FilterSet):
    tcg = django_filters.CharFilter(field_name="tcg__slug")
    expansion = django_filters.CharFilter(field_name="expansion__slug")
    product_type = django_filters.CharFilter(field_name="product_type__name", lookup_expr="iexact")
    condition = django_filters.CharFilter(field_name="condition__name", lookup_expr="iexact")
    min_price = django_filters.NumberFilter(field_name="price", lookup_expr="gte")
    max_price = django_filters.NumberFilter(field_name="price", lookup_expr="lte")
    in_stock = django_filters.BooleanFilter(field_name="in_stock")
    is_single = django_filters.BooleanFilter(field_name="is_single")
    has_discount = django_filters.BooleanFilter(method="filter_has_discount")

    class Meta:
        model = Product
        fields = [
            "tcg", "expansion", "product_type", "condition",
            "min_price", "max_price", "in_stock", "is_single", "has_discount",
        ]

    def filter_has_discount(self, queryset, name, value):
        if value:
            return queryset.filter(discount_percent__gt=0)
        return queryset.filter(discount_percent=0)
