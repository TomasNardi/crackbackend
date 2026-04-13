"""
Paq.ar (Correo Argentino) — Cliente API v1
==========================================
Documentación: Correo Argentino – Plataforma de Integración – Api 2.0

Endpoints implementados:
  GET  /v1/auth                              → validar credenciales
  POST /v1/orders                            → alta de orden
  PATCH /v1/orders/{trackingNumber}/cancel   → cancelar orden
  POST /v1/labels                            → obtener rótulo PDF en base64
  GET  /v1/tracking                          → historial de una orden
  GET  /v1/agencies                          → sucursales habilitadas
"""

import logging
from datetime import datetime

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Mapa provincia Argentina → código Paq.ar
PROVINCE_CODES = {
    "salta": "A",
    "provincia de buenos aires": "B",
    "buenos aires": "B",
    "ciudad autónoma de buenos aires": "C",
    "caba": "C",
    "san luis": "D",
    "entre ríos": "E",
    "entre rios": "E",
    "la rioja": "F",
    "santiago del estero": "G",
    "chaco": "H",
    "san juan": "J",
    "catamarca": "K",
    "la pampa": "L",
    "mendoza": "M",
    "misiones": "N",
    "formosa": "P",
    "neuquén": "Q",
    "neuquen": "Q",
    "río negro": "R",
    "rio negro": "R",
    "santa fe": "S",
    "tucumán": "T",
    "tucuman": "T",
    "chubut": "U",
    "tierra del fuego": "V",
    "corrientes": "W",
    "córdoba": "X",
    "cordoba": "X",
    "jujuy": "Y",
    "santa cruz": "Z",
}


def _get_province_code(province_name: str) -> str:
    """Convierte nombre de provincia al código de Paq.ar."""
    if not province_name:
        return settings.PAQAR_SENDER_STATE
    code = PROVINCE_CODES.get(province_name.strip().lower())
    if not code:
        logger.warning("Provincia no reconocida para Paq.ar: %s — usando CABA por defecto", province_name)
        return "C"
    return code


def _headers() -> dict:
    return {
        "Authorization": f"Apikey {settings.PAQAR_API_KEY}",
        "agreement": str(settings.PAQAR_AGREEMENT),
        "Content-Type": "application/json",
    }


