import time
from decimal import Decimal

import jwt
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIClient

from apps.core.models import EmailSubscription
from django.utils import timezone

from apps.orders.models import MercadoPagoPayment, Order

from .models import Customer
from .services import link_order_to_session
from .supabase_auth import get_verifier

SUPABASE_URL = "https://proyecto-test.supabase.co"
SECRET = "secreto-de-prueba-con-largo-suficiente-para-hs256"


def make_token(sub="uid-1", email="comprador@test.com", provider="email", **extra):
    claims = {
        "sub": sub,
        "email": email,
        "role": "authenticated",
        "aud": "authenticated",
        "iss": f"{SUPABASE_URL}/auth/v1",
        "exp": int(time.time()) + 3600,
        "app_metadata": {"provider": provider},
        "user_metadata": {},
        **extra,
    }
    return jwt.encode(claims, SECRET, algorithm="HS256")


@override_settings(
    SUPABASE_URL=SUPABASE_URL,
    SUPABASE_JWT_SECRET=SECRET,
    SUPABASE_TRUST_EMAIL_PROVIDER=True,
    GLOBAL_API_RATELIMIT_ENABLED=False,
)
class CustomerApiTests(TestCase):
    def setUp(self):
        get_verifier.cache_clear()
        self.client = APIClient()

    def tearDown(self):
        get_verifier.cache_clear()

    def auth(self, token=None):
        self.client.credentials(HTTP_X_CUSTOMER_TOKEN=token or make_token())

    def make_order(self, email="comprador@test.com", **extra):
        return Order.objects.create(
            customer_name="Ash Ketchum", customer_email=email, customer_phone="1150000000",
            total=Decimal("1000"), **extra,
        )

    def test_without_token_is_401(self):
        self.assertEqual(self.client.get("/api/v1/customers/orders/").status_code, 401)

    def test_bad_token_is_401(self):
        self.auth("no-es-un-jwt")
        self.assertEqual(self.client.get("/api/v1/customers/profile/").status_code, 401)

    def test_token_from_other_project_is_401(self):
        token = make_token(iss="https://otro.supabase.co/auth/v1")
        self.auth(token)
        self.assertEqual(self.client.get("/api/v1/customers/profile/").status_code, 401)

    def test_session_creates_customer_and_claims_guest_orders(self):
        mine = self.make_order(email="Comprador@Test.com")
        other = self.make_order(email="otro@test.com")
        self.auth()

        res = self.client.post("/api/v1/customers/session/")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["linked_orders"], 1)
        # El perfil se completa con la última compra.
        self.assertEqual(res.data["profile"]["first_name"], "Ash")
        self.assertEqual(res.data["profile"]["phone"], "1150000000")
        customer = Customer.objects.get(supabase_uid="uid-1")
        mine.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(mine.customer, customer)
        self.assertIsNone(other.customer)

        orders = self.client.get("/api/v1/customers/orders/").data
        self.assertEqual([o["order_code"] for o in orders], [mine.order_code])
        self.assertEqual(orders[0]["status_label"], "Pago pendiente")

    def test_unverified_email_does_not_claim_orders(self):
        self.make_order()
        with self.settings(SUPABASE_TRUST_EMAIL_PROVIDER=False):
            self.auth()
            res = self.client.post("/api/v1/customers/session/")
        self.assertEqual(res.data["linked_orders"], 0)

    def test_google_verified_email_claims_orders(self):
        self.make_order()
        with self.settings(SUPABASE_TRUST_EMAIL_PROVIDER=False):
            self.auth(make_token(provider="google", user_metadata={"email_verified": True, "full_name": "Misty Waterflower"}))
            res = self.client.post("/api/v1/customers/session/")
        self.assertEqual(res.data["linked_orders"], 1)
        # El nombre de Google gana sobre el de la compra.
        self.assertEqual(res.data["profile"]["first_name"], "Misty")

    def test_marketing_opt_in_subscribes_session_email(self):
        self.auth()
        self.client.post("/api/v1/customers/session/", {"marketing_opt_in": True}, format="json")
        self.assertTrue(EmailSubscription.objects.get(email="comprador@test.com").is_active)

    def test_marketing_opt_in_reactivates_and_never_unsubscribes(self):
        EmailSubscription.objects.create(email="comprador@test.com", is_active=False)
        self.auth()
        self.client.post("/api/v1/customers/session/", {"marketing_opt_in": True}, format="json")
        self.assertTrue(EmailSubscription.objects.get(email="comprador@test.com").is_active)
        # Volver a entrar sin marcar el checkbox no lo da de baja.
        self.client.post("/api/v1/customers/session/", {}, format="json")
        self.assertTrue(EmailSubscription.objects.get(email="comprador@test.com").is_active)

    def test_without_opt_in_nothing_is_subscribed(self):
        self.auth()
        self.client.post("/api/v1/customers/session/")
        self.assertFalse(EmailSubscription.objects.exists())

    def test_profile_update(self):
        self.auth()
        res = self.client.patch(
            "/api/v1/customers/profile/",
            {"first_name": "Brock", "last_name": "Harrison", "phone": "11223344", "email": "hack@x.com"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["first_name"], "Brock")
        # El email lo maneja Supabase: no se puede cambiar desde acá.
        self.assertEqual(res.data["email"], "comprador@test.com")

    def test_addresses_keep_a_single_default(self):
        self.auth()
        data = {"address": "Deheza 2921", "city": "CABA", "province": "CABA", "zip_code": "1429"}
        first = self.client.post("/api/v1/customers/addresses/", data, format="json").data
        self.assertTrue(first["is_default"])

        second = self.client.post(
            "/api/v1/customers/addresses/", {**data, "address": "Otra 123", "is_default": True}, format="json"
        ).data
        listed = {a["id"]: a["is_default"] for a in self.client.get("/api/v1/customers/addresses/").data}
        self.assertEqual(listed, {first["id"]: False, second["id"]: True})

        self.client.delete(f"/api/v1/customers/addresses/{second['id']}/")
        listed = self.client.get("/api/v1/customers/addresses/").data
        self.assertEqual([(a["id"], a["is_default"]) for a in listed], [(first["id"], True)])

    def test_home_and_branch_each_keep_their_own_default(self):
        self.auth()
        home = {"address": "Deheza 2921", "city": "CABA", "province": "CABA", "zip_code": "1429"}
        branch = {**home, "kind": "branch", "branch_name": "Correo Córdoba Centro",
                  "address": "Av. Colón 210", "city": "Córdoba", "province": "Córdoba", "zip_code": "5000"}
        h = self.client.post("/api/v1/customers/addresses/", home, format="json").data
        b = self.client.post("/api/v1/customers/addresses/", branch, format="json").data
        # La primera de cada tipo es predeterminada, sin pisarse entre sí.
        self.assertTrue(h["is_default"])
        self.assertTrue(b["is_default"])
        self.assertEqual(b["branch_name"], "Correo Córdoba Centro")

        b2 = self.client.post("/api/v1/customers/addresses/", {**branch, "address": "Otra 1", "is_default": True}, format="json").data
        listed = {a["id"]: a["is_default"] for a in self.client.get("/api/v1/customers/addresses/").data}
        self.assertEqual(listed, {h["id"]: True, b["id"]: False, b2["id"]: True})

        # Pasar la predeterminada de sucursal a domicilio deja otra sucursal como predeterminada.
        self.client.patch(f"/api/v1/customers/addresses/{b2['id']}/", {"kind": "home", "is_default": False}, format="json")
        listed = {a["id"]: (a["kind"], a["is_default"]) for a in self.client.get("/api/v1/customers/addresses/").data}
        self.assertEqual(listed[b["id"]], ("branch", True))
        self.assertEqual(listed[h["id"]], ("home", True))
        self.assertEqual(listed[b2["id"]], ("home", False))

    def test_order_timeline_with_mercadopago_payment(self):
        order = self.make_order(status=Order.STATUS_PAID, payment_method=Order.PAYMENT_MERCADOPAGO)
        MercadoPagoPayment.objects.create(
            order=order, preference_id="pref-1", payment_id="123456789", is_paid=True, date_approved=timezone.now(),
        )
        self.auth()
        self.client.post("/api/v1/customers/session/")

        data = self.client.get("/api/v1/customers/orders/").data[0]

        self.assertEqual([e["title"] for e in data["timeline"]], ["Pedido realizado", "Pago aprobado por Mercado Pago"])
        self.assertTrue(all(e["at"] for e in data["timeline"]))
        self.assertEqual(data["payment"]["operation_id"], "123456789")
        self.assertEqual(data["status_label"], "Preparando envío")

    def test_invalid_zip_is_rejected(self):
        self.auth()
        res = self.client.post(
            "/api/v1/customers/addresses/",
            {"address": "Deheza 2921", "city": "CABA", "province": "CABA", "zip_code": "abc"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_cannot_touch_someone_elses_address(self):
        self.auth(make_token(sub="uid-otro", email="otro@test.com"))
        data = {"address": "Deheza 2921", "city": "CABA", "province": "CABA", "zip_code": "1429"}
        ajena = self.client.post("/api/v1/customers/addresses/", data, format="json").data

        self.auth()
        self.assertEqual(self.client.delete(f"/api/v1/customers/addresses/{ajena['id']}/").status_code, 404)

    def test_checkout_with_session_links_order_even_with_other_email(self):
        order = self.make_order(email="mail-distinto@test.com")
        request = RequestFactory().post("/api/v1/orders/", HTTP_X_CUSTOMER_TOKEN=make_token())
        with self.captureOnCommitCallbacks(execute=True):
            link_order_to_session(order, request)
        order.refresh_from_db()
        self.assertEqual(order.customer.supabase_uid, "uid-1")

    def test_checkout_with_broken_token_stays_as_guest(self):
        order = self.make_order()
        request = RequestFactory().post("/api/v1/orders/", HTTP_X_CUSTOMER_TOKEN="roto")
        with self.captureOnCommitCallbacks(execute=True):
            link_order_to_session(order, request)  # no levanta
        order.refresh_from_db()
        self.assertIsNone(order.customer)

    def test_staff_endpoints_ignore_customer_token(self):
        # El token de cliente no da acceso al listado de órdenes del admin.
        self.auth()
        self.assertIn(self.client.get("/api/v1/orders/").status_code, (401, 403))
