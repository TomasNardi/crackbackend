"""Shipping carrier catalog and lookup helpers."""

CARRIER_CORREO_ARGENTINO = "correo_argentino"
CARRIER_ANDREANI = "andreani"

CARRIER_CHOICES = [
    (CARRIER_CORREO_ARGENTINO, "Correo Argentino"),
    (CARRIER_ANDREANI, "Andreani"),
]

CARRIER_TRACKING_URLS = {
    CARRIER_CORREO_ARGENTINO: "https://www.correoargentino.com.ar/seguimiento-de-envios",
    CARRIER_ANDREANI: "https://www.andreani.com/",
}

DEFAULT_CARRIER = CARRIER_CORREO_ARGENTINO
DEFAULT_CARRIER_LABEL = "Correo"


def get_carrier_label(carrier: str | None) -> str:
    carrier_value = (carrier or "").strip()
    return dict(CARRIER_CHOICES).get(carrier_value, DEFAULT_CARRIER_LABEL)



def get_carrier_tracking_url(carrier: str | None) -> str:
    carrier_value = (carrier or "").strip()
    return CARRIER_TRACKING_URLS.get(carrier_value, "")