def _url(path: str) -> str:
    return f"{settings.PAQAR_BASE_URL}{path}"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def validate_credentials() -> bool:
    """Valida las credenciales contra Paq.ar. Retorna True si son válidas."""
    try:
        resp = requests.get(
            _url("/auth"),
            headers=_headers(),
            timeout=10,
        )
        return resp.status_code == 204
    except requests.RequestException as exc:
        logger.error("Paq.ar auth error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Alta de orden
# ---------------------------------------------------------------------------

def create_order(order) -> dict:
    """
    Crea una orden en Paq.ar para el objeto Order de Django.
    Retorna el dict de respuesta o lanza PaqarError.

    Campos del modelo Order que se usan:
      customer_name, customer_email, customer_phone,
      shipping_address, shipping_city, shipping_province, shipping_zip,
      shipping_type (home→homeDelivery, pickup→agency),
      shipping_branch (agencyId cuando es pickup),
      total (declaredValue),
      order_code (shipmentClientId),
      created_at (saleDate),
    """
    from .models import Order

    delivery_type_map = {
        Order.SHIPPING_HOME: "homeDelivery",
        Order.SHIPPING_PICKUP: "agency",
    }
    delivery_type = delivery_type_map.get(order.shipping_type, "homeDelivery")

    # Partir nombre en calle / altura (el modelo guarda todo junto en shipping_address)
    address_parts = (order.shipping_address or "").split(" ", 1)
    street_name = address_parts[0] if address_parts else "S/N"
    street_number = address_parts[1] if len(address_parts) > 1 else "S/N"

    # Teléfono: separar area code (primero 2-4 dígitos) del número
    raw_phone = (order.customer_phone or "").strip().replace(" ", "").replace("-", "")
    area_code = raw_phone[:2] if len(raw_phone) >= 2 else ""
    phone_number = raw_phone[2:] if len(raw_phone) > 2 else raw_phone

    # Fecha de venta en formato ISO con offset -03:00
    sale_date = order.created_at.strftime("%Y-%m-%dT%H:%M:%S-03:00")

    payload = {
        "sellerId": str(settings.PAQAR_AGREEMENT),
        "order": {
            "senderData": {
                "id": str(settings.PAQAR_AGREEMENT),
                "businessName": settings.PAQAR_SENDER_NAME,
                "areaCodePhone": "",
                "phoneNumber": settings.PAQAR_SENDER_PHONE,
                "email": settings.PAQAR_SENDER_EMAIL,
                "observation": "",
                "address": {
                    "streetName": settings.PAQAR_SENDER_STREET,
                    "streetNumber": settings.PAQAR_SENDER_STREET_NUMBER,
                    "cityName": settings.PAQAR_SENDER_CITY,
                    "floor": "",
                    "department": "",
                    "state": settings.PAQAR_SENDER_STATE,
                    "zipCode": settings.PAQAR_SENDER_ZIP,
                },
            },
            "shippingData": {
                "name": order.customer_name,
                "areaCodePhone": "",
                "phoneNumber": raw_phone,
                "areaCodeCellphone": area_code,
                "cellphoneNumber": phone_number,
                "email": order.customer_email,
                "observation": "",
                "address": {
                    "streetName": street_name,
                    "streetNumber": street_number,
                    "cityName": order.shipping_city,
                    "floor": "",
                    "department": "",
                    "state": _get_province_code(order.shipping_province),
                    "zipCode": order.shipping_zip,
                },
            },
            "parcels": [
                {
                    "dimensions": {
                        "height": "20",
                        "width": "20",
                        "depth": "10",
                    },
                    "productWeight": str(settings.PAQAR_DEFAULT_WEIGHT_GRAMS),
                    "productCategory": "TCG",
                    "declaredValue": str(int(order.total)),
                }
            ],
            "deliveryType": delivery_type,
            "agencyId": order.shipping_branch if delivery_type == "agency" else "",
            "saleDate": sale_date,
            "shipmentClientId": order.order_code,
            "serviceType": settings.PAQAR_SERVICE_TYPE,
        },
    }

    try:
        resp = requests.post(
            _url("/orders"),
            json=payload,
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as exc:
        body = {}
        try:
            body = exc.response.json()
        except Exception:
            pass
        logger.error("Paq.ar create_order HTTP error %s: %s", exc.response.status_code, body)
        raise PaqarError(f"Paq.ar error {exc.response.status_code}: {body.get('message', str(exc))}")
    except requests.RequestException as exc:
        logger.error("Paq.ar create_order request error: %s", exc)
        raise PaqarError(f"Error de conexión con Paq.ar: {exc}")


# ---------------------------------------------------------------------------
# Cancelar orden
# ---------------------------------------------------------------------------

def cancel_order(tracking_number: str) -> dict:
    """Cancela una orden por trackingNumber."""
    try:
        resp = requests.patch(
            _url(f"/orders/{tracking_number}/cancel"),
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as exc:
        body = {}
        try:
            body = exc.response.json()
        except Exception:
            pass
        raise PaqarError(f"Paq.ar cancelar error {exc.response.status_code}: {body.get('message', str(exc))}")
    except requests.RequestException as exc:
        raise PaqarError(f"Error de conexión con Paq.ar: {exc}")


# ---------------------------------------------------------------------------
# Obtener rótulo (etiqueta PDF en base64)
# ---------------------------------------------------------------------------

def get_label(tracking_number: str, seller_id: str = "", label_format: str = "10x15") -> bytes:
    """
    Obtiene la etiqueta PDF de una orden.
    Retorna el contenido del PDF como bytes.
    label_format: "10x15" (default), "label", o vacío para formato estándar.
    """
    if not seller_id:
        seller_id = str(settings.PAQAR_AGREEMENT)

    headers = _headers()
    params = {}
    if label_format:
        params["labelFormat"] = label_format

    payload = [{"sellerId": seller_id, "trackingNumber": tracking_number}]

    try:
        resp = requests.post(
            _url("/labels"),
            json=payload,
            params=params,
            headers=headers,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.HTTPError as exc:
        body = {}
        try:
            body = exc.response.json()
        except Exception:
            pass
        raise PaqarError(f"Paq.ar get_label error {exc.response.status_code}: {body.get('message', str(exc))}")
    except requests.RequestException as exc:
        raise PaqarError(f"Error de conexión con Paq.ar: {exc}")

    if not data:
        raise PaqarError("Paq.ar no devolvió datos de etiqueta.")

    item = data[0]
    result = item.get("result", "")
    if result.startswith("ERROR"):
        raise PaqarError(f"Paq.ar etiqueta error: {result}")

    import base64
    b64 = item.get("fileBase64", "")
    if not b64:
        raise PaqarError("Paq.ar devolvió base64 vacío para la etiqueta.")

    return base64.b64decode(b64)


# ---------------------------------------------------------------------------
# Tracking / historial
# ---------------------------------------------------------------------------

def get_tracking(tracking_number: str) -> list:
    """Retorna la lista de eventos de una orden."""
    payload = [{"trackingNumber": tracking_number}]
    try:
        resp = requests.get(
            _url("/tracking"),
            json=payload,
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as exc:
        body = {}
        try:
            body = exc.response.json()
        except Exception:
            pass
        raise PaqarError(f"Paq.ar tracking error {exc.response.status_code}: {body.get('message', str(exc))}")
    except requests.RequestException as exc:
        raise PaqarError(f"Error de conexión con Paq.ar: {exc}")


# ---------------------------------------------------------------------------
# Sucursales
# ---------------------------------------------------------------------------

def get_agencies(state_id: str = "", pickup_availability: bool = None, package_reception: bool = None) -> list:
    """Retorna sucursales habilitadas para el acuerdo."""
    params = {}
    if state_id:
        params["stateId"] = state_id
    if pickup_availability is not None:
        params["pickup_availability"] = str(pickup_availability).lower()
    if package_reception is not None:
        params["package_reception"] = str(package_reception).lower()

    try:
        resp = requests.get(
            _url("/agencies"),
            params=params,
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as exc:
        body = {}
        try:
            body = exc.response.json()
        except Exception:
            pass
        raise PaqarError(f"Paq.ar agencies error {exc.response.status_code}: {body.get('message', str(exc))}")
    except requests.RequestException as exc:
        raise PaqarError(f"Error de conexión con Paq.ar: {exc}")


# ---------------------------------------------------------------------------
# Excepción
# ---------------------------------------------------------------------------

class PaqarError(Exception):
    """Error al comunicarse con la API de Paq.ar."""
    pass
