"""
Verifica que el buscador del catálogo esté usando el índice trigram.

El índice lo crea la migración 0003, pero puede no haber quedado: si el rol de
la base no tiene permiso para crear extensiones, la migración avisa y sigue de
largo en vez de romper el deploy. Este comando dice si quedó o no, y —lo que
importa de verdad— si el planificador realmente lo usa.

Uso (en la shell de Render):
    python manage.py check_search_index
    python manage.py check_search_index --q charizard
"""

import time

from django.core.management.base import BaseCommand
from django.db import connection

INDEX_NAME = "catalog_card_search_trgm"


class Command(BaseCommand):
    help = "Comprueba que la búsqueda del catálogo use el índice trigram"

    def add_arguments(self, parser):
        parser.add_argument(
            "--q", default="charizard",
            help="Texto a probar. Usá uno real, de 3 letras o más.",
        )

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write(self.style.WARNING(
                f"La base es {connection.vendor}, no PostgreSQL. El índice trigram "
                f"es exclusivo de Postgres: en desarrollo local esto no aplica."
            ))
            return

        query = options["q"]

        with connection.cursor() as cursor:
            # 1) ¿Está la extensión?
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm';")
            has_extension = cursor.fetchone() is not None
            self._report("Extensión pg_trgm", has_extension, "falta habilitarla")

            # 2) ¿Está el índice?
            cursor.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s;", [INDEX_NAME])
            has_index = cursor.fetchone() is not None
            self._report(f"Índice {INDEX_NAME}", has_index, "no se creó")

            if not (has_extension and has_index):
                self.stdout.write(self.style.ERROR(
                    "\nEl buscador está escaneando la tabla entera en cada tecla.\n"
                    "Volvé a correr: python manage.py migrate catalog"
                ))
                return

            # 3) Lo único que importa: ¿el planificador lo usa?
            #
            # La consulta tiene que ser idéntica a la que arma el ORM para
            # `search_text__icontains`, si no el EXPLAIN mide otra cosa.
            sql = (
                'SELECT id FROM catalog_catalogcard '
                'WHERE UPPER(search_text::text) LIKE UPPER(%s)'
            )
            cursor.execute("EXPLAIN ANALYZE " + sql, [f"%{query}%"])
            plan = "\n".join(row[0] for row in cursor.fetchall())

            uses_index = INDEX_NAME in plan
            self._report(f"El plan de '{query}' usa el índice", uses_index,
                         "Postgres prefirió escanear la tabla")

            # 4) Tiempo real de la consulta, sin el ida y vuelta de Django.
            start = time.perf_counter()
            cursor.execute(sql, [f"%{query}%"])
            cursor.fetchall()
            elapsed = (time.perf_counter() - start) * 1000

        self.stdout.write(f"\nTiempo de la búsqueda: {elapsed:.1f} ms")
        self.stdout.write(self.style.HTTP_INFO("\nPlan:\n" + plan))

        if uses_index:
            self.stdout.write(self.style.SUCCESS("\nTodo en orden."))
        else:
            self.stdout.write(self.style.WARNING(
                "\nEl índice existe pero no se usa. Suele pasar cuando el texto "
                "buscado tiene menos de 3 letras (no llega a formar un trigrama) "
                "o cuando la tabla es tan chica que escanearla sale más barato. "
                "Probá con --q de una carta real."
            ))

    def _report(self, label, ok, problem):
        mark = self.style.SUCCESS("OK") if ok else self.style.ERROR(f"NO — {problem}")
        self.stdout.write(f"{label}... {mark}")
