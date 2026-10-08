"""
Configuración de gunicorn. La lee solo al arrancar desde la raíz del servicio
(`gunicorn crackbackend.wsgi:application`); lo que se pase por línea de
comandos en el Start Command de Render tiene prioridad sobre esto.

Por defecto gunicorn levanta UN worker sincrónico: atiende un request a la vez,
y el mismo proceso sirve la API de la tienda, el admin, los estáticos y el ping
del cronjob. Una llamada lenta (Mercado Pago, Cloudinary, un mail, la carga de
stock) dejaba en cola a todo lo demás: abrir otra solapa del admin esperaba a
que terminara la anterior. Con hilos, mientras uno espera la red otro responde.

Un solo proceso a propósito: el plan de Render tiene poca memoria y cada worker
carga Django entero. Los hilos comparten esa memoria. Es lo mismo que Delta Old.
"""

import os

workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
# threads > 1 hace que gunicorn use el worker `gthread`.
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
# Render corta a los 100 s; la carga masiva de un set grande entra holgada.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "90"))
