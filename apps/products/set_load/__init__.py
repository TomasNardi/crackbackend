"""
Carga masiva por expansión: elegís un set y cargás el stock de todas sus cartas
desde una grilla, con un solo guardado. Es la de Delta Old, adaptada a Crack.

Capas (de adentro hacia afuera, cada una solo conoce a las de adentro):
    domain       reglas puras: validar filas y decidir altas vs. sumas
    repository   Django ORM: lecturas agregadas, bulk_create / bulk_update
    services     orquesta y define la transacción (todo o nada, idempotente)
    views        HTTP: JSON de entrada y salida, códigos de estado
"""
