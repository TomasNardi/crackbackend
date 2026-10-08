"""
Cuentas de compradores (Supabase Auth)
=======================================

El login (Google o código por email) lo resuelve Supabase en el navegador.
Django nunca ve una contraseña: recibe el JWT que firmó Supabase, lo valida
(`supabase_auth.py`) y lo traduce a un `Customer`.

Los compradores NO son `users.User`: esa tabla es la del staff que entra al
admin. Por eso el token viaja en su propio header (`X-Customer-Token`) y nunca
se cruza con el JWT de SimpleJWT (ver `authentication.py`).

La compra como invitado sigue igual. Una cuenta solo suma:
  - Ver sus pedidos: los que hizo con la sesión abierta y los que había hecho
    como invitado con el mismo email (solo si el email está verificado).
  - Guardar datos de contacto y direcciones para el checkout.
"""
