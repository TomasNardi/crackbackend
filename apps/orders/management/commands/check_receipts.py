"""
Verifica que el bucket de comprobantes esté bien antes de habilitar el checkout
por transferencia.

Hace el viaje completo de un comprobante real: sube un archivo, lo lee con un
link firmado, comprueba que SIN firma no se pueda leer, y lo borra.

Ese cuarto paso es el importante y es al revés que en `check_r2`: el bucket del
catálogo tiene que ser público, este no. Un comprobante es un documento bancario
del comprador, y si el bucket quedara expuesto, cualquiera con la URL lo abriría
para siempre.

Uso:
    python manage.py check_receipts
"""

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.catalog.services import r2
from apps.orders.services import receipts

TEST_KEY = "_healthcheck/receipts-check.txt"
TEST_BODY = b"crack-tcg comprobantes ok"


class Command(BaseCommand):
    help = "Prueba el bucket privado de comprobantes (subida, link firmado, privacidad y borrado)"

    def _ok(self):
        self.stdout.write(self.style.SUCCESS("ok"))

    def _fail(self):
        self.stdout.write(self.style.ERROR("falló"))

    def handle(self, *args, **options):
        # 1) Credenciales presentes
        self.stdout.write("1. Variables de entorno... ", ending="")
        missing = [
            name
            for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_RECEIPTS_BUCKET")
            if not getattr(settings, name, "")
        ]
        if missing:
            self._fail()
            raise CommandError(
                "Faltan estas variables en .env: " + ", ".join(missing) + "\n\n"
                "R2_RECEIPTS_BUCKET es el bucket privado de comprobantes "
                "(por ejemplo: crack-comprobantes). Las otras tres las compartís "
                "con el bucket del catálogo."
            )
        bucket = settings.R2_RECEIPTS_BUCKET
        self._ok()

        if bucket == getattr(settings, "R2_BUCKET", ""):
            raise CommandError(
                f"R2_RECEIPTS_BUCKET y R2_BUCKET apuntan al mismo bucket ({bucket}).\n"
                "Los comprobantes tienen que ir a un bucket aparte: el del catálogo "
                "es público y estos no pueden serlo."
            )

        # 2) Alcance del token — es lo que falla si el token de API se creó
        #    limitado al bucket del catálogo en vez de a toda la cuenta.
        self.stdout.write(f"2. Acceso al bucket '{bucket}'... ", ending="")
        try:
            client = r2.get_client()
            client.head_bucket(Bucket=bucket)
        except Exception as exc:  # noqa: BLE001
            self._fail()
            raise CommandError(
                f"No se pudo acceder al bucket: {exc}\n\n"
                "Si el bucket del catálogo funciona y este no, el token de API está\n"
                "limitado a ese bucket. En Cloudflare: R2 → Manage API Tokens → tu\n"
                "token → Edit, y en 'Specify bucket(s)' agregá también este bucket\n"
                f"('{bucket}'), o pasalo a 'Apply to all buckets in this account'.\n"
                "Permiso necesario: Object Read & Write."
            ) from exc
        self._ok()

        # 3) Subida
        self.stdout.write("3. Subida de prueba... ", ending="")
        try:
            client.put_object(
                Bucket=bucket, Key=TEST_KEY, Body=TEST_BODY, ContentType="text/plain"
            )
        except Exception as exc:  # noqa: BLE001
            self._fail()
            raise CommandError(
                f"No se pudo subir: {exc}\n\n"
                "El token puede tener solo lectura. Necesita 'Object Read & Write'."
            ) from exc
        self._ok()

        problemas = []

        # 4) Lectura con link firmado — es como el admin ve el comprobante.
        self.stdout.write("4. Lectura con link firmado... ", ending="")
        signed = receipts.view_url(TEST_KEY)
        if not signed:
            self._fail()
            problemas.append("No se pudo generar el link firmado.")
        else:
            try:
                response = requests.get(signed, timeout=20)
                if response.status_code == 200 and response.content == TEST_BODY:
                    self._ok()
                else:
                    self._fail()
                    problemas.append(
                        f"El link firmado devolvió {response.status_code} en vez del archivo."
                    )
            except requests.RequestException as exc:
                self._fail()
                problemas.append(f"El link firmado no respondió: {exc}")

        # 5) Privacidad — la misma URL sin la firma NO puede servir el archivo.
        self.stdout.write("5. Sin firma no se puede leer... ", ending="")
        unsigned = (signed or "").split("?", 1)[0]
        if not unsigned:
            self.stdout.write(self.style.WARNING("no se pudo probar"))
        else:
            try:
                response = requests.get(unsigned, timeout=20)
                if response.status_code == 200:
                    self._fail()
                    problemas.append(
                        f"¡El bucket está expuesto! {unsigned} devuelve el archivo sin firma.\n"
                        "     En Cloudflare: R2 → el bucket → Settings → deshabilitá la\n"
                        "     Public Development URL y desconectá cualquier dominio."
                    )
                else:
                    self._ok()
            except requests.RequestException:
                # No responder también es estar cerrado.
                self._ok()

        # 6) Limpieza
        self.stdout.write("6. Borrando el archivo de prueba... ", ending="")
        try:
            client.delete_object(Bucket=bucket, Key=TEST_KEY)
            self._ok()
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.WARNING(f"quedó sin borrar: {exc}"))

        if problemas:
            self.stdout.write("")
            for problema in problemas:
                self.stdout.write(self.style.ERROR(f"  • {problema}"))
            raise CommandError("El bucket de comprobantes todavía no está listo.")

        self.stdout.write(self.style.SUCCESS(
            "\nEl bucket de comprobantes está listo y es privado.\n"
            "Ya podés cargar los datos bancarios en el admin:\n"
            "  Configuración → Datos de transferencia"
        ))
