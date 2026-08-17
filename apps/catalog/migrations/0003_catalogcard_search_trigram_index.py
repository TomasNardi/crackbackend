"""
Índice trigram para el buscador del catálogo.

El buscador de carga de stock filtra con `search_text__icontains`, o sea
`LIKE '%charizard%'`. Un índice B-tree común no sirve para eso: el comodín de
adelante obliga a leer las 63k filas enteras en cada tecla.

`pg_trgm` resuelve exactamente ese caso. Parte el texto en trigramas ("cha",
"har", "ari"...) y los indexa con GIN, así que un LIKE con comodín a ambos lados
pasa a ser una búsqueda por índice.

Dos detalles que importan:

  * La expresión indexada tiene que ser idéntica a la que escribe Django. Para
    `icontains` sobre Postgres el ORM genera `UPPER("col"::text) LIKE UPPER(%s)`,
    así que el índice va sobre `UPPER(search_text::text)`. Si se indexa la
    columna pelada, Postgres no lo usa y la migración no cambia nada.

  * Es todo Postgres. En SQLite (desarrollo local) no existe la extensión, así
    que la migración no hace nada y la búsqueda sigue funcionando como siempre.

Tokens de menos de 3 letras no generan trigramas completos y caen igual en un
escaneo; no molesta porque el buscador ya pide un mínimo de 2 caracteres y las
búsquedas reales son por nombre y número.
"""

import logging

from django.db import migrations

logger = logging.getLogger(__name__)

INDEX_NAME = "catalog_card_search_trgm"

CREATE_SQL = f"""
CREATE INDEX IF NOT EXISTS {INDEX_NAME}
    ON catalog_catalogcard
    USING gin (UPPER(search_text::text) gin_trgm_ops);
"""

DROP_SQL = f"DROP INDEX IF EXISTS {INDEX_NAME};"


def create_trigram_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        logger.info("Índice trigram omitido: la base no es PostgreSQL.")
        return

    with schema_editor.connection.cursor() as cursor:
        try:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        except Exception as exc:  # noqa: BLE001 — depende de permisos del rol
            # Si el usuario de la base no puede crear extensiones, el buscador
            # sigue andando (más lento). Romper el deploy por esto sería peor.
            logger.warning(
                "No se pudo habilitar pg_trgm: %s. El buscador del catálogo va a "
                "seguir escaneando la tabla entera.", exc,
            )
            return

        cursor.execute(CREATE_SQL)


def drop_trigram_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(DROP_SQL)


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0002_cardset_source_modified_at"),
    ]

    operations = [
        migrations.RunPython(create_trigram_index, drop_trigram_index),
    ]
