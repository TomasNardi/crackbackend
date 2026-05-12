"""
Shipping service
================
Pricing resolution for shipping methods based on admin-configured values.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.orders.models import Order, ShippingConfig


BA_PROVINCE_NAMES = {
    "buenos aires",
    "caba",
    "ciudad autonoma de buenos aires",
    "ciudad autónoma de buenos aires",
    "capital federal",
}


class ShippingPricingError(ValidationError):
    """Validation error for shipping pricing rules."""


def normalize_shipping_zone(shipping_province: str, explicit_zone: str = "") -> str:
    zone = (explicit_zone or "").strip().lower()
    if zone in {Order.SHIPPING_ZONE_BA, Order.SHIPPING_ZONE_PROVINCE}:
        return zone

    province = (shipping_province or "").strip().lower()
    if province in BA_PROVINCE_NAMES:
        return Order.SHIPPING_ZONE_BA
    return Order.SHIPPING_ZONE_PROVINCE


def get_shipping_config_key(shipping_method: str, shipping_zone: str) -> str:
    method = (shipping_method or "").strip()
    zone = (shipping_zone or "").strip()

    if method == Order.SHIPPING_METHOD_HOME:
        if zone == Order.SHIPPING_ZONE_BA:
            return ShippingConfig.KEY_HOME_BA
        if zone == Order.SHIPPING_ZONE_PROVINCE:
            return ShippingConfig.KEY_HOME_PROVINCE

    if method == Order.SHIPPING_METHOD_BRANCH_NORMAL:
        if zone == Order.SHIPPING_ZONE_BA:
            return ShippingConfig.KEY_BRANCH_NORMAL_BA
        if zone == Order.SHIPPING_ZONE_PROVINCE:
            return ShippingConfig.KEY_BRANCH_NORMAL_PROVINCE

    if method == Order.SHIPPING_METHOD_BRANCH_EXPRESS:
        if zone == Order.SHIPPING_ZONE_BA:
            return ShippingConfig.KEY_BRANCH_EXPRESS_BA
        if zone == Order.SHIPPING_ZONE_PROVINCE:
            return ShippingConfig.KEY_BRANCH_EXPRESS_PROVINCE

    raise ShippingPricingError("Combinación de método/zona de envío inválida.")


def validate_shipping_method_zone(shipping_method: str, shipping_zone: str) -> None:
    if shipping_method == Order.SHIPPING_METHOD_HOME and shipping_zone not in {
        Order.SHIPPING_ZONE_BA,
        Order.SHIPPING_ZONE_PROVINCE,
    }:
        raise ShippingPricingError("Zona de domicilio inválida.")


def resolve_shipping_price(shipping_method: str, shipping_zone: str) -> Decimal:
    validate_shipping_method_zone(shipping_method, shipping_zone)
    config_key = get_shipping_config_key(shipping_method, shipping_zone)

    config = ShippingConfig.objects.filter(key=config_key).first()
    if not config:
        raise ShippingPricingError(
            f"No existe configuración de envío para '{config_key}'. Configúrala en admin."
        )

    return Decimal(config.price)


def get_shipping_method_label(shipping_method: str, shipping_zone: str) -> str:
    if shipping_method == Order.SHIPPING_METHOD_STORE_PICKUP:
        return "PickUp en tienda"
    zone_label = "BA" if shipping_zone == Order.SHIPPING_ZONE_BA else "Provincia"
    if shipping_method == Order.SHIPPING_METHOD_BRANCH_NORMAL:
        return f"Sucursal Normal {zone_label}"
    if shipping_method == Order.SHIPPING_METHOD_BRANCH_EXPRESS:
        return f"Sucursal Express {zone_label}"
    if shipping_method == Order.SHIPPING_METHOD_HOME:
        return f"Domicilio {zone_label}"
    return "Método no definido"


def get_checkout_shipping_prices() -> dict:
    """Returns frontend-ready shipping price map from ShippingConfig."""
    config_map = {
        row["key"]: row["price"]
        for row in ShippingConfig.objects.values("key", "price")
    }

    return {
        "branch": {
            "ba": {
                "normal": float(config_map.get(ShippingConfig.KEY_BRANCH_NORMAL_BA, Decimal("0"))),
                "express": float(config_map.get(ShippingConfig.KEY_BRANCH_EXPRESS_BA, Decimal("0"))),
            },
            "province": {
                "normal": float(config_map.get(ShippingConfig.KEY_BRANCH_NORMAL_PROVINCE, Decimal("0"))),
                "express": float(config_map.get(ShippingConfig.KEY_BRANCH_EXPRESS_PROVINCE, Decimal("0"))),
            },
        },
        "home": {
            "ba": {
                "normal": float(config_map.get(ShippingConfig.KEY_HOME_BA, Decimal("0"))),
            },
            "province": {
                "normal": float(config_map.get(ShippingConfig.KEY_HOME_PROVINCE, Decimal("0"))),
            },
        },
    }
