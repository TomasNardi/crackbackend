"""
Verifica que las credenciales de Cloudflare R2 estén bien antes de largar la
ingesta del catálogo.

Hace el viaje completo: sube un archivo de prueba, comprueba que exista, lo lee
por la URL pública y lo borra. Si algo está mal, te dice qué.

Uso:
    python manage.py check_r2
"""

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.catalog.services import r2

REQUIRED_SETTINGS = (
    "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET", "R2_PUBLIC_BASE_URL",
)

TEST_KEY = "_healthcheck/r2-check.txt"
TEST_BODY = b"crack-tcg r2 ok"


class Command(BaseCommand):
    help = "Prueba la conexión con Cloudflare R2 (subida, lectura pública y borrado)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep", action="store_true",
            help="No borra el archivo de prueba al terminar.",
        )

    def handle(self, *args, **options):
        # 1) Credenciales presentes
        self.stdout.write("1. Variables de entorno... ", ending="")
        missing = [name for name in REQUIRED_SETTINGS if not getattr(settings, name, "")]
        if missing:
            self.stdout.write(self.style.ERROR("faltan"))
            raise CommandError(
                "Faltan estas variables en .env: " + ", ".join(missing)
            )
        self.stdout.write(self.style.SUCCESS("ok"))

        # 2) Cliente y credenciales válidas
        self.stdout.write("2. Conexión y credenciales... ", ending="")
        try:
            client = r2.get_client()
            client.head_bucket(Bucket=r2._require("R2_BUCKET"))
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.ERROR("falló"))
            raise CommandError(
                f"No se pudo acceder al bucket: {exc}\n\n"
                "Revisá que R2_ACCOUNT_ID sea el Account ID de Cloudflare, que el "
                "token tenga permiso 'Object Read & Write' y que R2_BUCKET sea el "
                "nombre exacto del bucket."
            ) from exc
        self.stdout.write(self.style.SUCCESS("ok"))

        # 3) Subida
        self.stdout.write("3. Subida de prueba... ", ending="")
        try:
            url = r2.upload_bytes(TEST_KEY, TEST_BODY, content_type="text/plain")
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.ERROR("falló"))
            raise CommandError(f"No se pudo subir: {exc}") from exc
        self.stdout.write(self.style.SUCCESS("ok"))

        # 4) Lectura pública — es el paso que más falla, porque el bucket
        #    arranca privado y hay que habilitarle acceso público a mano.
        self.stdout.write("4. Lectura por la URL pública... ", ending="")
        try:
            response = requests.get(url, timeout=20)
            public_ok = response.status_code == 200 and response.content == TEST_BODY
        except requests.RequestException:
            public_ok = False

        if public_ok:
            self.stdout.write(self.style.SUCCESS("ok"))
        else:
            self.stdout.write(self.style.ERROR("falló"))
            self.stdout.write(self.style.WARNING(
                f"\n  Se subió bien, pero {url} no responde.\n"
                "  El bucket todavía no tiene acceso público. En Cloudflare:\n"
                "  R2 → tu bucket → Settings → Public access → Connect Domain\n"
                "  (o habilitá el subdominio r2.dev para probar).\n"
                "  Y verificá que R2_PUBLIC_BASE_URL sea ese dominio, sin barra final."
            ))

        # 5) Limpieza
        if not options["keep"]:
            self.stdout.write("5. Borrando el archivo de prueba... ", ending="")
            try:
                client.delete_object(Bucket=r2._require("R2_BUCKET"), Key=TEST_KEY)
                self.stdout.write(self.style.SUCCESS("ok"))
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.WARNING(f"quedó sin borrar: {exc}"))

        if public_ok:
            self.stdout.write(self.style.SUCCESS(
                "\nR2 está listo. Ya podés correr:\n"
                "  python manage.py import_catalog\n"
                "  python manage.py sync_catalog_images"
            ))
        else:
            raise CommandError("R2 sube archivos pero todavía no los sirve al público.")
